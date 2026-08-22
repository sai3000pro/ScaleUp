"""Following a performance while it happens.

The batch scorers align a complete take against a complete score with DTW. That
is the right tool for grading and the wrong one for coaching: DTW needs both
sequences before it can start, and it is free to revise an early alignment once
it sees the end. A live cue that changes its mind is worse than no cue -- the
learner sees "missed note" appear and then vanish.

So this is a **monotone cursor with bounded lookahead**. Each arriving note is
matched against the next few expected notes; the cursor only moves forward, and
a committed outcome is never revised. O(1) per note, bounded memory, and stable
enough to render.

Two things follow from that, both deliberate:

* It cannot recover from a mid-take restart the way global DTW can. That is
  acceptable **because this never produces the grade** -- at end of take the
  server hands the full note list to the existing `submit_attempt`, which runs
  the same batch scorer it always has. This is advisory only.
* Because it is advisory, its divergence from the batch scorer is worth
  measuring rather than assuming. The streaming session records both, so "how
  good is the live matcher" is a query rather than an opinion.

The cost weights are imported from the piano scorer rather than restated, so the
live and batch notions of "close enough" cannot drift apart.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Sequence

from app.domain.coach_policy import LiveMetricWindow
from app.evaluation.musicxml import MusicXMLScore
from app.evaluation.piano import CONFIDENCE_COST_WEIGHT, PITCH_COST_WEIGHT, TIMING_COST_WEIGHT

__all__ = [
    "MATCH_COST_CEILING",
    "ExpectedEvent",
    "MatchOutcome",
    "MatcherState",
    "ObservedEvent",
    "advance",
    "expected_events",
    "flush_stale",
    "new_matcher",
    "rolling_window",
]

# Above this the arriving note is not a plausible attempt at anything in the
# lookahead window, so it is an extra note rather than a bad match.
MATCH_COST_CEILING = 0.85
DEFAULT_LOOKAHEAD = 4


@dataclass(frozen=True, slots=True)
class ExpectedEvent:
    index: int
    pitch_midi: int | None
    onset_seconds: float
    drum: str | None = None


@dataclass(frozen=True, slots=True)
class ObservedEvent:
    pitch_midi: float | None
    onset_seconds: float
    duration_seconds: float = 0.0
    confidence: float = 1.0
    drum: str | None = None
    level_db: float | None = None


@dataclass(frozen=True, slots=True)
class MatchOutcome:
    kind: str  # matched | missed | extra
    expected_index: int | None
    observed_index: int | None
    pitch_error_semitones: float | None
    # Signed: positive is late.
    timing_error_seconds: float | None
    quality: float


@dataclass(frozen=True, slots=True)
class MatcherState:
    cursor: int = 0
    committed: tuple[MatchOutcome, ...] = ()
    observed_count: int = 0
    last_cursor_move_seconds: float = 0.0
    levels: tuple[float, ...] = ()


def expected_events(score: MusicXMLScore, instrument: str, repeats: int = 1) -> tuple[ExpectedEvent, ...]:
    """The score as a flat, time-ordered event list, looped across `repeats` measures for drills.

    Chord notes collapse to their earliest onset the way the chord scorer treats
    them, so a strum is one thing to hit rather than six things to miss.
    """
    seconds_per_beat = 60.0 / score.tempo_bpm
    events: list[ExpectedEvent] = []
    seen_onsets: set[float] = set()
    polyphonic = instrument in {"guitar", "piano"}

    base_notes: list[tuple[int | None, float, str | None]] = []
    max_onset_beats = 0.0
    for note in score.notes:
        playable = note.pitch_midi is not None or note.unpitched_step is not None
        if not playable:
            pass
        elif polyphonic and note.onset_beats in seen_onsets:
            pass
        else:
            seen_onsets.add(note.onset_beats)
            base_notes.append((note.pitch_midi, note.onset_beats, note.unpitched_step))
            if note.onset_beats > max_onset_beats:
                max_onset_beats = note.onset_beats

    if not base_notes:
        return ()

    num_repeats = repeats if max_onset_beats < 12.0 else 1
    measure_beats = max(4.0, math.ceil((max_onset_beats + 0.1) / 4.0) * 4.0)

    for r in range(num_repeats):
        beat_offset = r * measure_beats
        for pitch_midi, onset_beats, drum in base_notes:
            events.append(
                ExpectedEvent(
                    index=len(events),
                    pitch_midi=pitch_midi,
                    onset_seconds=(onset_beats + beat_offset) * seconds_per_beat,
                    drum=drum,
                )
            )
    return tuple(events)


def new_matcher() -> MatcherState:
    return MatcherState()


# @spec EVAL-LIVE-004
def _cost(expected: ExpectedEvent, observed: ObservedEvent, timing_tolerance: float) -> float:
    if expected.pitch_midi is None or observed.pitch_midi is None:
        pitch_cost = 0.0 if expected.pitch_midi is None and observed.pitch_midi is None else 1.0
    else:
        diff = abs(expected.pitch_midi - observed.pitch_midi)
        if diff <= 0.8:
            pitch_cost = 0.0
        elif diff <= 1.8:
            pitch_cost = 0.18
        elif diff >= 11.2 and round(diff) % 12 <= 0.8:
            # Octave harmonic
            pitch_cost = 0.12
        else:
            pitch_cost = min(diff / 4.0, 1.0)
    timing_cost = min(abs(expected.onset_seconds - observed.onset_seconds) / max(timing_tolerance * 1.5, 0.4), 1.0)
    confidence_cost = 1.0 - observed.confidence
    return PITCH_COST_WEIGHT * pitch_cost + TIMING_COST_WEIGHT * timing_cost + CONFIDENCE_COST_WEIGHT * confidence_cost


# @spec EVAL-LIVE-001, EVAL-LIVE-002, EVAL-LIVE-005
def advance(
    state: MatcherState,
    expected: Sequence[ExpectedEvent],
    observation: ObservedEvent,
    observation_index: int,
    *,
    timing_tolerance: float,
    lookahead: int = DEFAULT_LOOKAHEAD,
) -> tuple[MatcherState, tuple[MatchOutcome, ...]]:
    """Fold one observed note in. Returns the new state and what it just decided."""
    window = [
        event for event in expected[state.cursor : state.cursor + lookahead]
    ]
    if not window:
        outcome = MatchOutcome("extra", None, observation_index, None, None, 0.0)
        return (
            replace(state, committed=state.committed + (outcome,), observed_count=state.observed_count + 1),
            (outcome,),
        )

    scored = [(event, _cost(event, observation, timing_tolerance)) for event in window]
    best_event, best_cost = min(scored, key=lambda pair: (pair[1], pair[0].index))

    if best_cost > MATCH_COST_CEILING:
        outcome = MatchOutcome("extra", None, observation_index, None, None, 0.0)
        return (
            replace(state, committed=state.committed + (outcome,), observed_count=state.observed_count + 1),
            (outcome,),
        )

    emitted: list[MatchOutcome] = []
    # Anything the cursor jumped over was never played.
    for skipped in expected[state.cursor : best_event.index]:
        emitted.append(MatchOutcome("missed", skipped.index, None, None, None, 0.0))

    pitch_error = (
        None
        if best_event.pitch_midi is None or observation.pitch_midi is None
        else observation.pitch_midi - best_event.pitch_midi
    )
    timing_error = observation.onset_seconds - best_event.onset_seconds
    emitted.append(
        MatchOutcome(
            kind="matched",
            expected_index=best_event.index,
            observed_index=observation_index,
            pitch_error_semitones=pitch_error,
            timing_error_seconds=timing_error,
            quality=max(0.0, 1.0 - best_cost),
        )
    )

    levels = state.levels if observation.level_db is None else state.levels + (observation.level_db,)
    return (
        MatcherState(
            cursor=best_event.index + 1,
            committed=state.committed + tuple(emitted),
            observed_count=state.observed_count + 1,
            last_cursor_move_seconds=observation.onset_seconds,
            levels=levels[-64:],
        ),
        tuple(emitted),
    )


# @spec EVAL-LIVE-003
def flush_stale(
    state: MatcherState,
    expected: Sequence[ExpectedEvent],
    *,
    now_seconds: float,
    timing_tolerance: float,
) -> tuple[MatcherState, tuple[MatchOutcome, ...]]:
    """Commit notes whose moment has passed without anything arriving.

    This is how silence registers. Without it a learner who stops halfway
    through shows no missed notes at all -- the cursor simply never moves, and
    the live view says everything is fine.
    """
    if now_seconds < 0.0:
        return state, ()
    emitted: list[MatchOutcome] = []
    cursor = state.cursor
    grace_period = max(timing_tolerance * 2.5, 2.0)
    while cursor < len(expected) and expected[cursor].onset_seconds + grace_period < now_seconds:
        emitted.append(MatchOutcome("missed", expected[cursor].index, None, None, None, 0.0))
        cursor += 1
    if not emitted:
        return state, ()
    return replace(state, cursor=cursor, committed=state.committed + tuple(emitted)), tuple(emitted)


def rolling_window(
    state: MatcherState,
    *,
    now_seconds: float,
    window_seconds: float,
    expected_count: int,
    recent_outcomes: int = 12,
) -> LiveMetricWindow:
    """Summarise the recent past for the coach policy."""
    recent = state.committed[-recent_outcomes:]
    matched = [outcome for outcome in recent if outcome.kind == "matched"]
    missed = [outcome for outcome in recent if outcome.kind == "missed"]
    extra = [outcome for outcome in recent if outcome.kind == "extra"]

    pitch_errors = [abs(o.pitch_error_semitones) for o in matched if o.pitch_error_semitones is not None]
    raw_pitch_errors = [o.pitch_error_semitones for o in matched if o.pitch_error_semitones is not None]
    timing_errors = [o.timing_error_seconds for o in matched if o.timing_error_seconds is not None]
    levels = state.levels[-recent_outcomes:]
    level_mean = sum(levels) / len(levels) if levels else None
    level_variation = None
    if len(levels) >= 4 and level_mean is not None:
        spread = max(levels) - min(levels)
        # Normalised against a 24 dB working range, matching `dynamics.py`.
        level_variation = min(1.0, spread / 24.0)

    return LiveMetricWindow(
        window_seconds=window_seconds,
        note_count=len(recent),
        matched_count=len(matched),
        missed_count=len(missed),
        extra_count=len(extra),
        mean_pitch_error_semitones=sum(pitch_errors) / len(pitch_errors) if pitch_errors else None,
        signed_pitch_bias_semitones=sum(raw_pitch_errors) / len(raw_pitch_errors) if raw_pitch_errors else None,
        mean_abs_timing_error_seconds=(
            sum(abs(value) for value in timing_errors) / len(timing_errors) if timing_errors else None
        ),
        signed_timing_bias_seconds=sum(timing_errors) / len(timing_errors) if timing_errors else None,
        tempo_ratio=None,
        mean_confidence=sum(o.quality for o in matched) / len(matched) if matched else 0.0,
        dynamics_rms_mean=level_mean,
        dynamics_rms_variation=level_variation,
        progress_ratio=0.0 if expected_count == 0 else min(1.0, state.cursor / expected_count),
        seconds_since_cursor_moved=max(0.0, now_seconds - state.last_cursor_move_seconds),
    )
