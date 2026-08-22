"""Wire contracts for clip-based instrument practice."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ExerciseNoteOut(BaseModel):
    pitch_midi: int | None = None
    note_name: str
    onset_beats: float
    duration_beats: float
    fret: int | None = None
    string: int | None = None


class ExerciseOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    node_id: uuid.UUID
    slug: str
    title: str
    instructions: str
    score_title: str
    score_format: str
    tempo_bpm: float
    duration_beats: float
    evaluator_version: str
    difficulty: int
    notes: list[ExerciseNoteOut] = Field(default_factory=list)


class ExerciseGenerateIn(BaseModel):
    """Ask for a playable exercise on one skill node.

    Everything except the node is optional: the point is that a node gets an
    exercise automatically, derived from its own title and difficulty. The
    overrides exist because a curriculum author knows better than a keyword
    match.
    """

    node_id: uuid.UUID
    instrument: str | None = Field(default=None, max_length=24)
    pattern: str | None = Field(default=None, max_length=32)
    tonic: str | None = Field(default=None, max_length=2)
    mode: str | None = Field(default=None, max_length=8)
    tempo_bpm: int | None = Field(default=None, ge=40, le=208)
    bars: int | None = Field(default=None, ge=1, le=8)
    beats_per_measure: int | None = Field(default=None, ge=2, le=12)
    beat_type: int | None = Field(default=None, ge=2, le=8)
    title: str | None = Field(default=None, max_length=200)
    # False keeps the deterministic floor and never calls a provider.
    use_llm: bool = True


class PracticeSessionCreate(BaseModel):
    exercise_id: uuid.UUID


class LessonOut(BaseModel):
    """One lesson in a skill's run, and how far this learner has got with it."""

    exercise_id: uuid.UUID
    title: str
    #: What the learner is asked to play. Carried here so a realm can say what a
    #: lesson is before the learner commits to it.
    instructions: str
    difficulty: int
    #: Ordinal within the run, from 1.
    step: int
    attempts: int
    #: The learner's best take, or null where they have never played it.
    best_score: float | None
    cleared: bool
    #: Whether it can be played now. Everything up to the frontier is open, so a
    #: cleared lesson stays replayable -- skills decay.
    open: bool


class SkillRealmOut(BaseModel):
    """A skill's lesson run and whether its test has been earned."""

    node_id: uuid.UUID
    node_title: str
    lessons: list[LessonOut]
    #: The step to play next, or null when every lesson is cleared.
    open_step: int | None
    #: The test at the end of the run. Opens only once every lesson is cleared.
    test_open: bool


class PracticeSessionOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    exercise_id: uuid.UUID
    status: str
    created_at: datetime
    completed_at: datetime | None


class PerformedNoteIn(BaseModel):
    # None only for rhythm-only instruments (drums), where pitch is inapplicable
    # and `drum` carries the identity instead.
    pitch_midi: float | None = Field(default=None, ge=0, le=127)
    onset_seconds: float = Field(ge=0)
    duration_seconds: float = Field(default=0, ge=0)
    confidence: float = Field(default=1, ge=0, le=1)
    string: int | None = Field(default=None, ge=1, le=6)
    fret: int | None = Field(default=None, ge=0, le=24)
    # Violin intonation offset in cents (positive = sharp, negative = flat).
    cents_deviation: float | None = Field(default=None)
    # Drum identity for rhythm-only instruments; ignored elsewhere.
    drum: str | None = Field(default=None, max_length=16)
    # Mean level of the note in dBFS. Absolute loudness carries no information
    # about the player -- it is microphone gain and distance -- so the scorer
    # only ever compares these to each other. None means the client did not
    # measure it, which keeps the note out of the dynamics average entirely.
    level_db: float | None = Field(default=None, ge=-120, le=20)


class PostureMetricIn(BaseModel):
    """One physical-form reading, already reduced in the browser.

    `raw` and `unit` carry the geometry the value came from -- an angle in
    degrees, a normalized ratio. They are persisted so the thresholds can be
    retuned later against real takes; without them every posture number would be
    permanently unauditable.
    """

    key: str = Field(max_length=40)
    value: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    status: str = Field(max_length=20)
    raw: float | None = None
    unit: str | None = Field(default=None, max_length=8)


class PostureObservationIn(BaseModel):
    """Derived posture metrics for one take. Never video, never landmarks."""

    version: str = Field(max_length=32)
    threshold_version: str = Field(max_length=40)
    instrument: str | None = Field(default=None, max_length=24)
    metrics: list[PostureMetricIn] = Field(default_factory=list, max_length=12)
    frame_count: int = Field(default=0, ge=0)
    coverage: float = Field(default=0.0, ge=0, le=1)


class PerformanceAttemptCreate(BaseModel):
    observed_notes: list[PerformedNoteIn] = Field(max_length=2000)
    # The preserved original take this attempt was scored from, when one exists.
    recording_id: uuid.UUID | None = None
    # Absent when the camera was off or declined. Absent is not a failure: the
    # posture weight redistributes and the take scores exactly as it would have
    # before posture existed.
    posture: PostureObservationIn | None = None
    # Which pitch detector produced `observed_notes`.
    analyzer: str | None = Field(default=None, max_length=24)


class RecordingCreate(BaseModel):
    course_id: uuid.UUID
    format: str = Field(min_length=1, max_length=16)
    duration_seconds: float | None = Field(default=None, ge=0)
    content_base64: str = Field(min_length=1, max_length=30_000_000)


class RecordingOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    attempt_id: uuid.UUID | None
    format: str
    byte_size: int
    content_sha256: str
    duration_seconds: float | None
    created_at: datetime
    # True when this upload was a content-addressed duplicate of an existing
    # take, so the client knows the bytes were not stored twice.
    deduplicated: bool


class PerformanceMetricsOut(BaseModel):
    evaluator_version: str
    expected_note_count: int
    observed_note_count: int
    matched_note_count: int
    missed_note_count: int
    extra_note_count: int
    # None for drums: rhythm-only instruments have no pitch to score.
    pitch_accuracy: float | None
    rhythm_accuracy: float
    technique_accuracy: float | None
    position_error_count: int
    intonation_accuracy: float | None
    intonation_deviation_cents: float | None
    # None means "not measured", never "measured as zero".
    dynamics_accuracy: float | None = None
    dynamic_range_db: float | None = None
    dynamics_contrast: float | None = None
    posture_accuracy: float | None = None
    posture_version: str | None = None
    analyzer: str | None = None
    tempo_bpm: float | None
    tempo_deviation_percent: float | None
    alignment_confidence: float
    overall_score: float
    low_confidence: bool


class ExaminerFeedbackOut(BaseModel):
    persona: str
    tone: str
    summary: str
    strengths: list[str]
    corrections: list[str]
    next_step: str


class PerformanceAttemptOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    exercise_id: uuid.UUID
    status: str
    overall_score: float
    alignment_confidence: float
    exp_awarded: int
    feedback_provider: str
    created_at: datetime
    metrics: PerformanceMetricsOut
    feedback: ExaminerFeedbackOut


class VoiceArtifactOut(BaseModel):
    attempt_id: uuid.UUID
    provider: str
    voice_key: str
    format: str
    audio_base64: str | None
    spoken_text: str
    cache_key: str
    cached: bool
