"""A repository path a document points at exists."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DOCUMENTS = sorted(ROOT.glob("docs/**/*.md")) + [ROOT / "CLAUDE.md", ROOT / "README.md"]
# Backticked, extension-bearing paths rooted at a top-level folder of this repository.
PATH_REFERENCE = re.compile(r"`((?:backend|frontend|scripts|docs|design|\.github)/[A-Za-z0-9_./\-]+\.[a-z]{1,5})`")


def _references() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for document in DOCUMENTS:
        text = document.read_text(encoding="utf-8")
        for match in PATH_REFERENCE.finditer(text):
            found.append((str(document.relative_to(ROOT)), match.group(1)))
    return found


# @spec OPS-CONTRACT-005
def test_every_documented_repository_path_exists() -> None:
    references = _references()
    assert len(references) > 50, "the path scanner stopped matching anything"
    missing = sorted({f"{document} -> {ref}" for document, ref in references if not (ROOT / ref).exists()})
    assert not missing, "documentation points at files that do not exist:\n  " + "\n  ".join(missing)


@pytest.mark.parametrize("document", [d for d in DOCUMENTS if d.name.endswith("-design.md")])
def test_design_documents_are_in_the_scan(document: Path) -> None:
    assert document.exists()
