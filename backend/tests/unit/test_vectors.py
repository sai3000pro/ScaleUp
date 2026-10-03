"""Embedding vectors are unit length at the gateway seam."""

from __future__ import annotations

import math

from app.domain.vectors import unit_normalise
from app.services import llm_gateway


# @spec LLM-EMBED-004
def test_unit_normalise_scales_to_length_one() -> None:
    assert unit_normalise([3.0, 4.0]) == [0.6, 0.8]
    assert math.isclose(math.sqrt(sum(x * x for x in unit_normalise([1.0, 2.0, 2.0]))), 1.0)


# @spec LLM-EMBED-004
def test_a_zero_vector_has_no_direction() -> None:
    assert unit_normalise([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]


# @spec LLM-EMBED-004
def test_an_already_unit_vector_is_unchanged() -> None:
    unit = [0.6, 0.8]
    assert all(math.isclose(a, b, abs_tol=1e-12) for a, b in zip(unit_normalise(unit), unit))


# @spec LLM-EMBED-004
def test_the_gateway_normalises_provider_vectors(monkeypatch) -> None:
    monkeypatch.setattr(llm_gateway, "embed_texts", lambda texts: [[3.0, 4.0], [0.0, 0.0]])
    monkeypatch.setattr(llm_gateway.llm_calls, "record", lambda **kwargs: None)

    vectors = llm_gateway.embed_texts_recorded(["one", "two"])

    assert vectors[0] == [0.6, 0.8]
    assert vectors[1] == [0.0, 0.0]
