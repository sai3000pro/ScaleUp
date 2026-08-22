"""The coach's restraint is the feature.

Anyone can make an LLM comment on a performance. The difficulty is a tutor who
stays quiet while you are playing, says one useful thing at the rest, and does
not repeat itself. Every test here is about a path that must NOT lead to speech.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.domain.coach_policy import (
    BETTER_WHEN_LOWER,
    CueKind,
    LiveMetricWindow,
    TurnBudget,
    TurnHistory,
    classify,
    decide_turn,
    interpret,
)


def _window(**overrides) -> LiveMetricWindow:
    base = {
        "window_seconds": 6.0,
        "note_count": 10,
        "matched_count": 10,
        "missed_count": 0,
        "extra_count": 0,
        "mean_pitch_error_semitones": 0.05,
        "mean_abs_timing_error_seconds": 0.02,
        "signed_timing_bias_seconds": 0.0,
        "mean_confidence": 0.9,
        "progress_ratio": 0.4,
        "seconds_since_cursor_moved": 0.2,
    }
    base.update(overrides)
    return LiveMetricWindow(**base)


def _turn(window: LiveMetricWindow, **overrides):
    kwargs = {
        "window": window,
        "history": TurnHistory(),
        "budget": TurnBudget(),
        "now_seconds": 30.0,
        "silence_seconds": 1.0,
        "expected_count": 16,
    }
    kwargs.update(overrides)
    return decide_turn(**kwargs)


class TestSilence:
    def test_it_does_not_speak_while_the_learner_is_playing(self) -> None:
        turn = _turn(_window(signed_timing_bias_seconds=-0.2), silence_seconds=0.05)
        assert turn.should_speak is False
        assert turn.suppressed_by == "mid_phrase"

    def test_it_speaks_at_a_rest(self) -> None:
        turn = _turn(_window(signed_timing_bias_seconds=-0.2), silence_seconds=1.2)
        assert turn.should_speak is True
        assert turn.cue is CueKind.RUSHING

    def test_nothing_to_say_is_a_valid_answer(self) -> None:
        # A clean, unremarkable stretch of playing. A coach that fills this
        # silence is worse than one that does not.
        turn = _turn(_window(matched_count=3))
        assert turn.should_speak is False
        assert turn.suppressed_by == "nothing_to_say"

    def test_losing_your_place_may_interrupt_once(self) -> None:
        window = _window(seconds_since_cursor_moved=6.0, note_count=4, matched_count=0)
        first = _turn(window, silence_seconds=0.0)
        assert first.should_speak is True
        assert first.severity == "intervene"

        again = _turn(window, silence_seconds=0.0, history=TurnHistory(interventions=1))
        assert again.should_speak is False
        assert again.suppressed_by == "mid_phrase"


class TestBudgets:
    def test_it_stops_after_the_per_take_cap(self) -> None:
        turn = _turn(
            _window(missed_count=5),
            history=TurnHistory(utterance_count=4),
        )
        assert turn.should_speak is False
        assert turn.suppressed_by == "cap"

    def test_it_waits_between_utterances(self) -> None:
        turn = _turn(
            _window(missed_count=5),
            history=TurnHistory(utterance_count=1, last_utterance_at_seconds=27.0),
        )
        assert turn.suppressed_by == "cooldown"

    def test_it_does_not_repeat_the_same_cue(self) -> None:
        turn = _turn(
            _window(missed_count=5),
            history=TurnHistory(
                utterance_count=1,
                last_utterance_at_seconds=10.0,
                last_cue_at_seconds={str(CueKind.MISSED_RUN): 20.0},
            ),
        )
        assert turn.suppressed_by == "duplicate"

    def test_an_exhausted_course_budget_silences_rather_than_raises(self) -> None:
        # The budget is an input to the decision, not an exception thrown from
        # the gateway mid-phrase: running out must degrade to the deterministic
        # sentence, never surface as an error beside a good take.
        turn = _turn(
            _window(missed_count=5),
            budget=TurnBudget(
                remaining_course_budget_usd=Decimal("0.0001"),
                estimated_utterance_cost_usd=Decimal("0.01"),
            ),
        )
        assert turn.should_speak is False
        assert turn.suppressed_by == "budget"


class TestClassification:
    def test_rushing_and_dragging_are_distinguished(self) -> None:
        rushing = classify(_window(signed_timing_bias_seconds=-0.2), expected_count=16)
        dragging = classify(_window(signed_timing_bias_seconds=0.2), expected_count=16)
        assert rushing is not None and rushing[0] is CueKind.RUSHING
        assert dragging is not None and dragging[0] is CueKind.DRAGGING

    def test_missed_notes_outrank_timing(self) -> None:
        result = classify(_window(missed_count=4, signed_timing_bias_seconds=-0.3), expected_count=16)
        assert result is not None and result[0] is CueKind.MISSED_RUN

    def test_a_clean_streak_is_worth_saying_once(self) -> None:
        result = classify(_window(matched_count=10), expected_count=16)
        assert result is not None and result[0] is CueKind.GOOD_STREAK

    # @spec COACH-CUE-006
    def test_flat_and_sharp_pitch_are_distinguished(self) -> None:
        sharp = classify(_window(signed_pitch_bias_semitones=0.6), expected_count=16)
        flat = classify(_window(signed_pitch_bias_semitones=-0.6), expected_count=16)
        assert sharp is not None and sharp[0] is CueKind.SHARP_PITCH
        assert flat is not None and flat[0] is CueKind.FLAT_PITCH

    def test_a_finished_take_always_speaks(self) -> None:
        turn = _turn(_window(), take_finished=True)
        assert turn.should_speak is True
        assert turn.cue is CueKind.TAKE_COMPLETE


class TestInterpretation:
    def test_numbers_become_words(self) -> None:
        phrases = interpret(_window(signed_timing_bias_seconds=-0.2, mean_pitch_error_semitones=0.6))
        assert "running ahead of the beat" in phrases
        assert "landing on the wrong notes" in phrases
        assert all(not phrase[0].isdigit() or "notes" in phrase for phrase in phrases)

    def test_polarity_is_declared_rather_than_inferred(self) -> None:
        # "the number went down" and "the playing improved" are different facts.
        assert BETTER_WHEN_LOWER["mean_pitch_error_semitones"] is True
        assert BETTER_WHEN_LOWER["missed_count"] is True
        assert BETTER_WHEN_LOWER["mean_confidence"] is False

    def test_good_playing_reads_as_good(self) -> None:
        phrases = interpret(_window())
        assert "locked to the pulse" in phrases
        assert "pitching accurately" in phrases


def test_the_decision_is_deterministic() -> None:
    window = _window(missed_count=5)
    assert _turn(window) == _turn(window)


@pytest.mark.parametrize("silence", [0.0, 0.3, 0.59])
def test_every_sub_threshold_silence_is_mid_phrase(silence: float) -> None:
    assert _turn(_window(missed_count=5), silence_seconds=silence).suppressed_by == "mid_phrase"
