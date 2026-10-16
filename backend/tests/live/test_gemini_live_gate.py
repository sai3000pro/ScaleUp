"""Gemini, against Google, for the three things the floor cannot prove.

The unit suite pins the registry, the refusals and the streaming protocol with
no network. What it cannot pin is that the configured model names still exist,
that the compatibility endpoint still honours `stream_options`, and that the
embedding model still answers at the configured dimension. Each of those has
changed under a deployment before; this is where it is noticed.
"""

from __future__ import annotations

from app.domain.vectors import unit_normalise
from app.llm.base import LLMRole, StreamDelta
from app.llm.gemini_provider import GeminiEmbeddingProvider, GeminiLLMClient
from app.llm.registry import ROLES

CHUNKS = [
    {"chunk_id": "c1", "text": "The dot product multiplies matching components and sums them."},
    {"chunk_id": "c2", "text": "Two vectors are orthogonal when their dot product is zero."},
]


# @spec LLM-LIVE-001, LLM-LIVE-002, LLM-ROLE-004
async def test_structured_call_satisfies_the_shared_schema(gemini_settings) -> None:
    result = await GeminiLLMClient().structured(
        LLMRole.QUESTION_GEN,
        {
            "node_title": "Dot Product",
            "node_summary": "Multiply matching components and sum them.",
            "context": CHUNKS,
            "requested_type": "mcq",
        },
    )
    assert result.provider == "gemini"
    assert result.model == ROLES[LLMRole.QUESTION_GEN].gemini_model
    assert result.data["question_type"] == "mcq"
    assert len(result.data["options"]) == 4
    assert result.usage.input_tokens > 0 and result.usage.output_tokens > 0
    assert result.usage.cost_usd > 0


# @spec LLM-LIVE-001, LLM-LIVE-002, LLM-PROV-004, LLM-PROV-006
async def test_stream_yields_prose_then_reported_usage(gemini_settings) -> None:
    deltas: list[StreamDelta] = []
    async for delta in GeminiLLMClient().stream_text(
        LLMRole.LIVE_COACH_CUE,
        {
            "exercise_title": "C major scale",
            "instrument": "piano",
            "cue": "rushing",
            "severity": "medium",
            "metric_words": "ahead of the beat by a tenth of a second",
            "deterministic_cue": "You are rushing the second half; sit back on the beat.",
            "recent_utterances": "(none)",
        },
    ):
        deltas.append(delta)

    spoken = "".join(delta.text for delta in deltas).strip()
    assert spoken, "a live cue that streams nothing falls to the floor without anyone noticing"
    usage = [delta.usage for delta in deltas if delta.usage is not None]
    assert usage, "the endpoint stopped honouring stream_options.include_usage"
    assert usage[-1].input_tokens > 0 and usage[-1].output_tokens > 0


# @spec LLM-LIVE-001, LLM-EMBED-002, LLM-EMBED-004
async def test_embeddings_answer_at_the_configured_dimension_and_point_the_right_way(gemini_settings) -> None:
    provider = GeminiEmbeddingProvider()
    raw = await provider.embed(
        [
            "Practise the C major scale with even eighth notes.",
            "Play a C major scale slowly, keeping every note the same length.",
            "Quarterly revenue grew because of strong advertising sales.",
        ]
    )
    assert [len(vector) for vector in raw] == [gemini_settings.embedding_dimensions] * 3

    scale_a, scale_b, revenue = (unit_normalise(vector) for vector in raw)
    near = sum(a * b for a, b in zip(scale_a, scale_b, strict=True))
    far = sum(a * b for a, b in zip(scale_a, revenue, strict=True))
    assert near > far
    assert abs(sum(x * x for x in scale_a) - 1.0) < 1e-6
