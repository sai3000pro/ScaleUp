"""The LLM seam.

Callers name a ROLE and hand over variables. They never name a model, never see
a provider SDK, and never parse prose. Everything below this line is swappable
by changing one table in `registry.py`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, AsyncIterator, Mapping, Protocol, Sequence

__all__ = [
    "LLMRole",
    "Usage",
    "StructuredResult",
    "LLMError",
    "SchemaValidationError",
    "ProviderError",
    "RefusalError",
    "BudgetExceededError",
    "LLMClient",
    "EmbeddingProvider",
    "StreamDelta",
    "StreamedResult",
    "StreamingLLMClient",
]


# @spec LLM-ROLE-001, LLM-ROLE-006
class LLMRole(StrEnum):
    """What the call is FOR. The model that serves it is a config decision."""

    GRAPH_EXTRACT_MAP = "graph_extract_map"  # per-window, high volume, cheap model
    GRAPH_MERGE = "graph_merge"  # one global reduce, strong model
    # Prerequisites inferred from section CONTENT, over the closed vocabulary of
    # skills the table of contents already produced. The TOC gives the nodes;
    # this gives the edges the outline cannot know.
    PREREQ_INFER = "prereq_infer"
    # The mirror question: "which of these sections use X?". Asked only of the
    # skills the forward pass never cited, because a foundation nobody names by
    # title is invisible to a pass that only ever reads forwards.
    PREREQ_DEPENDENTS = "prereq_dependents"
    # Names and summarises the sub-section fragments the BOOK's own lead-in
    # lines already delimited. Boundaries are found structurally in
    # `app/ingestion/segment.py`; this call never chooses them.
    SECTION_SEGMENT = "section_segment"
    # Rewrites the caption under a node. `app/ingestion/summarise.py` already
    # picks the best sentence the book itself supports; this role is the upgrade
    # over that floor, and every node it declines keeps the deterministic one.
    NODE_SUMMARY = "node_summary"
    # Compares a learner's desired campaign outcome with the generated skill
    # vocabulary. On-demand only: it is advisory, not part of every briefing
    # read, and it must never invent skills outside the supplied graph.
    CAMPAIGN_OUTCOME_EVAL = "campaign_outcome_eval"
    # Answers a learner's own question about a course, citing the nodes and
    # chunks the answer came from. The inverse of QUESTION_GEN, which only ever
    # asks questions *at* the learner.
    COURSE_QA = "course_qa"
    # Turns a learner's stated goal plus the whole shared catalogue into a
    # prerequisite tree. The catalogue is passed as a CLOSED vocabulary to select
    # from: a model asked to invent a syllabus invents a different one every call
    # and shares nothing between instruments, while a model asked to select
    # returns the same skill entities other instruments already use. Every plan
    # is validated before anything is written, and a rejected plan falls back to
    # deterministic assembly rather than failing the learner's request.
    CURRICULUM_PLAN = "curriculum_plan"
    QUESTION_GEN = "question_gen"
    GRADE = "grade"
    # Turns a canonical performance metric bundle into concise, persona-voiced
    # coaching. Runs once per submitted attempt, after the deterministic
    # examiner has already produced the floor; this role only rewrites the
    # learner-facing wording, never the numbers. Falls back to the deterministic
    # feedback whenever the call fails, so the practice result is never held
    # hostage to a provider outage.
    PERFORMANCE_FEEDBACK = "performance_feedback"
    # Composes a more musical exercise than the procedural generator's scale or
    # arpeggio, as a NOTE LIST the deterministic renderer turns into MusicXML.
    # The model never writes XML: guitar string/fret and drum staff positions
    # are derived from the same tables the scorers read, because a hallucinated
    # fret becomes a wrong technique score and a hallucinated drum becomes a
    # missed hit -- both of which look like the learner's fault. Any failure
    # keeps the procedural floor, so a node always has something playable.
    SCORE_COMPOSE = "score_compose"
    # One or two spoken sentences during a live practice take. The only
    # streaming role: a learner waiting on a complete JSON object before hearing
    # anything has already played the next phrase. Latency is the product here,
    # which is why the registry points it at the cheapest capable model.
    LIVE_COACH_CUE = "live_coach_cue"


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    latency_ms: int = 0


@dataclass(frozen=True, slots=True)
class StructuredResult:
    data: dict[str, Any]
    raw_text: str
    model: str
    provider: str
    prompt_id: str
    prompt_version: str
    prompt_sha256: str
    request_fingerprint: str
    usage: Usage = field(default_factory=Usage)
    # The `llm_calls` row this call produced. Providers never set it -- they know
    # nothing about Postgres, which is the whole point of the seam. It is filled
    # in by `services.llm_gateway.RecordingLLMClient` after the ledger write, so
    # a caller that wants to link its own row to the exact call that produced it
    # (`attempts.grade_llm_call_id`) can, without a second lookup and without
    # guessing which of several concurrent calls was its own.
    llm_call_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class StreamDelta:
    """One chunk of a streamed reply. Text only -- never partial JSON."""

    text: str


@dataclass(frozen=True, slots=True)
class StreamedResult:
    """How a stream ended, for the ledger."""

    text: str
    model: str
    provider: str
    prompt_id: str
    prompt_version: str
    prompt_sha256: str
    request_fingerprint: str
    usage: Usage = field(default_factory=Usage)
    # ok | cancelled | provider_error | timeout | refusal
    status: str = "ok"
    llm_call_id: uuid.UUID | None = None


class LLMError(RuntimeError):
    """Base for every failure this layer reports."""


class SchemaValidationError(LLMError):
    """The model returned JSON that does not satisfy the contract."""


class ProviderError(LLMError):
    """Transport, rate limit, or upstream failure. Usually worth retrying."""


class RefusalError(LLMError):
    """The model declined. Never worth retrying with the same input."""


class BudgetExceededError(LLMError):
    """The course budget cannot cover the next estimated billable call."""

    def __init__(self, *, budget_usd: object, spent_usd: object, estimated_usd: object) -> None:
        self.budget_usd = budget_usd
        self.spent_usd = spent_usd
        self.estimated_usd = estimated_usd
        super().__init__(
            f"This course has reached its ${budget_usd} budget; "
            f"the next call is estimated at ${estimated_usd}."
        )


class LLMClient(Protocol):
    provider: str

    def model_for(self, role: LLMRole) -> str:
        """Which model this client would use for `role`.

        Needed so the `llm_calls` ledger can attribute a *failed* call to a
        model: when `structured` raises, there is no result to read it from, and
        a failure row with an empty model is the row you most want populated.
        """
        ...

    async def structured(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        *,
        course_id: str | None = None,
    ) -> StructuredResult:
        """Render the role's prompt, call the model, validate against its schema.

        Implementations must raise SchemaValidationError rather than returning
        malformed data -- a caller that has to re-check the shape defeats the
        point of the seam.
        """
        ...


class EmbeddingProvider(Protocol):
    dimensions: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Batched. Returns one vector per input, in order."""
        ...


# @spec LLM-ROLE-005
class StreamingLLMClient(Protocol):
    """Providers that can stream prose.

    A separate Protocol rather than another method on `LLMClient`, so
    `structured()` keeps its JSON-Schema guarantee untouched and a provider can
    support one without the other. Streaming roles return prose by design: you
    cannot speak a half-parsed JSON object, and an incremental JSON parser is
    the wrong complexity for a sentence.
    """

    provider: str

    def model_for(self, role: LLMRole) -> str: ...

    def stream_text(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        *,
        course_id: str | None = None,
    ) -> AsyncIterator[StreamDelta]: ...
