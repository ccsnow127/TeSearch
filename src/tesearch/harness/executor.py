"""The container a module's suites are run in.

The search runs on the host and only produces text. All execution happens in one
resident container per module, started from that instance's TestGenEval testbed
image and reused through ``docker exec`` for the whole run. The host never imports
the repository under test, and the eval-fold mutant sources never leave the
container.

Two image families occur in the benchmark and are probed at startup:
  * conda testbeds — repository under the service user's home, commands wrapped
    in ``conda run -n <repo>__<version>``;
  * pyenv testbeds — repository under /opt, interpreter resolved by the shims.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from ..data import ModuleTask

CONDA = "/home/swe-bench/miniconda3/bin/conda"
HELPER = Path(__file__).resolve().parent / "container" / "tp_container.py"
MUT_DIR = "/tmp/mut"


class DockerExecutor:
    def __init__(self, task: ModuleTask, search_n: int = 60, eval_n: int = 800,
                 seed: int = 0, name: str | None = None) -> None:
        self.task = task
        self.search_n = search_n
        self.eval_n = eval_n
        self.seed = seed
        self.name = name or f"tesearch_{uuid.uuid4().hex[:10]}"
        env = task.repo.replace("/", "__")
        self.repo_dir = f"/home/swe-bench/{env}"   # replaced by _detect_layout()
        self.conda_env = f"{env}__{task.version}"
        self.image_type = "conda"
        self.n_search = self.n_eval = 0
        self.mutants: dict[str, dict] = {}

    # ------------------------------------------------------------- lifecycle
    def __enter__(self) -> "DockerExecutor":
        self._rm()
        self._run(["docker", "run", "-d", "--name", self.name, "--network", "host",
                   "--platform", "linux/amd64", "--entrypoint", "sleep",
                   self.task.image, "infinity"])
        try:
            self._detect_layout()
            self._align_repo()
            self._put(HELPER.read_text(encoding="utf-8"), "/tmp/tp_container.py")
            self._ensure_probe_deps()
            self._ensure_built()
            self._materialize_mutants()
        except Exception:
            self._rm()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self._rm()

    # ------------------------------------------------------------ public API
    def probe(self, suite_src: str) -> dict:
        """pytest + coverage: {tests: [{name, verdict, traceback}], coverage,
        uncovered, output}."""
        self._put(suite_src, "/tmp/suite.py")
        out = self._exec(f"python /tmp/tp_container.py probe --module {self.task.code_file} "
                         f"--test-file {self.task.test_file} --suite /tmp/suite.py")
        return _last_json(out, {"tests": [], "coverage": 0.0, "uncovered": [], "output": out[-3000:]})

    def mutate(self, suite_src: str, fold: str) -> dict:
        """Score a suite against the ``search`` or ``eval`` fold:
        {mutation, survivors, total, green}."""
        self._put(suite_src, "/tmp/suite.py")
        out = self._exec(f"python /tmp/tp_container.py mutate --module {self.task.code_file} "
                         f"--test-file {self.task.test_file} --suite /tmp/suite.py "
                         f"--fold {MUT_DIR}/{fold}")
        return _last_json(out, {"mutation": 0.0, "survivors": [], "total": 0, "green": False})

    # ---------------------------------------------------------------- set-up
    def _detect_layout(self) -> None:
        out = self._run(["docker", "exec", "-u", "root", self.name, "bash", "-c",
                         "echo REPO_DIR=$REPO_DIR; echo IMAGE_TYPE=$IMAGE_TYPE"])
        for line in out.splitlines():
            key, _, value = line.partition("=")
            if key == "REPO_DIR" and value.strip():
                self.repo_dir = value.strip()
            elif key == "IMAGE_TYPE" and value.strip():
                self.image_type = value.strip()

    def _align_repo(self) -> None:
        """Check out the instance's commit and apply its patch.

        Testbed images are shared per version, so without the checkout the module
        under test could come from a different commit than the one the model sees.
        The module file is then overwritten with ``code_src`` so the marks shown to
        the model line up with what is executed.
        """
        t = self.task
        if t.base_commit:
            self._run(["docker", "exec", "-u", "root", self.name, "bash", "-c",
                       f"cd {self.repo_dir} && git -c safe.directory='*' checkout -qf {t.base_commit}"])
            if t.patch:
                subprocess.run(["docker", "exec", "-i", "-u", "root", self.name, "bash", "-c",
                                f"cd {self.repo_dir} && git -c safe.directory='*' apply -"],
                               input=t.patch, text=True, capture_output=True, timeout=120)
        self._put(t.code_src, f"{self.repo_dir}/{t.code_file}")

    def _ensure_probe_deps(self) -> None:
        """pytest and coverage must import in the testbed interpreter itself."""
        check = "python -c \"import pytest, coverage; print('DEPS_OK')\" 2>&1 | tail -2"
        install = "python -m pip install -q pytest coverage 2>&1 | tail -3"
        if self.image_type == "pyenv":
            run = self._exec
        else:
            envpy = f"/home/swe-bench/miniconda3/envs/{self.conda_env}/bin/python"
            run = lambda cmd: self._run(["docker", "exec", "-u", "root", self.name, "bash",
                                         "-c", cmd.replace("python ", f"{envpy} ", 1)])
        try:
            if "DEPS_OK" in run(check):
                return
        except RuntimeError:
            pass
        run(install)

    def _ensure_built(self) -> None:
        """Compiled repositories may ship unbuilt; build them in place if the
        top-level package does not import."""
        parts = self.task.code_file.split("/")
        pkg = parts[1] if parts[0] in ("src", "lib") and len(parts) > 1 else parts[0]
        pkg = pkg[:-3] if pkg.endswith(".py") else pkg
        if not pkg.isidentifier():
            return
        check = f"python -c \"import {pkg}; print('BUILD_OK')\" 2>&1 | tail -2"
        if "BUILD_OK" in self._try_exec(check):
            return
        for cmd in ("python -m pip install -q --no-build-isolation --no-use-pep517 -e . 2>&1 | tail -3",
                    "python setup.py build_ext --inplace 2>&1 | tail -3"):
            self._try_exec(cmd)
            if "BUILD_OK" in self._try_exec(check):
                return

    def _materialize_mutants(self) -> None:
        """Generate the two folds once, inside the container when its interpreter
        has cosmic-ray, otherwise on the host (same helper, same seed) and copy
        them in; the container then only runs suites against the files."""
        args = (f"gen --module {self.task.code_file} --out {MUT_DIR} --seed {self.seed} "
                f"--search-n {self.search_n} --eval-n {self.eval_n}")
        try:
            out = self._exec(f"python /tmp/tp_container.py {args}")
            info = json.loads(out.strip().splitlines()[-1])
        except (RuntimeError, ValueError, IndexError):
            info = self._gen_on_host()
        self.n_search, self.n_eval = info["n_search"], info["n_eval"]
        manifest = json.loads(self._exec(f"cat {MUT_DIR}/manifest.json"))
        self.mutants = {m["id"]: m for m in manifest}
        if self.n_search == 0:
            raise RuntimeError(f"{self.task.module_id}: no mutants generated")

    def _gen_on_host(self) -> dict:
        with tempfile.TemporaryDirectory() as td:
            mod = Path(td) / self.task.code_file
            mod.parent.mkdir(parents=True, exist_ok=True)
            mod.write_text(self.task.code_src, encoding="utf-8")
            out_dir = Path(td) / "mut"
            p = subprocess.run([sys.executable, str(HELPER), "gen", "--module",
                                self.task.code_file, "--out", str(out_dir),
                                "--seed", str(self.seed), "--search-n", str(self.search_n),
                                "--eval-n", str(self.eval_n)],
                               cwd=td, capture_output=True, text=True, timeout=1800)
            if p.returncode != 0:
                raise RuntimeError(f"mutant generation failed: {p.stderr[-800:]}")
            self._run(["docker", "exec", "-u", "root", self.name, "rm", "-rf", MUT_DIR])
            self._run(["docker", "cp", str(out_dir), f"{self.name}:{MUT_DIR}"])
            return json.loads(p.stdout.strip().splitlines()[-1])

    # ------------------------------------------------------------ docker glue
    def _exec(self, cmd: str) -> str:
        """Run under the testbed interpreter. ``bash -c`` (not a login shell) keeps
        the pyenv shims on PATH; utf-8 stdio because testbeds run a POSIX locale."""
        prefix = f"cd {self.repo_dir} && PYTHONIOENCODING=utf-8 "
        if self.image_type == "pyenv":
            full = prefix + cmd
        else:
            full = prefix + f"{CONDA} run -n {self.conda_env} {cmd}"
        return self._run(["docker", "exec", "-u", "root", self.name, "bash", "-c", full])

    def _try_exec(self, cmd: str) -> str:
        try:
            return self._exec(cmd)
        except RuntimeError as exc:
            return str(exc)

    def _put(self, content: str, dst: str) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(content)
            tmp = f.name
        try:
            self._run(["docker", "cp", tmp, f"{self.name}:{dst}"])
        finally:
            Path(tmp).unlink(missing_ok=True)

    def _rm(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True, text=True)

    @staticmethod
    def _run(cmd: list[str]) -> str:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode != 0:
            raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd)[:300]}\n"
                               f"{p.stdout[-2000:]}\n{p.stderr[-2000:]}")
        return p.stdout


def _last_json(out: str, default: dict) -> dict:
    for line in reversed(out.strip().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return default
