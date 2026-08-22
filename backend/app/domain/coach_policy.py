"""When the coach speaks, and what about.

Pure. Time enters as a parameter and never as a clock read, which is what keeps
this in `domain/` and what makes every rule below testable without waiting.

The hard part of a live coach is not generating speech. It is **not** generating
speech. A tutor who comments on every mistake is unusable: the learner is
playing, the corrections arrive on top of the notes they are still trying to
get right, and the whole thing becomes noise to be talked over. So the default
answer here is silence, and every path to speaking has to earn it:

* the learner has stopped playing (a phrase end, not mid-note);
* enough time has passed since the last utterance;
* this particular cue has not just been given;
* there is a budget left to spend;
* and there is genuinely something to say.

"Nothing to say" is a first-class outcome, not a failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Mapping

__all__ = [
    "BETTER_WHEN_LOWER",
    "CoachTurn",
    "CueKind",
    "LiveMetricWindow",
    "TurnBudget",
    "TurnHistory",
    "classify",
    "decide_turn",
    "interpret",
]


# @spec COACH-POLICY-002
class CueKind(StrEnum):
    RUSHING = "rushing"
    DRAGGING = "dragging"
    FLAT_PITCH = "flat_pitch"
    SHARP_PITCH = "sharp_pitch"
    MISSED_RUN = "missed_run"
    EXTRA_NOTES = "extra_notes"
    DYNAMICS_FLAT = "dynamics_flat"
    LOST_PLACE = "lost_place"
    GOOD_STREAK = "good_streak"
    TAKE_COMPLETE = "take_complete"


# Declared once, in a table, rather than inferred from the sign of a delta.
# Without this a coach congratulates a learner whose intonation error just went
# up, because "the number increased" and "the playing improved" are different
# facts that look identical to a model reading raw floats.
BETTER_WHEN_LOWER: Mapping[str, bool] = {
    "mean_abs_timing_error_seconds": True,
    "mean_pitch_error_semitones": True,
    "missed_count": True,
    "extra_count": True,
    "dynamics_rms_variation": False,
    "mean_confidence": False,
    "progress_ratio": False,
}


@dataclass(frozen=True, slots=True)
class LiveMetricWindow:
    """What the last few seconds of playing looked like.

    Lives in `domain/` rather than next to the matcher that fills it, because
    the policy is the thing that must import nothing.
    """

    window_seconds: float = 0.0
    note_count: int = 0
    matched_count: int = 0
    missed_count: int = 0
    extra_count: int = 0
    mean_pitch_error_semitones: float | None = None
    # Positive means sharp, negative means flat.
    signed_pitch_bias_semitones: float | None = None
    mean_abs_timing_error_seconds: float | None = None
    # Positive means late (dragging), negative means early (rushing).
    signed_timing_bias_seconds: float | None = None
    tempo_ratio: float | None = None
    mean_confidence: float = 0.0
    dynamics_rms_mean: float | None = None
    dynamics_rms_variation: float | None = None
    progress_ratio: float = 0.0
    seconds_since_cursor_moved: float = 0.0


@dataclass(frozen=True, slots=True)
class TurnBudget:
    max_utterances_per_take: int = 4
    min_seconds_between_utterances: float = 8.0
    # A phrase boundary. Shorter and the coach talks over the tail of a note.
    min_silence_seconds: float = 0.6
    same_cue_cooldown_seconds: float = 25.0
    remaining_course_budget_usd: Decimal = Decimal("1")
    estimated_utterance_cost_usd: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class TurnHistory:
    utterance_count: int = 0
    last_utterance_at_seconds: float | None = None
    last_cue: CueKind | None = None
    last_cue_at_seconds: Mapping[str, float] = None  # type: ignore[assignment]
    interventions: int = 0

    def cue_last_spoken(self, cue: CueKind) -> float | None:
        table = self.last_cue_at_seconds or {}
        return table.get(str(cue))


@dataclass(frozen=True, slots=True)
class CoachTurn:
    should_speak: bool
    cue: CueKind | None
    severity: str  # info | nudge | intervene
    reason: str
    phrase_words: tuple[str, ...]
    suppressed_by: str | None  # cooldown | budget | mid_phrase | cap | duplicate | nothing_to_say


# Thresholds. Each is a starting point rather than a discovery, and each is the
# kind of number that should move once real takes exist.
RUSHING_SECONDS = -0.09
DRAGGING_SECONDS = 0.09
PITCH_ERROR_SEMITONES = 0.45
MISSED_RUN_COUNT = 3
EXTRA_RUN_COUNT = 3
LOST_PLACE_SECONDS = 4.0
GOOD_STREAK_NOTES = 8
FLAT_DYNAMICS_VARIATION = 0.02


# @spec COACH-CUE-003
def interpret(window: LiveMetricWindow) -> tuple[str, ...]:
    """Turn the window's numbers into the words a prompt should see.

    A model handed `0.94` has to guess whether that is good. A model handed
    "rock-steady pulse" does not. Pre-interpreting is also where the polarity
    table gets applied, so the phrase can never disagree with the metric.
    """
    phrases: list[str] = []
    bias = window.signed_timing_bias_seconds
    if bias is not None:
        if bias <= RUSHING_SECONDS:
            phrases.append("running ahead of the beat")
        elif bias >= DRAGGING_SECONDS:
            phrases.append("sitting behind the beat")
        else:
            phrases.append("locked to the pulse")

    pitch_bias = window.signed_pitch_bias_semitones
    pitch_error = window.mean_pitch_error_semitones
    if pitch_bias is not None and abs(pitch_bias) >= PITCH_ERROR_SEMITONES:
        if pitch_bias > 0:
            phrases.append("reaching sharp over the notes")
        else:
            phrases.append("falling flat under the notes")
    elif pitch_error is not None:
        if pitch_error >= PITCH_ERROR_SEMITONES:
            phrases.append("landing on the wrong notes")
        elif pitch_error >= 0.2:
            phrases.append("close on pitch but not centred")
        else:
            phrases.append("pitching accurately")

    if window.missed_count >= MISSED_RUN_COUNT:
        phrases.append(f"{window.missed_count} notes skipped")
    if window.extra_count >= EXTRA_RUN_COUNT:
        phrases.append(f"{window.extra_count} notes added that are not written")
    if window.dynamics_rms_variation is not None and window.dynamics_rms_variation < FLAT_DYNAMICS_VARIATION:
        phrases.append("playing at one unvarying volume")
    if window.progress_ratio >= 0.99:
        phrases.append("at the end of the exercise")
    return tuple(phrases)


# @spec COACH-CUE-001, COACH-CUE-002, COACH-CUE-005, COACH-CUE-006, COACH-CUE-007
def classify(window: LiveMetricWindow, *, expected_count: int) -> tuple[CueKind, str] | None:
    """The single most useful thing to say right now, or nothing.

    Ordered by how much it costs the learner to leave uncorrected. Losing your
    place is the only thing worth interrupting for; everything else can wait for
    a rest.
    """
    if expected_count > 0 and window.seconds_since_cursor_moved >= LOST_PLACE_SECONDS and window.note_count > 0:
        return CueKind.LOST_PLACE, "intervene"
    if window.missed_count >= MISSED_RUN_COUNT:
        return CueKind.MISSED_RUN, "nudge"
    if window.extra_count >= EXTRA_RUN_COUNT:
        return CueKind.EXTRA_NOTES, "nudge"

    pitch_bias = window.signed_pitch_bias_semitones
    pitch_error = window.mean_pitch_error_semitones
    if pitch_bias is not None and abs(pitch_bias) >= PITCH_ERROR_SEMITONES:
        return CueKind.SHARP_PITCH if pitch_bias > 0 else CueKind.FLAT_PITCH, "nudge"
    if pitch_error is not None and pitch_error >= PITCH_ERROR_SEMITONES:
        return CueKind.SHARP_PITCH if (pitch_bias is None or pitch_bias >= 0) else CueKind.FLAT_PITCH, "nudge"

    bias = window.signed_timing_bias_seconds
    if bias is not None and bias <= RUSHING_SECONDS:
        return CueKind.RUSHING, "nudge"
    if bias is not None and bias >= DRAGGING_SECONDS:
        return CueKind.DRAGGING, "nudge"

    if window.dynamics_rms_variation is not None and window.dynamics_rms_variation < FLAT_DYNAMICS_VARIATION:
        return CueKind.DYNAMICS_FLAT, "info"

    if window.matched_count >= GOOD_STREAK_NOTES and window.missed_count == 0 and window.extra_count == 0:
        return CueKind.GOOD_STREAK, "info"
    return None


# @spec COACH-POLICY-001, COACH-POLICY-003, COACH-POLICY-004, COACH-POLICY-005,
# @spec COACH-POLICY-006, COACH-POLICY-007, COACH-POLICY-008, COACH-POLICY-009,
# @spec COACH-POLICY-010, COACH-POLICY-011
def decide_turn(
    *,
    window: LiveMetricWindow,
    history: TurnHistory,
    budget: TurnBudget,
    now_seconds: float,
    silence_seconds: float,
    expected_count: int,
    take_finished: bool = False,
) -> CoachTurn:
    """Should the coach speak now, and about what."""
    if take_finished:
        return CoachTurn(
            should_speak=True,
            cue=CueKind.TAKE_COMPLETE,
            severity="info",
            reason="The take finished.",
            phrase_words=interpret(window),
            suppressed_by=None,
        )

    classified = classify(window, expected_count=expected_count)
    if classified is None:
        return CoachTurn(False, None, "info", "Nothing worth saying.", interpret(window), "nothing_to_say")
    cue, severity = classified

    # Losing your place is the one thing worth talking over, and only once --
    # a coach who keeps interrupting to say you are lost is not helping.
    interrupts = severity == "intervene" and history.interventions == 0
    if silence_seconds < budget.min_silence_seconds and not interrupts:
        return CoachTurn(False, cue, severity, "The learner is still playing.", interpret(window), "mid_phrase")

    if history.utterance_count >= budget.max_utterances_per_take:
        return CoachTurn(False, cue, severity, "This take has had its say.", interpret(window), "cap")

    last = history.last_utterance_at_seconds
    if last is not None and now_seconds - last < budget.min_seconds_between_utterances and not interrupts:
        return CoachTurn(False, cue, severity, "Spoke too recently.", interpret(window), "cooldown")

    spoken_at = history.cue_last_spoken(cue)
    if spoken_at is not None and now_seconds - spoken_at < budget.same_cue_cooldown_seconds:
        return CoachTurn(False, cue, severity, "Already said this.", interpret(window), "duplicate")

    # The budget is an INPUT here rather than an exception thrown from the
    # gateway mid-stream. Running out mid-phrase should degrade to the
    # deterministic sentence, not surface as an error next to a good take.
    if budget.estimated_utterance_cost_usd > budget.remaining_course_budget_usd:
        return CoachTurn(False, cue, severity, "Out of course budget.", interpret(window), "budget")

    return CoachTurn(
        should_speak=True,
        cue=cue,
        severity=severity,
        reason=f"{cue} at {severity}.",
        phrase_words=interpret(window),
        suppressed_by=None,
    )
