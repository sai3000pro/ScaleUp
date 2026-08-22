"""Mechanically enforce the project's no-`continue` rule (see CLAUDE.md).

Ruff has no rule for this, and a stated constraint that nothing checks is a
constraint that quietly decays. The TypeScript half is covered by
`no-continue: "error"` in frontend/eslint.config.mjs.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"


# @spec OPS-CI-004
def test_no_continue_statements_in_app() -> None:
    offenders: list[str] = []

    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Continue):
                offenders.append(f"{path.relative_to(APP_ROOT.parent)}:{node.lineno}")

    assert not offenders, (
        "`continue` is banned in this project; use explicit if/elif/else branching so "
        "every path through the loop is visible at the point of decision.\n  " + "\n  ".join(offenders)
    )
