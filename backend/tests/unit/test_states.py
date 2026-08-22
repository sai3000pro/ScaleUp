"""Node state derivation truth table."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.srs import ReviewState
from app.domain.states import NodeState, derive_state, gating_masteries, overdue_days

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)


def test_untouched_node_with_no_prerequisites_is_available() -> None:
    assert derive_state(ReviewState(), level=0, prerequisite_masteries=[], now=NOW) == NodeState.AVAILABLE


def test_node_with_an_unmet_prerequisite_is_locked() -> None:
    assert derive_state(ReviewState(), 0, [0.2], NOW) == NodeState.LOCKED


def test_node_unlocks_at_half_prerequisite_mastery() -> None:
    assert derive_state(ReviewState(), 0, [0.5], NOW) == NodeState.AVAILABLE


def test_one_weak_prerequisite_among_many_still_locks() -> None:
    assert derive_state(ReviewState(), 0, [0.9, 0.9, 0.1], NOW) == NodeState.LOCKED


def test_drilled_but_not_due_is_learning() -> None:
    state = ReviewState(reps=2, mastery=0.6, last_reviewed_at=NOW, due_at=NOW + timedelta(days=3))
    assert derive_state(state, level=2, prerequisite_masteries=[], now=NOW) == NodeState.LEARNING


def test_fully_levelled_node_is_mastered() -> None:
    state = ReviewState(reps=6, mastery=0.9, last_reviewed_at=NOW, due_at=NOW + timedelta(days=30))
    assert derive_state(state, level=5, prerequisite_masteries=[], now=NOW) == NodeState.MASTERED


def test_overdue_mastered_node_reads_as_decaying() -> None:
    """The case that carries the entire retention mechanic.

    If mastery were permanent, the Daily Quest board would have nothing to say.
    """
    state = ReviewState(reps=6, mastery=0.95, last_reviewed_at=NOW - timedelta(days=60), due_at=NOW - timedelta(days=30))
    assert derive_state(state, level=5, prerequisite_masteries=[], now=NOW) == NodeState.DECAYING


def test_locked_beats_decaying() -> None:
    """A node whose prerequisite regressed is locked, not merely overdue."""
    state = ReviewState(reps=3, mastery=0.7, last_reviewed_at=NOW, due_at=NOW - timedelta(days=5))
    assert derive_state(state, level=3, prerequisite_masteries=[0.1], now=NOW) == NodeState.LOCKED


def test_overdue_days_is_zero_when_not_due() -> None:
    assert overdue_days(ReviewState(due_at=NOW + timedelta(days=1)), NOW) == 0.0
    assert overdue_days(ReviewState(), NOW) == 0.0


def test_overdue_days_measures_the_gap() -> None:
    state = ReviewState(due_at=NOW - timedelta(days=3))
    assert abs(overdue_days(state, NOW) - 3.0) < 1e-9


# ── structural nodes must not quarantine their subtree ────────────────────
#
# A node with assessable=False can never be drilled, so no attempt is ever
# recorded against it and its mastery stays 0.0 for ever. Feeding that raw 0.0
# in as a prerequisite mastery locked every descendant permanently -- and the
# quest board excludes structural nodes, so nothing could ever unlock it. One
# container chapter quarantined the whole book with no in-app way out.

CHAPTER = "chapter"
SECTION = "section"
INTRO = "intro"


def test_a_structural_prerequisite_is_seen_through_rather_than_blocking() -> None:
    prereqs = {SECTION: [CHAPTER]}
    mastery = {CHAPTER: 0.0}  # never drillable, so never above zero
    assessable = {CHAPTER: False, SECTION: True}

    gating = gating_masteries(SECTION, prereqs, mastery, assessable)

    assert gating == []
    assert derive_state(ReviewState(), 0, gating, NOW) == NodeState.AVAILABLE


def test_a_structural_node_still_passes_through_its_own_prerequisites() -> None:
    """Transparent, not free: a container behind real work stays gated."""
    prereqs = {SECTION: [CHAPTER], CHAPTER: [INTRO]}
    mastery = {CHAPTER: 0.0, INTRO: 0.1}
    assessable = {CHAPTER: False, SECTION: True, INTRO: True}

    gating = gating_masteries(SECTION, prereqs, mastery, assessable)

    assert gating == [0.1]
    assert derive_state(ReviewState(), 0, gating, NOW) == NodeState.LOCKED


def test_clearing_the_real_prerequisite_unlocks_through_the_container() -> None:
    prereqs = {SECTION: [CHAPTER], CHAPTER: [INTRO]}
    assessable = {CHAPTER: False, SECTION: True, INTRO: True}

    gating = gating_masteries(SECTION, prereqs, {CHAPTER: 0.0, INTRO: 0.9}, assessable)

    assert derive_state(ReviewState(), 0, gating, NOW) == NodeState.AVAILABLE


def test_an_ordinary_prerequisite_is_unaffected() -> None:
    gating = gating_masteries("b", {"b": ["a"]}, {"a": 0.2}, {"a": True, "b": True})
    assert gating == [0.2]


def test_a_chain_of_containers_collapses() -> None:
    prereqs = {"leaf": ["mid"], "mid": ["top"], "top": []}
    assessable = {"leaf": True, "mid": False, "top": False}
    assert gating_masteries("leaf", prereqs, {}, assessable) == []


def test_a_cyclic_edge_set_terminates_rather_than_hanging() -> None:
    """The graph is a DAG by construction, but this reads database rows."""
    prereqs = {"a": ["b"], "b": ["a"]}
    assessable = {"a": False, "b": False}
    assert gating_masteries("a", prereqs, {}, assessable) == []
