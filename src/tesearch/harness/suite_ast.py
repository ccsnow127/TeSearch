"""Static operations on suite source: counting tests and isolating the green subset."""
from __future__ import annotations

import ast

_FN = (ast.FunctionDef, ast.AsyncFunctionDef)


def _test_defs(body):
    for node in body:
        if isinstance(node, _FN) and node.name.startswith("test"):
            yield node
        elif isinstance(node, ast.ClassDef):
            yield from _test_defs(node.body)


def count_tests(src: str) -> int:
    """Written size s(T): functions whose name starts with ``test``, at module level
    or inside test classes (the same count the size ask names)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return 0
    return sum(1 for _ in _test_defs(tree.body))


def test_names(src: str) -> list[str]:
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    return [n.name for n in _test_defs(tree.body)]


def canon(test_id: str) -> str:
    """``path/to/test_x.py::TestC::test_y[param]`` -> ``test_y``."""
    return test_id.split("::")[-1].split("[")[0]


def drop_failing_tests(src: str, failing: set) -> str:
    """Remove the named test functions and methods; the rest is the green subset.

    Any parse or unparse failure returns the source unchanged, so the caller can
    tell a no-op prune from a real one.
    """
    if not failing:
        return src
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src

    def keep(node) -> bool:
        return not (isinstance(node, _FN) and node.name in failing)

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            node.body = [m for m in node.body if keep(m)] or [ast.Pass()]
    tree.body = [n for n in tree.body if keep(n)]
    try:
        return ast.unparse(tree) + "\n"
    except Exception:  # noqa: BLE001
        return src
