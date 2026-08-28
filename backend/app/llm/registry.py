"""Role -> model/prompt/schema. The one table that controls what an ingest costs.

A 1000-page book is ~120 GRAPH_EXTRACT_MAP calls and exactly one GRAPH_MERGE.
Serving the map phase with a cheap model and the reduce with a strong one is the
difference between a cents-scale ingest and a dollars-scale one, and it is a
one-line change here rather than a code change anywhere.

Anthropic and OpenAI ids are exact strings with no date suffixes.

Gemini is on moving aliases, and that is a trade rather than an oversight. Google
retires numbered Gemini ids to new keys quickly -- the whole 2.5 family already
answers 404 for a key issued today -- so a pinned id is a build that stops working
on a date nobody chose. The cost is that `gemini-flash-latest` can change model
under a fixed prompt version, which weakens "did grading change after I edited the
rubric?" for Gemini-served calls; `llm_calls` still records the alias that ran, so
the question narrows rather than disappearing. Pin an exact id here the moment
reproducibility matters more than staying reachable.

The pro tier is unreachable on a free-tier key: `gemini-2.5-pro` is closed to new
keys and `gemini-3.1-pro-preview` answers 429 without a paid plan. Roles that want
the strongest model point at the strongest *reachable* one.

Every role names one model per provider. A provider column that borrowed another
provider's column would make this table -- the one that answers "what does an
ingest cost" -- report the wrong price the moment the borrowed name is not what
actually ran.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.llm.base import LLMRole


@dataclass(frozen=True, slots=True)
# @spec LLM-ROLE-002, LLM-ROLE-003
class RoleConfig:
    prompt_id: str
    prompt_version: str
    schema_id: str
    schema_version: str
    anthropic_model: str
    openai_model: str
    gemini_model: str
    #: Where the Gemini primary above answers "overloaded" or "rate limited",
    #: the model the call is re-attempted on. Empty means this role has no
    #: cheaper reachable sibling and drops straight to the deterministic floor.
    #: Priced in the same table as the primary, because a fallen-back call is
    #: billed at the model that answered it.
    gemini_fallback_model: str
    #: Which workload this role belongs to: "ingest" (compiling a curriculum),
    #: "tutor" (drilling, grading and feedback) or "live" (the streaming coach).
    #: A provider credential can be set per lane, so a quota exhausted while
    #: ingesting a book does not silence a learner mid-take.
    lane: str
    max_tokens: int
    effort: str  # anthropic only: low | medium | high | xhigh | max


#: Workload lanes, in the order a deployment usually wants to isolate them.
LANES: tuple[str, ...] = ("ingest", "tutor", "live")


#: How long a call in each lane may wait on the provider, in seconds.
#:
#: A deadline belongs to whoever is waiting, and the three lanes differ in exactly
#: that. An ingest runs unattended inside a Celery task and should be patient rather
#: than abandon a book halfway. A learner watching a drill spinner will not wait a
#: minute for a question. A learner mid-take has already started playing again by the
#: time a cue arrives late, which is why `live` is tighter than a network round trip
#: to a busy model usually needs -- a late cue is worse than the deterministic one.
#:
#: These are ceilings clamped by GEMINI_TIMEOUT_SECONDS, so lowering that setting
#: still lowers every lane, while raising it cannot make an interactive path patient.
LANE_TIMEOUT_SECONDS: dict[str, float] = {
    "ingest": 45.0,
    "tutor": 10.0,
    "live": 4.0,
}

#: Lanes that decline the SDK's own retry. Retrying the alias that is overloaded
#: doubles the wait before reaching the answer the fallback model had all along, and
#: for these two lanes that wait is the product. `ingest` keeps its retry: nobody is
#: watching, and a transient blip mid-book is worth absorbing quietly.
LANES_WITHOUT_SDK_RETRY: frozenset[str] = frozenset({"tutor", "live"})


ROLES: dict[LLMRole, RoleConfig] = {
    # High volume. Cheap model, modest effort.
    LLMRole.GRAPH_EXTRACT_MAP: RoleConfig(
        prompt_id="graph_extract",
        prompt_version="v1",
        schema_id="concept_map",
        schema_version="v1",
        anthropic_model="claude-haiku-4-5",
        openai_model="gpt-4o-mini",
        gemini_model="gemini-flash-lite-latest",
        gemini_fallback_model="",
        lane="ingest",
        max_tokens=8000,
        effort="medium",
    ),
    # One call per learner goal, and it decides the shape of everything that
    # learner will see. Worth the strong model: the tree is the product.
    LLMRole.CURRICULUM_PLAN: RoleConfig(
        prompt_id="curriculum_plan",
        prompt_version="v2",
        schema_id="curriculum_plan",
        schema_version="v1",
        anthropic_model="claude-opus-5",
        openai_model="gpt-4o",
        gemini_model="gemini-flash-latest",
        gemini_fallback_model="gemini-flash-lite-latest",
        lane="ingest",
        max_tokens=8000,
        effort="high",
    ),
    # Runs once per ingest and decides the shape of the whole tree. Worth the
    # strong model and the higher effort.
    LLMRole.GRAPH_MERGE: RoleConfig(
        prompt_id="graph_merge",
        prompt_version="v1",
        schema_id="graph_merge",
        schema_version="v1",
        anthropic_model="claude-opus-5",
        openai_model="gpt-4o",
        gemini_model="gemini-flash-latest",
        gemini_fallback_model="gemini-flash-lite-latest",
        lane="ingest",
        max_tokens=16000,
        effort="high",
    ),
    # One call per section, so volume scales with the book -- a cheap model,
    # kept honest by a closed slug vocabulary and a required quotation.
    LLMRole.PREREQ_INFER: RoleConfig(
        prompt_id="prereq_infer",
        prompt_version="v1",
        schema_id="prereq_edges",
        schema_version="v1",
        anthropic_model="claude-haiku-4-5",
        openai_model="gpt-4o-mini",
        gemini_model="gemini-flash-lite-latest",
        gemini_fallback_model="",
        lane="ingest",
        max_tokens=4000,
        effort="medium",
    ),
    # The mirror of PREREQ_INFER, run only for under-cited skills and batched,
    # so its volume is capped rather than per-section. Same cheap model: the
    # judgement is "does this excerpt use the thing I just defined?", which is
    # reading, not reasoning.
    LLMRole.PREREQ_DEPENDENTS: RoleConfig(
        prompt_id="prereq_dependents",
        prompt_version="v1",
        schema_id="prereq_dependents",
        schema_version="v1",
        anthropic_model="claude-haiku-4-5",
        openai_model="gpt-4o-mini",
        gemini_model="gemini-flash-lite-latest",
        gemini_fallback_model="",
        lane="ingest",
        max_tokens=4000,
        effort="medium",
    ),
    # One call per section that the book's own lead-ins split. The boundaries
    # are already fixed by the time this runs, so the model is only writing a
    # title and a summary for text it can see -- a cheap model's job.
    LLMRole.SECTION_SEGMENT: RoleConfig(
        prompt_id="section_segment",
        prompt_version="v1",
        schema_id="section_fragments",
        schema_version="v1",
        anthropic_model="claude-haiku-4-5",
        openai_model="gpt-4o-mini",
        gemini_model="gemini-flash-lite-latest",
        gemini_fallback_model="",
        lane="ingest",
        max_tokens=8000,
        effort="medium",
    ),
    # A dozen nodes per call, so a 200-node textbook is ~17 calls. The model is
    # rewording an excerpt it can see into one sentence -- the same job as
    # SECTION_SEGMENT, and the same cheap model.
    LLMRole.NODE_SUMMARY: RoleConfig(
        prompt_id="node_summary",
        prompt_version="v1",
        schema_id="node_summaries",
        schema_version="v1",
        anthropic_model="claude-haiku-4-5",
        openai_model="gpt-4o-mini",
        gemini_model="gemini-flash-lite-latest",
        gemini_fallback_model="",
        lane="ingest",
        max_tokens=4000,
        effort="medium",
    ),
    # One call per question a learner asks, and they read the answer. Cheap
    # models paraphrase; this one has to stay inside the retrieved passages and
    # quote them, so it gets the same model as GRADE.
    LLMRole.COURSE_QA: RoleConfig(
        prompt_id="course_qa",
        prompt_version="v1",
        schema_id="course_qa",
        schema_version="v1",
        anthropic_model="claude-sonnet-5",
        openai_model="gpt-4o",
        gemini_model="gemini-flash-latest",
        gemini_fallback_model="gemini-flash-lite-latest",
        lane="tutor",
        max_tokens=4000,
        effort="medium",
    ),
    # On-demand campaign review. It sees only the learner's outcome and the
    # generated skill summaries, so its judgement is advisory and closed over
    # the actual tree rather than a second curriculum generator.
    LLMRole.CAMPAIGN_OUTCOME_EVAL: RoleConfig(
        prompt_id="campaign_outcome_eval",
        prompt_version="v1",
        schema_id="campaign_outcome_eval",
        schema_version="v1",
        anthropic_model="claude-sonnet-5",
        openai_model="gpt-4o",
        gemini_model="gemini-flash-latest",
        gemini_fallback_model="gemini-flash-lite-latest",
        lane="tutor",
        max_tokens=3000,
        effort="medium",
    ),
    LLMRole.QUESTION_GEN: RoleConfig(
        prompt_id="question_gen",
        prompt_version="v3",
        schema_id="question",
        schema_version="v3",
        anthropic_model="claude-sonnet-5",
        openai_model="gpt-4o-mini",
        gemini_model="gemini-flash-latest",
        gemini_fallback_model="gemini-flash-lite-latest",
        lane="tutor",
        max_tokens=4000,
        effort="medium",
    ),
    # The learner sees this output and judges the product by it. Strong model.
    LLMRole.GRADE: RoleConfig(
        prompt_id="grade",
        prompt_version="v1",
        schema_id="grade",
        schema_version="v1",
        anthropic_model="claude-sonnet-5",
        openai_model="gpt-4o",
        gemini_model="gemini-flash-latest",
        gemini_fallback_model="gemini-flash-lite-latest",
        lane="tutor",
        max_tokens=4000,
        effort="high",
    ),
    # One call per submitted performance attempt, and the learner reads it
    # directly, so the wording is worth a strong model. It only rewrites the
    # deterministic examiner's floor -- a failure falls back without losing a
    # single metric.
    LLMRole.PERFORMANCE_FEEDBACK: RoleConfig(
        prompt_id="performance_feedback",
        # v2 adds the ABRSM-style assessment frame and, more importantly, the
        # rule that an axis reported as "not assessed" must not be graded.
        # v1.md stays on disk untouched: every historical `llm_calls` row points
        # at its sha256, and that is the only thing that makes "did the coaching
        # change when I edited the rubric?" answerable after the fact.
        prompt_version="v2",
        schema_id="performance_feedback",
        schema_version="v1",
        anthropic_model="claude-sonnet-5",
        openai_model="gpt-4o",
        gemini_model="gemini-flash-latest",
        gemini_fallback_model="gemini-flash-lite-latest",
        lane="tutor",
        max_tokens=2000,
        effort="medium",
    ),
    # One call per exercise created, and the learner then plays the result over
    # and over -- so this is worth a strong model, the same reasoning as
    # PERFORMANCE_FEEDBACK. It is also strictly optional: the procedural
    # generator has already produced a valid score before this is asked.
    LLMRole.SCORE_COMPOSE: RoleConfig(
        prompt_id="score_compose",
        prompt_version="v1",
        schema_id="score_notes",
        schema_version="v1",
        anthropic_model="claude-sonnet-5",
        openai_model="gpt-4o",
        gemini_model="gemini-flash-latest",
        gemini_fallback_model="gemini-flash-lite-latest",
        lane="tutor",
        max_tokens=4000,
        effort="medium",
    ),
    # Spoken during a live take, so latency IS the product: a strong model that
    # starts talking two seconds late is worse than a cheap one that starts in
    # four hundred milliseconds. The schema is registered for `prepare()`'s
    # benefit and unused on the streaming path, which returns prose.
    LLMRole.LIVE_COACH_CUE: RoleConfig(
        prompt_id="live_coach_cue",
        prompt_version="v1",
        schema_id="live_coach_cue",
        schema_version="v1",
        anthropic_model="claude-haiku-4-5",
        openai_model="gpt-4o-mini",
        gemini_model="gemini-flash-lite-latest",
        gemini_fallback_model="",
        lane="live",
        max_tokens=120,
        effort="low",
    ),
}

# USD per million tokens, (input, output). Used to populate llm_calls.cost_usd
# so `GET /courses/{id}/cost` can answer "what did this book cost me?".
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-5": (Decimal("5.00"), Decimal("25.00")),
    "claude-sonnet-5": (Decimal("3.00"), Decimal("15.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
    "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    # Carried from the 2.5 tier rates rather than measured: these are the tiers
    # Google prices at, not confirmed figures for the 3.x ids. Confirm against the
    # current price list before anyone treats GET /api/courses/{id}/cost as an
    # invoice -- an unpriced model bills as zero, which is worse than being wrong.
    "gemini-flash-latest": (Decimal("0.30"), Decimal("2.50")),
    "gemini-flash-lite-latest": (Decimal("0.10"), Decimal("0.40")),
    "gemini-3.1-pro-preview": (Decimal("1.25"), Decimal("10.00")),
    "text-embedding-3-small": (Decimal("0.02"), Decimal("0")),
    "fake": (Decimal("0"), Decimal("0")),
}


# @spec LLM-LEDGER-004
def price_for(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    rate_in, rate_out = PRICES.get(model, (Decimal(0), Decimal(0)))
    million = Decimal(1_000_000)
    return (rate_in * Decimal(input_tokens) / million) + (rate_out * Decimal(output_tokens) / million)
