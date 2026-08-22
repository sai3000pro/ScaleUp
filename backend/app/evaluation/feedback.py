"""Deterministic examiner feedback over canonical performance metrics.

This is the zero-provider floor of the Virtual Tutor. It turns the raw metric
bundle into persona-voiced coaching that the demo can render (and an ElevenLabs
persona can later speak) even with ``LLM_PROVIDER=fake``. An LLM role may upgrade
the summary text later without changing this wire contract: strengths,
corrections, and the next step are computed here so they are always coherent and
always reference the exact misses, extras, and tempo drift the scorer found.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.evaluation.piano import PianoPerformanceScore

PERSONA = "Professor Cadenza"


@dataclass(frozen=True, slots=True)
class ExaminerFeedback:
    """Structured, persona-voiced coaching for one performance attempt."""

    persona: str
    tone: str
    summary: str
    strengths: tuple[str, ...]
    corrections: tuple[str, ...]
    next_step: str


def _tone(overall_score: float) -> str:
    if overall_score >= 0.9:
        return "celebratory"
    if overall_score >= 0.75:
        return "encouraging"
    if overall_score >= 0.5:
        return "coaching"
    return "supportive"


def _summary(score: PianoPerformanceScore, exercise_title: str) -> str:
    if score.low_confidence:
        return f"I couldn't line this take of {exercise_title} up reliably enough to score it."
    percent = round(score.overall_score * 100)
    if score.overall_score >= 0.9:
        return f"{exercise_title} was a clean, confident run at {percent}%."
    if score.overall_score >= 0.75:
        return f"{exercise_title} is solid at {percent}% - a few small fixes will make it shine."
    if score.overall_score >= 0.5:
        return f"{exercise_title} has the right shape at {percent}%; the details need one more pass."
    return f"Let's rebuild {exercise_title} step by step - it's at {percent}% right now."


def _intonation_deviation(score: PianoPerformanceScore) -> float | None:
    """Mean cents deviation when the evaluator reports intonation, else None."""
    deviation = getattr(score, "intonation_deviation_cents", None)
    return deviation if isinstance(deviation, float) else None


def _intonation_accuracy(score: PianoPerformanceScore) -> float | None:
    accuracy = getattr(score, "intonation_accuracy", None)
    return accuracy if isinstance(accuracy, float) else None


def _strengths(score: PianoPerformanceScore, instrument: str) -> tuple[str, ...]:
    strengths: list[str] = []
    if score.pitch_accuracy is not None and score.pitch_accuracy >= 0.9:
        strengths.append("Your pitch is nearly flawless.")
    elif score.pitch_accuracy is not None and score.pitch_accuracy >= 0.75:
        strengths.append("Your pitch is dependable overall.")
    intonation = _intonation_accuracy(score)
    if intonation is not None and intonation >= 0.9:
        strengths.append("Your intonation is impressively centred.")
    elif intonation is not None and intonation >= 0.75:
        strengths.append("Your intonation is mostly on the mark.")
    if score.rhythm_accuracy >= 0.9:
        strengths.append("Your rhythm is steady and even.")
    elif score.rhythm_accuracy >= 0.75:
        strengths.append("Your timing is mostly locked in.")
    if score.missed_note_count == 0 and score.extra_note_count == 0:
        strengths.append("Every written note is accounted for - nothing skipped, nothing extra.")
    if score.tempo_deviation_percent is not None and score.tempo_deviation_percent <= 5:
        strengths.append("You held the tempo within a few percent of the marking.")
    # The wire schema caps coaching lists at three items; the floor must already
    # respect the contract it shares with the LLM upgrade.
    return tuple(strengths[:3])


def _corrections(score: PianoPerformanceScore, instrument: str) -> tuple[str, ...]:
    corrections: list[str] = []
    if score.missed_note_count == 1:
        corrections.append("One written note was missed.")
    elif score.missed_note_count > 1:
        corrections.append(f"{score.missed_note_count} written notes were missed.")
    if score.extra_note_count == 1:
        corrections.append("One extra note slipped in.")
    elif score.extra_note_count > 1:
        corrections.append(f"{score.extra_note_count} extra notes slipped in.")
    deviation = _intonation_deviation(score)
    if instrument == "violin" and deviation is not None and deviation > 20:
        corrections.append("A few notes sit more than twenty cents off centre - check finger placement.")
    if score.pitch_accuracy is not None and score.pitch_accuracy < 0.7:
        corrections.append("A few pitches landed off - slow down and hear each interval before you play it.")
    if score.rhythm_accuracy < 0.7:
        corrections.append("The rhythm drifts; count each beat out loud.")
    if score.tempo_deviation_percent is not None and score.tempo_deviation_percent > 10:
        corrections.append("The tempo wandered - hold a steadier pulse.")
    return tuple(corrections[:3])


def _next_step(score: PianoPerformanceScore, instrument: str, exercise_title: str) -> str:
    action = "press" if instrument == "piano" else "play"
    if score.low_confidence:
        return "Slow the tempo and replay the first few notes once more so each one rings clearly."
    deviation = _intonation_deviation(score)
    if instrument == "violin" and deviation is not None and deviation > 20:
        return f"Bow each note of {exercise_title} slowly against a tuner until the needle stops swinging."
    if score.missed_note_count > 0:
        return f"Replay {exercise_title} slowly and make sure no written note is skipped."
    if score.extra_note_count > 0:
        return f"Replay {exercise_title} and let each {action} release before the next note starts."
    if score.pitch_accuracy is not None and score.pitch_accuracy < score.rhythm_accuracy:
        return f"Isolate the intervals of {exercise_title} and {action} them slowly until the pitches settle."
    if score.rhythm_accuracy < 0.95:
        return f"Metronome it: {action} {exercise_title} again at a slower marking and keep the pulse even."
    return f"Raise the tempo a little and {action} {exercise_title} once more to lock it in."


# @spec COACH-EXAM-001, COACH-EXAM-003, COACH-EXAM-007, COACH-EXAM-008
def generate_feedback(
    score: PianoPerformanceScore,
    *,
    exercise_title: str,
    instrument: str = "instrument",
    difficulty: int = 3,
) -> ExaminerFeedback:
    """Build persona-voiced coaching from a deterministic performance score.

    ``difficulty`` is accepted so the feedback stays exercise-aware and future
    personas can modulate how demanding the next step is; the current floor does
    not branch on it beyond the signature. Pitch-dependent lines are skipped for
    rhythm-only instruments (drums), and violin intonation is coached from the
    cents deviation when the evaluator reports it.
    """
    del difficulty  # reserved for difficulty-aware tone without breaking the contract
    return ExaminerFeedback(
        persona=PERSONA,
        tone=_tone(score.overall_score),
        summary=_summary(score, exercise_title),
        strengths=_strengths(score, instrument),
        corrections=_corrections(score, instrument),
        next_step=_next_step(score, instrument, exercise_title),
    )


# @spec COACH-EXAM-004, COACH-EXAM-005, COACH-EXAM-006
def merge_feedback(deterministic: ExaminerFeedback, upgraded: dict[str, object] | None) -> ExaminerFeedback:
    """Merge an LLM upgrade over the deterministic floor.

    Every field falls back to the deterministic value when the upgrade omits or
    empties it, so a partially valid model response still yields a complete,
    coherent coaching message. The numbers never come from here -- only wording.
    """
    if upgraded is None:
        return deterministic

    strengths = upgraded.get("strengths")
    corrections = upgraded.get("corrections")
    return ExaminerFeedback(
        persona=str(upgraded.get("persona") or deterministic.persona),
        tone=str(upgraded.get("tone") or deterministic.tone),
        summary=str(upgraded.get("summary") or deterministic.summary),
        strengths=tuple(str(item) for item in strengths) if strengths else deterministic.strengths,
        corrections=tuple(str(item) for item in corrections) if corrections else deterministic.corrections,
        next_step=str(upgraded.get("next_step") or deterministic.next_step),
    )


import random

# ── live coaching ────────────────────────────────────────────────────────────
#
# Expressive, diverse cue variations derived from measurements and LLM roles.
# The coach rotates through these variations so real-time and fallback feedback
# remains engaging, natural, and non-repetitive across takes.

_LIVE_CUE_VARIATIONS: dict[str, list[str]] = {
    "rushing": [
        "You're getting ahead of the beat - let the pulse come to you.",
        "Pull back just a touch - lock into the groove.",
        "Breathe into the tempo, don't rush the downbeat.",
        "Feel the space between the notes - relax the pulse.",
        "A little quick on the transitions - steady the tempo.",
    ],
    "dragging": [
        "You're sitting behind the beat - lean into the pulse a little.",
        "Drive the rhythm forward - anticipate the next note.",
        "Stay on the front edge of the beat.",
        "Crisp attacks - don't lag behind the click.",
        "Pick up the momentum - keep the tempo moving.",
    ],
    "flat_pitch": [
        "Those notes are landing under pitch - listen up into them.",
        "Support the tone and raise your pitch slightly.",
        "Target the center of the pitch - aim a little higher.",
        "Clean fret and key contact will bring that pitch right in tune.",
        "Lift the intonation upward on the higher intervals.",
    ],
    "sharp_pitch": [
        "You're reaching over the notes - settle back onto them.",
        "Relax the hand pressure - let the pitch settle down.",
        "Ease into the pitch - soften the attack slightly.",
        "Bring the pitch down slightly into the center of the target.",
    ],
    "missed_run": [
        "A few notes are going by unplayed - slow it down and take every one.",
        "Focus on clean transitions across that whole run.",
        "Shape every note in the phrase - leave none behind.",
        "Step cleanly through each interval one note at a time.",
    ],
    "extra_notes": [
        "There are extra notes creeping in - play only what's written.",
        "Mute neighboring strings and keys for a cleaner sound.",
        "Keep your fingers disciplined - just the target notes.",
        "Isolate each note cleanly without ghost strikes.",
    ],
    "dynamics_flat": [
        "It's all at one volume - let the loud parts be loud.",
        "Add some dynamic contrast - give the music light and shade.",
        "Bring out the accents to give the phrase more life.",
        "Vary your touch between the gentle and accented notes.",
    ],
    "lost_place": [
        "Take a breath and find your place - start again from the top of the phrase.",
        "Reset your hand position and jump back in on the downbeat.",
        "Pause, shake out the tension, and let's catch the next measure.",
        "No worries - regroup and start clean from the phrase head.",
        "Anchor your eyes on the sheet and lock into the click.",
    ],
    "good_streak": [
        "That's clean playing. Keep exactly that going.",
        "Locked in! Beautiful consistency.",
        "Spot on - great articulation!",
        "Rhythm is rock solid right now.",
        "Flawless groove - keep that momentum!",
        "Super smooth execution - sounding great!",
    ],
    "take_complete": [
        "That's the take. Let's see how it went.",
        "Take wrapped up! Let's check the breakdown.",
        "Nice run through the piece! Reviewing your score.",
        "Finished! Let's analyze your timing and pitch.",
    ],
}

_LIVE_CUE_TEXT: dict[str, str] = {
    cue: variations[0] for cue, variations in _LIVE_CUE_VARIATIONS.items()
}


# @spec COACH-CUE-004, COACH-CUE-008
def live_cue_text(cue: str, *, exercise_title: str = "", instrument: str = "", seed: int | None = None) -> str:
    """The varied pedagogical sentence for one live cue.

    Selects an expressive variation or pseudo-random rotation based on utterance seed.
    """
    del exercise_title, instrument
    options = _LIVE_CUE_VARIATIONS.get(str(cue))
    if not options:
        return _LIVE_CUE_TEXT.get(str(cue), "Keep going - I'm listening.")
    if seed is not None:
        return options[seed % len(options)]
    return random.choice(options)
