"""The billable-call guard must stop spend before a provider is contacted."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from decimal import Decimal

import pytest

from app.llm.base import BudgetExceededError, LLMRole
from app.repositories import llm_calls
from app.services import llm_gateway

COURSE_ID = uuid.uuid4()


def test_assert_budget_rejects_when_estimate_crosses_limit(monkeypatch) -> None:
    class FakeSession:
        def scalar(self, _statement):
            return Decimal("4.80")

    @contextmanager
    def fake_sync_session():
        yield FakeSession()

    monkeypatch.setattr(llm_calls, "sync_session", fake_sync_session)

    with pytest.raises(BudgetExceededError) as caught:
        llm_calls.assert_budget(
            course_id=COURSE_ID,
            estimated_cost_usd=Decimal("0.30"),
            budget_usd=Decimal("5.00"),
        )

    assert caught.value.spent_usd == Decimal("4.80")
    assert caught.value.estimated_usd == Decimal("0.30")


async def test_structured_preflight_stops_inner_client(monkeypatch) -> None:
    calls = 0

    class Inner:
        provider = "openai"

        def model_for(self, _role):
            return "gpt-4o-mini"

        async def structured(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            raise AssertionError("the provider must not be contacted after the preflight fails")

    def reject(**_kwargs):
        raise BudgetExceededError(
            budget_usd=Decimal("5.00"),
            spent_usd=Decimal("4.99"),
            estimated_usd=Decimal("0.02"),
        )

    monkeypatch.setattr(llm_gateway.llm_calls, "assert_budget", reject)
    client = llm_gateway.RecordingLLMClient(Inner(), course_id=COURSE_ID)

    with pytest.raises(BudgetExceededError):
        await client.structured(
            LLMRole.QUESTION_GEN,
            {
                "node_title": "Vectors",
                "node_summary": "Vectors are ordered lists of numbers.",
                "context": "A vector is an ordered list of numbers.",
                "requested_type": "short_answer",
            },
        )

    assert calls == 0


def test_embedding_preflight_stops_provider(monkeypatch) -> None:
    calls = 0

    def reject(**_kwargs):
        nonlocal calls
        calls += 1
        raise BudgetExceededError(
            budget_usd=Decimal("5.00"),
            spent_usd=Decimal("4.99"),
            estimated_usd=Decimal("0.02"),
        )

    monkeypatch.setattr(llm_gateway.llm_calls, "assert_budget", reject)
    def provider_must_not_run(_texts):
        raise AssertionError("provider called")

    monkeypatch.setattr(llm_gateway, "embed_texts", provider_must_not_run)

    with pytest.raises(BudgetExceededError):
        llm_gateway.embed_texts_recorded(["a vector is an ordered list of numbers"], course_id=COURSE_ID)

    assert calls == 1


def test_budget_error_message_is_actionable() -> None:
    error = BudgetExceededError(
        budget_usd=Decimal("5.00"),
        spent_usd=Decimal("4.99"),
        estimated_usd=Decimal("0.02"),
    )
    assert "reached" in str(error)
    assert "$5.00" in str(error)
