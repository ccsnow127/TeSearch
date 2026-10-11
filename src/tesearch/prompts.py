"""Building the prompts.

Three system prompts -- one for the opening generations and two for breeding,
depending on whether the suite has to shrink or grow -- kept verbatim under
``prompts/`` at the repository root, and one user prompt assembled here: the
module source, then the size to write, then the example suites with the strongest
last. Nothing is ever truncated: a clipped module hides the very lines the call
is asked to cover, and a clipped example cuts a test in half.

What the best example still misses is marked inline, at the end of the line it
refers to, because a mark sitting next to the code is far easier to act on than a
list of line numbers somewhere else:
    # <-- NOT COVERED YET          module line none of the passing tests execute
    # <-- SURVIVING MUTANT: <op>   module line where that mutation survives
    # <-- FAILING: <exception>     def header of a test that fails
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from .archive import Suite
from .parents import COMPRESS

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def _load(name: str) -> str:
    """One prompt file, verbatim; the files under ``prompts/`` are the source of truth."""
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").rstrip("\n")


SEED_SYS = _load("seed_system.txt")
BREED_COMPRESS_SYS = _load("breed_compress_system.txt")
BREED_EXPAND_SYS = _load("breed_extend_system.txt")
_MODULE_HEADER_MARKED = _load("module_header_marked.txt")
_SIZE_ASK = _load("size_ask.txt")


def breed_system(mode: str) -> str:
    return BREED_COMPRESS_SYS if mode == COMPRESS else BREED_EXPAND_SYS


def size_ask(n: int) -> str:
    return _SIZE_ASK.format(n=n)


# ---------------------------------------------------------------- inline marks
def mark_module(module_src: str, uncovered, survivors) -> str:
    marks: dict[int, list[str]] = {}
    for n in uncovered or ():
        marks.setdefault(int(n), []).append("NOT COVERED YET")
    for s in survivors or ():
        if s.get("line"):
            op = (s.get("operator") or "mutation").split("/")[-1]
            marks.setdefault(int(s["line"]), []).append(f"SURVIVING MUTANT: {op}")
    return "\n".join(f"{ln}  # <-- {'; '.join(marks[i])}" if i in marks else ln
                     for i, ln in enumerate(module_src.splitlines(), start=1))


def mark_failing(suite_src: str, failing: dict) -> str:
    """Mark each failing test at the end of its (possibly multi-line) def header."""
    if not failing:
        return suite_src
    lines = suite_src.splitlines()
    marks: dict[int, str] = {}
    try:
        tree = ast.parse(suite_src)
    except SyntaxError:
        for i, ln in enumerate(lines, start=1):
            m = re.match(r"\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(", ln)
            if m and m.group(1) in failing:
                marks[i] = failing[m.group(1)]
    else:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in failing:
                end = node.body[0].lineno - 1 if node.body else node.lineno
                end = max(end, node.lineno)
                while end > node.lineno and not lines[end - 1].strip():
                    end -= 1
                marks[end] = failing[node.name]
    return "\n".join(f"{ln}  # <-- FAILING: {marks[i]}" if i in marks else ln
                     for i, ln in enumerate(lines, start=1))


# --------------------------------------------------------------------- prompts
def seed_user(dotted: str, module_src: str, n: int | None = None) -> str:
    """Ask for a suite from scratch. With ``n``, a size is requested too, which is
    what a call falls back to while the archive is still empty."""
    parts = [f"[TARGET MODULE] {dotted}", f"[MODULE SOURCE]\n{module_src}"]
    if n is not None:
        parts.append(size_ask(n))
    parts.append("Write the full test suite now. Complete file, no prose, no fences.")
    return "\n\n".join(parts)


def _suite_block(i: int, s: Suite, note: str | None) -> str:
    header = (f"[test_suite_v{i} - size={s.size} green={s.green_size} "
              f"pass_rate={s.pass_rate:.3f} coverage={s.cov:.3f} mutation={s.mut:.3f} "
              f"loc={s.loc}]")
    n_fail = len(s.failing)
    if n_fail > 0:
        header += (f"\n({n_fail} of its {s.size} tests FAIL - each marked inline below; "
                   f"the coverage/mutation above come from the {s.green_size} that pass)")
    if note:
        header += f"\n({note})"
    return f"{header}\n{mark_failing(s.src, s.failing)}"


def breed_user(dotted: str, module_src: str, n: int, parents: list[Suite],
               notes: list[str | None]) -> str:
    """Module (marked with the strongest parent's residue) → size ask → parents."""
    best = parents[-1]
    if best.uncovered or best.survivors:
        module = f"{_MODULE_HEADER_MARKED}\n{mark_module(module_src, best.uncovered, best.survivors)}"
    else:
        module = f"[MODULE SOURCE]\n{module_src}"
    parts = [f"[TARGET MODULE] {dotted}", module, size_ask(n)]
    parts += [_suite_block(i, s, note) for i, (s, note) in enumerate(zip(parents, notes))]
    parts.append(f"Write test_suite_v{len(parents)} now: the next, improved complete suite. "
                 f"Complete file, no prose, no fences.")
    return "\n\n".join(parts)


def extract_code(text: str) -> str:
    """The largest fenced block if the model fenced its output, else the text."""
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text or "", re.DOTALL)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    return (text or "").strip() + "\n"
