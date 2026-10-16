"""The live gate stays out of CI by marker, not by directory layout."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CI = ROOT / ".github" / "workflows" / "ci.yml"
LIVE_DIR = ROOT / "backend" / "tests" / "live"


# @spec LLM-LIVE-003, LLM-FAKE-006, LLM-FAKE-007
def test_ci_deselects_live_tests_by_marker() -> None:
    workflow = CI.read_text(encoding="utf-8")
    assert '-m "not live"' in workflow
    assert "tests/live" not in workflow, "selecting by path means a live test outside the directory still runs"


# @spec LLM-LIVE-001
def test_live_directory_stamps_the_marker_on_everything() -> None:
    conftest = (LIVE_DIR / "conftest.py").read_text(encoding="utf-8")
    assert "pytest_collection_modifyitems" in conftest
    assert "pytest.mark.live" in conftest
