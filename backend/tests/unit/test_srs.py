"""SM-2 scheduling, mastery EMA, and time decay."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.exp import rescue_multiplier
from app.domain.srs import (
    EASE_FLOOR,
    MAX_INTERVAL_DAYS,
    ReviewState,
    proficiency,
    quality_from_score,
    schedule,
    update_mastery,
)

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
NO_JITTER = (lambda: 1.0)  # noqa: E731  -- deterministic scheduling in tests


def test_quality_mapping_puts_the_pass_boundary_at_half() -> None:
    assert quality_from_score(0.0) == 0
    assert quality_from_score(0.49) == 2  # fail
    assert quality_from_score(0.5) == 3  # pass
    assert quality_from_score(1.0) == 5


def test_first_two_passes_use_the_fixed_ladder() -> None:
    first = schedule(ReviewState(), 1.0, NOW, NO_JITTER)
    assert first.reps == 1
    assert first.interval_days == 1.0
    assert first.due_at == NOW + timedelta(days=1)

    second = schedule(first, 1.0, NOW, NO_JITTER)
    assert second.reps == 2
    assert second.interval_days == 6.0


def test_third_pass_multiplies_by_ease() -> None:
    state = ReviewState(ease=2.5, interval_days=6.0, reps=2, mastery=0.9)
    third = schedule(state, 1.0, NOW, NO_JITTER)
    assert third.reps == 3
    assert third.interval_days == 6.0 * third.ease


def test_lapse_resets_reps_and_drops_ease() -> None:
    state = ReviewState(ease=2.5, interval_days=30.0, reps=5, mastery=0.9)
    lapsed = schedule(state, 0.2, NOW, NO_JITTER)

    assert lapsed.reps == 0
    assert lapsed.lapses == 1
    assert lapsed.interval_days == 0.5
    assert lapsed.ease == 2.3


def test_ease_never_falls_below_the_floor() -> None:
    state = ReviewState(ease=EASE_FLOOR)
    for _ in range(10):
        state = schedule(state, 0.0, NOW, NO_JITTER)
    assert state.ease == EASE_FLOOR


def test_interval_is_capped() -> None:
    state = ReviewState(ease=2.8, interval_days=MAX_INTERVAL_DAYS, reps=9, mastery=1.0)
    advanced = schedule(state, 1.0, NOW, NO_JITTER)
    assert advanced.interval_days == MAX_INTERVAL_DAYS


def test_jitter_spreads_due_dates_within_ten_percent() -> None:
    state = ReviewState(ease=2.5, interval_days=10.0, reps=3, mastery=0.9)
    low = schedule(state, 1.0, NOW, lambda: 0.9)
    high = schedule(state, 1.0, NOW, lambda: 1.1)
    assert low.due_at < high.due_at
    assert (high.due_at - low.due_at).total_seconds() > 0


def test_mastery_is_an_ema_and_does_not_decay() -> None:
    assert update_mastery(0.0, 1.0) == 0.4
    assert round(update_mastery(0.4, 1.0), 4) == 0.64
    assert update_mastery(1.0, 0.0) == 0.6


# ── decay ─────────────────────────────────────────────────────────────────


def test_proficiency_halves_exactly_at_one_interval() -> None:
    """The invariant the whole visual language rests on."""
    state = ReviewState(interval_days=10.0, mastery=0.8, last_reviewed_at=NOW, reps=3)
    at_due = NOW + timedelta(days=10)
    assert abs(proficiency(state, at_due) - 0.4) < 1e-9


def test_proficiency_is_full_immediately_after_review() -> None:
    state = ReviewState(interval_days=10.0, mastery=0.8, last_reviewed_at=NOW, reps=3)
    assert abs(proficiency(state, NOW) - 0.8) < 1e-9


def test_proficiency_decreases_monotonically() -> None:
    state = ReviewState(interval_days=5.0, mastery=1.0, last_reviewed_at=NOW, reps=3)
    samples = [proficiency(state, NOW + timedelta(days=d)) for d in range(0, 40, 2)]
    assert all(later <= earlier for earlier, later in zip(samples, samples[1:]))


def test_never_reviewed_node_has_zero_proficiency() -> None:
    assert proficiency(ReviewState(), NOW) == 0.0


# ── rescue bonus ──────────────────────────────────────────────────────────


def test_rescue_multiplier_bounds() -> None:
    assert rescue_multiplier(0.0, 10.0) == 1.0
    assert rescue_multiplier(5.0, 10.0) == 1.25
    assert rescue_multiplier(10.0, 10.0) == 1.5
    assert rescue_multiplier(900.0, 10.0) == 1.5  # clamps
