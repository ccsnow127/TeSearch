"""Turning the TestGenEval-lite dataset into search tasks.

The dataset (``kjain14/testgenevallite`` on HuggingFace, split ``test``) has 160
rows, one per (module, commit) pair, with the columns

    repo, base_commit, version, instance_id, patch, test_patch, preds_context,
    code_src, test_src, code_file, test_file, local_imports, id, baseline_covs

A run targets a module, not a commit, so rows are grouped by ``(repo, code_file)``
into 129 distinct modules. A module that appears at several releases is
represented by its newest one, and all of its instance ids are kept.

The repository's own tests (``test_src``) are carried along but never shown to the
model -- that would be handing over the answer. ``test_file`` is only the path the
generated suite gets written to inside the container.
"""
from __future__ import annotations

import ast
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parents[2] / "data" / "testgenevallite"
IMAGE_NAMESPACE = "kdjain"
# Repositories whose testbed image is built per instance rather than per release,
# as declared by the benchmark's own image configuration.
_INSTANCE_IMAGE_REPOS = {"scikit-learn/scikit-learn"}

COLUMNS = ("repo", "base_commit", "version", "instance_id", "patch", "test_patch",
           "preds_context", "code_src", "test_src", "code_file", "test_file",
           "local_imports", "id", "baseline_covs")


@dataclass(frozen=True)
class ModuleTask:
    """One module under test, with everything the harness needs to rebuild it."""

    repo: str
    version: str
    instance_id: str
    row_id: str                     # the dataset's ``id`` column
    base_commit: str
    patch: str
    code_file: str                  # repo-relative path of the module under test
    code_src: str                   # module source shown to the model
    test_file: str                  # repo-relative path the suite is written to
    test_src: str = field(repr=False, default="")
    local_imports: tuple = field(repr=False, default=())
    instance_ids: tuple = ()        # every lite instance of this module

    @property
    def module_id(self) -> str:
        return f"{self.repo}::{self.code_file}"

    @property
    def slug(self) -> str:
        """Filesystem-safe name, e.g. ``django__django__db.models.query_utils``."""
        return f"{self.repo.replace('/', '__')}__{self.dotted}"

    @property
    def image(self) -> str:
        repo = self.repo.replace("/", "_")
        if self.repo in _INSTANCE_IMAGE_REPOS:
            return f"{IMAGE_NAMESPACE}/swe-bench-{repo}-instance:{self.instance_id}"
        return f"{IMAGE_NAMESPACE}/swe-bench-{repo}-testbed:{self.version}"

    @property
    def dotted(self) -> str:
        """Import path of the module: ``src/_pytest/nodes.py`` -> ``_pytest.nodes``."""
        path = self.code_file
        for prefix in ("src/", "lib/"):
            if path.startswith(prefix):
                path = path[len(prefix):]
                break
        if path.endswith(".py"):
            path = path[:-3]
        return path.replace("/", ".").strip(".")

    @property
    def s_min(self) -> int:
        """Smallest sensible suite: one test per public function or method.

        Below this a test has to check several callables at once, which makes it
        hard to read and lets a suite game the size objective by packing
        everything into one function.
        """
        return count_public_callables(self.code_src)


def count_public_callables(src: str) -> int:
    """Public top-level functions plus public methods of public top-level classes."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return 1
    fn = (ast.FunctionDef, ast.AsyncFunctionDef)
    n = 0
    for node in tree.body:
        if isinstance(node, fn) and not node.name.startswith("_"):
            n += 1
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            n += sum(1 for m in node.body
                     if isinstance(m, fn) and not m.name.startswith("_"))
    return max(1, n)


def load_rows(split: str = "test", root: Path | str = DATA_ROOT) -> list[dict]:
    """Rows of the lite parquet, as dicts keyed by the dataset's own columns."""
    import pyarrow.parquet as pq

    path = Path(root) / f"{split}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run scripts/fetch_data.sh first")
    rows = pq.read_table(path).to_pylist()
    missing = set(COLUMNS) - set(rows[0]) if rows else set()
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    return rows


def _version_key(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"[.\-]", v))


def _instance_number(instance_id: str) -> int:
    m = re.search(r"-(\d+)$", instance_id)
    return int(m.group(1)) if m else 0


def _to_task(row: dict, instance_ids: tuple) -> ModuleTask:
    return ModuleTask(
        repo=row["repo"], version=row["version"], instance_id=row["instance_id"],
        row_id=row["id"], base_commit=row["base_commit"], patch=row["patch"] or "",
        code_file=row["code_file"], code_src=row["code_src"],
        test_file=row["test_file"], test_src=row["test_src"] or "",
        local_imports=tuple(row["local_imports"] or ()), instance_ids=instance_ids)


def load_modules(split: str = "test", root: Path | str = DATA_ROOT) -> list[ModuleTask]:
    """The distinct modules of the split, sorted by module id."""
    groups: dict[tuple, list[dict]] = {}
    for row in load_rows(split, root):
        groups.setdefault((row["repo"], row["code_file"]), []).append(row)
    tasks = []
    for key in sorted(groups):
        rows = groups[key]
        rep = max(rows, key=lambda r: (_version_key(r["version"]),
                                       _instance_number(r["instance_id"])))
        ids = tuple(sorted(r["instance_id"] for r in rows))
        tasks.append(_to_task(rep, ids))
    return tasks


def get_module(key: str, split: str = "test", root: Path | str = DATA_ROOT) -> ModuleTask:
    """Look a module up by module id, slug, dotted path, row id or instance id.

    A row id or instance id pins that exact instance (its commit and version)
    rather than the module's representative.
    """
    for task in load_modules(split, root):
        if key in (task.module_id, task.slug, task.dotted, task.code_file):
            return task
    for row in load_rows(split, root):
        if key in (row["id"], row["instance_id"]):
            same = sorted(r["instance_id"] for r in load_rows(split, root)
                          if (r["repo"], r["code_file"]) == (row["repo"], row["code_file"]))
            return _to_task(row, tuple(same))
    raise KeyError(f"no module matches {key!r}")


SUBSET_ROOT = DATA_ROOT.parent / "subsets"


def load_subset(name: str, split: str = "test") -> list[ModuleTask]:
    """Tasks listed in ``data/subsets/<name>.txt`` (one instance id per line;
    ``#`` starts a comment). Each line pins that exact instance."""
    path = Path(name) if Path(name).exists() else SUBSET_ROOT / f"{name}.txt"
    keys = [ln.split("#", 1)[0].strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    return [get_module(k, split) for k in keys if k]


def summary(tasks: list[ModuleTask]) -> Counter:
    return Counter(t.repo for t in tasks)
