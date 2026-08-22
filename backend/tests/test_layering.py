"""Mechanically enforce the one-directional layering rule (see CLAUDE.md).

    routers  ->  services  ->  {repositories | models | llm | vector}  ->  domain
    tasks    ->  services
    domain   ->  nothing

The rule is stated in CLAUDE.md and in the high-level design, and until this file
nothing checked it. That matters most for `app/domain/`: its independence is the
reason the DAG, the scheduler, the state machine and the coaching policy test in
milliseconds with no Docker running. One convenience import of a SQLAlchemy model
into a domain module ends that property silently -- the tests still pass, they
just start needing a database.

Two directions are checked:

  * `app/domain/` imports nothing else from `app`.  (PROG-DAG-001)
  * `app/api/routers/` does not touch SQLAlchemy directly, so query construction
    stays in the service and repository layers.

Both are import-graph facts, so they are read off the AST rather than trusted.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
DOMAIN = APP_ROOT / "domain"
ROUTERS = APP_ROOT / "api" / "routers"


def _imported_modules(path: Path) -> list[tuple[str, int]]:
    """Every module name this file imports, with the line it is imported on.

    Relative imports are resolved to their `app.` prefix so a `from ..models
    import X` inside a package is not silently invisible to the check.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, int]] = []
    package_parts = path.relative_to(APP_ROOT.parent).parent.parts

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                found.append((node.module or "", node.lineno))
            else:
                base = package_parts[: len(package_parts) - (node.level - 1)]
                found.append((".".join([*base, node.module or ""]).rstrip("."), node.lineno))
        else:
            pass  # no `continue`: every branch is visible at the point of decision
    return found


# @spec PROG-DAG-001
def test_domain_imports_nothing_from_the_rest_of_the_application() -> None:
    offenders: list[str] = []

    for path in sorted(DOMAIN.rglob("*.py")):
        for module, lineno in _imported_modules(path):
            if module.startswith("app.") and not module.startswith("app.domain"):
                offenders.append(f"{path.relative_to(APP_ROOT.parent)}:{lineno} imports {module}")

    assert not offenders, (
        "app/domain/ must import nothing from the rest of the application. Its independence is "
        "what lets the graph, scheduling, state and coaching-policy rules be tested in "
        "milliseconds with nothing running.\n  " + "\n  ".join(offenders)
    )


def test_routers_do_not_construct_queries() -> None:
    offenders: list[str] = []

    for path in sorted(ROUTERS.rglob("*.py")):
        for module, lineno in _imported_modules(path):
            root = module.split(".")[0]
            if root == "sqlalchemy":
                offenders.append(f"{path.relative_to(APP_ROOT.parent)}:{lineno} imports {module}")

    assert not offenders, (
        "Routers must not touch SQLAlchemy. Query construction belongs in the service and "
        "repository layers, so a route stays a translation between HTTP and a service call.\n  "
        + "\n  ".join(offenders)
    )
