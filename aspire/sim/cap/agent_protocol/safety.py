"""Static admission checks for dynamic-v2 Python actions."""

from __future__ import annotations

import ast

FORBIDDEN_NAMES = {"env", "APIS", "audit", "simulator", "private_artifact_root"}
FORBIDDEN_CALLS = {
    "open", "eval", "exec", "compile", "__import__", "breakpoint", "input",
    "globals", "locals", "vars", "dir", "getattr", "setattr", "delattr",
}
FORBIDDEN_ATTRIBUTES = {"sim", "body_xpos", "set_joint_qpos", "parsed_problem", "_eval_predicate", "obj_body_id", "handle"}
ALLOWED_IMPORT_ROOTS = {"math", "numpy", "scipy"}


def validate_public_python(code: str) -> None:
    tree = ast.parse(code)
    bad_names = sorted({node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} & FORBIDDEN_NAMES)
    bad_attrs = sorted({node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)} & FORBIDDEN_ATTRIBUTES)
    bad_attrs.extend(sorted({
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr.startswith("_")
    }))
    bad_calls = sorted({node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)} & FORBIDDEN_CALLS)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    bad_imports = sorted(name for name in imports if name.split(".", 1)[0] not in ALLOWED_IMPORT_ROOTS)
    violations = bad_names + bad_attrs + bad_calls + bad_imports
    if violations:
        raise ValueError(f"generated code references forbidden capabilities: {violations}")
