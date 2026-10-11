"""Measurement helper that runs inside the module's testbed container.

Standard library only (plus cosmic_ray for ``gen``, and pytest/coverage in the
testbed interpreter). Written to run unchanged on Python 3.6, the oldest
interpreter among the TestGenEval testbeds.

    gen     enumerate cosmic-ray mutants of the module once, and split them into a
            stratified search fold and a disjoint held-out eval fold
    probe   run a suite under pytest + coverage: per-test verdicts, line coverage
            of the module, and its missing lines
    mutate  score a (green) suite against one fold: kill rate and survivors
"""
import argparse
import ast
import json
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

PIPE = subprocess.PIPE

FAMILIES = [
    ("ReplaceBinaryOperator", "binary"),
    ("ReplaceComparisonOperator", "comparison"),
    ("ReplaceUnaryOperator", "unary"),
    ("NumberReplacer", "number"),
    ("AddNot", "logic"), ("ReplaceAndWithOr", "logic"), ("ReplaceOrWithAnd", "logic"),
    ("ReplaceTrueWithFalse", "boolean"), ("ReplaceFalseWithTrue", "boolean"),
    ("ReplaceBreakWithContinue", "loopflow"), ("ReplaceContinueWithBreak", "loopflow"),
    ("ZeroIterationForLoop", "loopflow"),
    ("RemoveDecorator", "decorator"),
    ("ExceptionReplacer", "exception"),
    ("VariableInserter", "variable"), ("VariableReplacer", "variable"),
]

PYTEST_ARGS = ["-W", "ignore::pytest.PytestConfigWarning", "--override-ini=addopts=",
               "-p", "no:cacheprovider"]


def family_of(op):
    short = op.split("/")[-1]
    for prefix, fam in FAMILIES:
        if short.startswith(prefix):
            return fam
    return "other"


# ============================================================== mutant folds
def _first_diff_line(orig, mutated):
    o, m = orig.splitlines(), mutated.splitlines()
    for i in range(min(len(o), len(m))):
        if o[i] != m[i]:
            return i + 1
    return min(len(o), len(m)) + 1


def _function_spans(src):
    """(start, end) lines of every function; end_lineno needs 3.8+, so older
    interpreters close a span at the next def."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    fns = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    starts = sorted(n.lineno for n in fns)
    total = src.count("\n") + 1
    spans = []
    for n in fns:
        end = getattr(n, "end_lineno", None)
        if end is None:
            later = [s for s in starts if s > n.lineno]
            end = min(later) - 1 if later else total
        spans.append((n.lineno, end))
    return spans


def stratified_search_fold(pool, src, n, seed):
    """Region-then-family stratification of the search fold.

    Regions are functions (the innermost span containing the mutated line). Each
    region with mutants gets at least one pick, largest pools first; the rest of
    the budget is allotted proportionally by largest remainder. Within a region the
    pick is the candidate whose family is most under-represented against the
    pool's family proportions, then the one farthest from lines already picked.
    """
    if n >= len(pool):
        return set(m["id"] for m in pool)
    rng = random.Random(seed)
    spans = _function_spans(src)

    def region_of(line):
        best = None
        for a, b in spans:
            if a <= line <= b and (best is None or b - a < best[1] - best[0]):
                best = (a, b)
        return best if best else ("module", 0)

    regions = {}
    for m in pool:
        regions.setdefault(region_of(int(m["line"] or 0)), []).append(m)
    order = sorted(regions, key=lambda r: (-len(regions[r]), str(r)))
    quota = dict((r, 0) for r in regions)
    budget = n
    for r in order:
        if budget == 0:
            break
        quota[r] = 1
        budget -= 1
    if budget:
        caps = dict((r, len(regions[r]) - quota[r]) for r in regions)
        total = float(sum(caps.values()) or 1)
        shares = dict((r, budget * caps[r] / total) for r in regions)
        for r in order:
            take = min(caps[r], int(shares[r]), budget)
            quota[r] += take
            budget -= take
        for r in sorted(regions, key=lambda r: -(shares[r] - int(shares[r]))):
            if budget == 0:
                break
            if quota[r] < len(regions[r]):
                quota[r] += 1
                budget -= 1

    fam_pool = {}
    for m in pool:
        fam_pool[m["family"]] = fam_pool.get(m["family"], 0) + 1
    size_pool = float(len(pool))
    picked_fam, chosen, n_picked = {}, set(), 0
    region_lines = dict((r, []) for r in regions)
    remaining = dict(quota)
    live = [r for r in order if quota[r] > 0]
    while live:
        nxt = []
        for r in live:
            cands = [m for m in regions[r] if m["id"] not in chosen]
            if remaining[r] == 0 or not cands:
                continue

            def key(m):
                target = fam_pool[m["family"]] / size_pool
                deficit = target * (n_picked + 1) - picked_fam.get(m["family"], 0)
                spread = (min(abs(int(m["line"]) - l) for l in region_lines[r])
                          if region_lines[r] else 10 ** 6)
                return (deficit, spread, rng.random())

            m = max(cands, key=key)
            chosen.add(m["id"])
            n_picked += 1
            picked_fam[m["family"]] = picked_fam.get(m["family"], 0) + 1
            region_lines[r].append(int(m["line"]))
            remaining[r] -= 1
            if remaining[r] > 0:
                nxt.append(r)
        live = nxt
    return chosen


def gen(module_path, out, seed, search_n, eval_n):
    """Enumerate mutants round-robin across operator families, stop once both folds
    can be filled, then split them into disjoint search and eval folds."""
    from cosmic_ray.mutating import mutate_code
    from cosmic_ray.plugins import get_operator, operator_names

    src = Path(module_path).read_text(encoding="utf-8")
    target = search_n + eval_n
    by_family = {}
    for name in operator_names():
        try:
            by_family.setdefault(family_of(name), []).append((name, get_operator(name)()))
        except Exception:
            continue

    def stream(ops):
        for name, op in ops:
            for occ in range(500):
                try:
                    mutated = mutate_code(src, op, occ)
                except Exception:
                    mutated = None
                if mutated is None:
                    break
                yield name, mutated, occ

    streams = dict((f, stream(ops)) for f, ops in by_family.items())
    live = sorted(streams)
    seen, pool = set(), []
    while live and len(pool) < target:
        nxt = []
        for f in live:
            try:
                name, mutated, occ = next(streams[f])
            except StopIteration:
                continue
            nxt.append(f)
            if mutated == src or mutated in seen:
                continue
            seen.add(mutated)
            line = _first_diff_line(src, mutated)
            pool.append({"id": "%s@L%d#%d" % (name.split("/")[-1], line, occ),
                         "operator": name, "family": family_of(name), "line": line,
                         "src": mutated})
            if len(pool) >= target:
                break
        live = nxt

    pool.sort(key=lambda m: (m["line"], m["family"], m["id"]))
    search_ids = stratified_search_fold(pool, src, min(search_n, len(pool)), seed)
    rest = [m for m in pool if m["id"] not in search_ids]
    if eval_n and len(rest) > eval_n:
        step = len(rest) / float(eval_n)
        keep = set(int(i * step) for i in range(eval_n))
        rest = [m for i, m in enumerate(rest) if i in keep]
    eval_ids = set(m["id"] for m in rest)
    for m in pool:
        m["fold"] = "search" if m["id"] in search_ids else ("eval" if m["id"] in eval_ids else None)
    pool = [m for m in pool if m["fold"]]

    outp = Path(out)
    for fold in ("search", "eval"):
        shutil.rmtree(str(outp / fold), ignore_errors=True)
        (outp / fold).mkdir(parents=True, exist_ok=True)
    for m in pool:
        (outp / m["fold"] / (m["id"] + ".py")).write_text(m["src"], encoding="utf-8")
    (outp / "original.py").write_text(src, encoding="utf-8")
    manifest = [dict((k, v) for k, v in m.items() if k != "src") for m in pool]
    (outp / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    n_search = sum(1 for m in pool if m["fold"] == "search")
    print(json.dumps({"total": len(pool), "n_search": n_search, "n_eval": len(pool) - n_search}))


# ==================================================================== probe
# "path::Class::test[param id, may contain spaces] PASSED   [ 10%]"
_VERDICT = re.compile(r"^(\S+::.+?)\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)(?:\s+\[\s*\d+%\])?\s*$")
# short summary: "ERROR path::test[...] - message"  /  "FAILED path::test - message"
_SUMMARY = re.compile(r"^(FAILED|ERROR) (\S+::.+?)(?: - .*)?$")
_TB_BLOCK = re.compile(r"^_+ (\S+) _+\s*$(.*?)(?=^_+ |^={4,} )", re.MULTILINE | re.DOTALL)


def _write_suite(test_file, suite_file):
    Path(test_file).parent.mkdir(parents=True, exist_ok=True)
    Path(test_file).write_text(Path(suite_file).read_text(encoding="utf-8"), encoding="utf-8")


def _parse_verbose(out):
    tests, seen = [], {}
    for line in out.splitlines():
        m = _VERDICT.match(line)
        if m:
            seen[m.group(1)] = len(tests)
            tests.append({"name": m.group(1), "verdict": m.group(2), "traceback": ""})
    for line in out.splitlines():
        m = _SUMMARY.match(line)
        if not m:
            continue
        name = m.group(2)
        if name in seen:
            if tests[seen[name]]["verdict"] == "PASSED":   # passed the call, errored in teardown
                tests[seen[name]]["verdict"] = m.group(1)
        else:
            seen[name] = len(tests)
            tests.append({"name": name, "verdict": m.group(1), "traceback": line})
    blocks = dict((m.group(1).strip(), m.group(2).strip()[-2000:])
                  for m in _TB_BLOCK.finditer(out + "\n=====\n"))
    for t in tests:
        if t["verdict"] in ("FAILED", "ERROR"):
            bare = t["name"].split("::")[-1]
            t["traceback"] = blocks.get(bare) or blocks.get(bare.split("[")[0], "")
    return tests


def _module_entry(files, module_path):
    base = module_path.split("/")[-1]
    for path, info in files.items():
        p = path.replace("\\", "/")
        if p == module_path or p.endswith("/" + module_path):
            return info
    for path, info in files.items():
        if path.replace("\\", "/").endswith("/" + base):
            return info
    return None


def probe(module_path, test_file, suite_file, timeout):
    _write_suite(test_file, suite_file)
    rc = Path("/tmp/tp_cov.rc")
    rc.write_text("[run]\ndata_file = /tmp/.tp_coverage\n", encoding="utf-8")
    for f in Path("/tmp").glob(".tp_coverage*"):
        try:
            f.unlink()
        except OSError:
            pass
    try:
        p = subprocess.run([sys.executable, "-m", "coverage", "run", "--rcfile", str(rc),
                            "-m", "pytest", "-v", "-rfE", "--tb=short"] + PYTEST_ARGS + [test_file],
                           stdout=PIPE, stderr=PIPE, encoding="utf-8", errors="replace",
                           timeout=timeout)
        out = p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        print(json.dumps({"tests": [], "coverage": 0.0, "uncovered": [],
                          "output": "timeout after %ds" % timeout}))
        return
    tests = _parse_verbose(out)
    coverage, uncovered = 0.0, []
    js = subprocess.run([sys.executable, "-m", "coverage", "json", "--rcfile", str(rc), "-o", "-"],
                        stdout=PIPE, stderr=PIPE, encoding="utf-8", errors="replace", timeout=120)
    try:
        info = _module_entry(json.loads(js.stdout).get("files", {}), module_path)
    except ValueError:
        info = None
    if info:
        coverage = round(info["summary"]["percent_covered"] / 100.0, 4)
        uncovered = info.get("missing_lines", [])
    print(json.dumps({"tests": tests, "coverage": coverage, "uncovered": uncovered,
                      "output": out[-3000:]}))


# =================================================================== mutate
def _passes(test_file, timeout):
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=no", "-x"]
                           + PYTEST_ARGS + [test_file],
                           stdout=PIPE, stderr=PIPE, encoding="utf-8", errors="replace",
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    out = p.stdout + p.stderr
    return p.returncode == 0 and bool(re.search(r"\d+ passed", out))


def mutate(module_path, test_file, suite_file, fold_dir, timeout):
    _write_suite(test_file, suite_file)
    if not _passes(test_file, timeout):
        print(json.dumps({"mutation": 0.0, "survivors": [], "total": 0, "green": False}))
        return
    manifest = {}
    mpath = Path(fold_dir).parent / "manifest.json"
    if mpath.exists():
        for e in json.loads(mpath.read_text(encoding="utf-8")):
            manifest[e["id"]] = e
    mutants = sorted(Path(fold_dir).glob("*.py"))
    original = Path(module_path).read_text(encoding="utf-8")
    survivors, killed = [], 0
    try:
        for mut in mutants:
            Path(module_path).write_text(mut.read_text(encoding="utf-8"), encoding="utf-8")
            if _passes(test_file, timeout):
                e = manifest.get(mut.stem, {})
                survivors.append({"id": mut.stem, "line": e.get("line", 0),
                                  "operator": e.get("operator", ""),
                                  "family": e.get("family", "")})
            else:
                killed += 1
    finally:
        Path(module_path).write_text(original, encoding="utf-8")
    total = len(mutants)
    print(json.dumps({"mutation": round(killed / float(total), 4) if total else 0.0,
                      "survivors": survivors, "total": total, "green": True}))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True
    g = sub.add_parser("gen")
    g.add_argument("--module", required=True)
    g.add_argument("--out", required=True)
    g.add_argument("--seed", type=int, default=0)
    g.add_argument("--search-n", type=int, default=60)
    g.add_argument("--eval-n", type=int, default=800)
    for name in ("probe", "mutate"):
        p = sub.add_parser(name)
        p.add_argument("--module", required=True)
        p.add_argument("--test-file", required=True)
        p.add_argument("--suite", required=True)
        p.add_argument("--timeout", type=int, default=300 if name == "probe" else 120)
        if name == "mutate":
            p.add_argument("--fold", required=True)
    a = ap.parse_args()
    if a.cmd == "gen":
        gen(a.module, a.out, a.seed, a.search_n, a.eval_n)
    elif a.cmd == "probe":
        probe(a.module, a.test_file, a.suite, a.timeout)
    else:
        mutate(a.module, a.test_file, a.suite, a.fold, a.timeout)


if __name__ == "__main__":
    main()
