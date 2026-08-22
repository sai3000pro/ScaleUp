"""The live matcher is advisory, and its limits are measured rather than assumed."""

from __future__ import annotations

import pytest

from app.evaluation.musicxml import parse_musicxml
from app.evaluation.online import (
    ObservedEvent,
    advance,
    expected_events,
    flush_stale,
    new_matcher,
    rolling_window,
)
from app.evaluation.piano import PerformedNote, score_performance
from app.evaluation.reference_scores import PIANO_STEPWISE_SCORE_XML

TOLERANCE = 0.25


def _events():
    score = parse_musicxml(PIANO_STEPWISE_SCORE_XML)
    return score, expected_events(score, "piano")


def _play(observations, expected):
    state = new_matcher()
    for index, observation in enumerate(observations):
        state, _ = advance(state, expected, observation, index, timing_tolerance=TOLERANCE)
    return state


def _perfect(expected):
    return [
        ObservedEvent(pitch_midi=event.pitch_midi, onset_seconds=event.onset_seconds, confidence=1.0)
        for event in expected
    ]


def test_a_perfect_take_matches_everything() -> None:
    _, expected = _events()
    state = _play(_perfect(expected), expected)
    assert state.cursor == len(expected)
    kinds = [outcome.kind for outcome in state.committed]
    assert kinds == ["matched"] * len(expected)


def test_a_skipped_note_is_reported_once_at_the_right_index() -> None:
    _, expected = _events()
    observations = [obs for index, obs in enumerate(_perfect(expected)) if index != 1]
    state = _play(observations, expected)
    missed = [outcome for outcome in state.committed if outcome.kind == "missed"]
    assert len(missed) == 1
    assert missed[0].expected_index == 1


def test_an_inserted_note_is_extra_and_does_not_move_the_cursor() -> None:
    _, expected = _events()
    observations = list(_perfect(expected))
    observations.insert(2, ObservedEvent(pitch_midi=40, onset_seconds=observations[2].onset_seconds, confidence=1.0))
    state = _play(observations, expected)
    extras = [outcome for outcome in state.committed if outcome.kind == "extra"]
    assert len(extras) == 1
    assert state.cursor == len(expected)


def test_silence_registers_as_missed_notes() -> None:
    """Without a stale flush, a learner who stops shows no misses at all."""
    _, expected = _events()
    state = _play(_perfect(expected)[:1], expected)
    state, emitted = flush_stale(state, expected, now_seconds=99.0, timing_tolerance=TOLERANCE)
    assert len(emitted) == len(expected) - 1
    assert all(outcome.kind == "missed" for outcome in emitted)


def test_committed_outcomes_are_never_revised() -> None:
    """A live cue that changes its mind is worse than no cue."""
    _, expected = _events()
    observations = _perfect(expected)
    state = new_matcher()
    snapshots = []
    for index, observation in enumerate(observations):
        state, _ = advance(state, expected, observation, index, timing_tolerance=TOLERANCE)
        snapshots.append(state.committed)
    for earlier, later in zip(snapshots, snapshots[1:]):
        assert later[: len(earlier)] == earlier


def test_replaying_a_buffer_reproduces_the_state_exactly() -> None:
    """The property the streaming resume path depends on."""
    _, expected = _events()
    observations = _perfect(expected)
    assert _play(observations, expected) == _play(observations, expected)


def test_it_agrees_with_the_batch_scorer_on_a_clean_take() -> None:
    """Agreement is asserted, not assumed -- and only where it is fair to expect.

    The batch scorer may revise an early alignment once it has seen the whole
    take; the online matcher cannot. On a clean take they must agree exactly,
    which is the case that matters for a live cue being trustworthy.
    """
    score, expected = _events()
    observations = _perfect(expected)
    state = _play(observations, expected)
    batch = score_performance(
        score,
        [
            PerformedNote(pitch_midi=o.pitch_midi, onset_seconds=o.onset_seconds, duration_seconds=0.5, confidence=1.0)
            for o in observations
        ],
    )
    matched = len([outcome for outcome in state.committed if outcome.kind == "matched"])
    assert matched == batch.matched_note_count
    assert len([o for o in state.committed if o.kind == "missed"]) == batch.missed_note_count
    assert len([o for o in state.committed if o.kind == "extra"]) == batch.extra_note_count


class TestWindow:
    def test_rushing_shows_as_a_negative_bias(self) -> None:
        _, expected = _events()
        early = [
            ObservedEvent(pitch_midi=event.pitch_midi, onset_seconds=max(0.0, event.onset_seconds - 0.15),
                          confidence=1.0)
            for event in expected
        ]
        state = _play(early, expected)
        window = rolling_window(state, now_seconds=5.0, window_seconds=5.0, expected_count=len(expected))
        assert window.signed_timing_bias_seconds is not None
        assert window.signed_timing_bias_seconds < 0

    def test_progress_tracks_the_cursor(self) -> None:
        _, expected = _events()
        state = _play(_perfect(expected)[:2], expected)
        window = rolling_window(state, now_seconds=2.0, window_seconds=5.0, expected_count=len(expected))
        assert window.progress_ratio == pytest.approx(2 / len(expected))

    def test_an_empty_take_reports_nothing_rather_than_zero(self) -> None:
        _, expected = _events()
        window = rolling_window(new_matcher(), now_seconds=1.0, window_seconds=5.0, expected_count=len(expected))
        assert window.mean_pitch_error_semitones is None
        assert window.signed_pitch_bias_semitones is None
        assert window.signed_timing_bias_seconds is None
        assert window.note_count == 0

    # @spec COACH-CUE-006
    def test_flat_and_sharp_show_as_signed_pitch_bias(self) -> None:
        _, expected = _events()
        flat_notes = [
            ObservedEvent(
                pitch_midi=event.pitch_midi - 0.5 if event.pitch_midi is not None else None,
                onset_seconds=event.onset_seconds,
                confidence=1.0,
            )
            for event in expected
        ]
        state = _play(flat_notes, expected)
        window = rolling_window(state, now_seconds=5.0, window_seconds=5.0, expected_count=len(expected))
        assert window.signed_pitch_bias_semitones is not None
        assert window.signed_pitch_bias_semitones < 0


def test_chords_collapse_to_one_event_per_onset() -> None:
    """A strum is one thing to hit, not six things to miss."""
    from app.evaluation.reference_scores import GUITAR_GCD_STRUM_XML

    score = parse_musicxml(GUITAR_GCD_STRUM_XML)
    events = expected_events(score, "guitar")
    assert len(events) < len(score.notes)
    assert len({event.onset_seconds for event in events}) == len(events)
