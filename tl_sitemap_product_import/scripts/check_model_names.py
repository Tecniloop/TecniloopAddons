#!/usr/bin/env python3
"""Static diagnostic for invalid Odoo model _name definitions.

Run against one or more addon roots:
    python3 check_model_names.py /path/to/extra-addons /path/to/custom-addons
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


def iter_model_classes(path: Path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    except SyntaxError as exc:
        yield (path, exc.lineno or 0, "<syntax error>", f"syntax error: {exc}")
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        name_values = []
        name_methods = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "_name":
                name_methods.append(item.lineno)
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id == "_name":
                        name_values.append((item.lineno, item.value))
            elif isinstance(item, ast.AnnAssign):
                if isinstance(item.target, ast.Name) and item.target.id == "_name":
                    name_values.append((item.lineno, item.value))
        for lineno in name_methods:
            yield (path, lineno, node.name, "defines a method named _name")
        for lineno, value in name_values:
            if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                yield (path, lineno, node.name, f"_name is not a string literal: {ast.dump(value)}")


def main(argv: list[str]) -> int:
    roots = [Path(arg).resolve() for arg in argv[1:]] or [Path.cwd()]
    problems = []
    for root in roots:
        if not root.exists():
            print(f"Missing path: {root}", file=sys.stderr)
            continue
        for path in root.rglob("*.py"):
            problems.extend(iter_model_classes(path))
    if not problems:
        print("OK: no invalid static _name declarations found.")
        return 0
    for path, lineno, cls, reason in problems:
        print(f"{path}:{lineno}: class {cls}: {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
