"""Route each role to the provider its workload lane actually has a credential for.

A deployment rarely turns a paid provider on everywhere at once. You put a key
against the work you are testing -- compiling curricula, say -- and leave the rest
alone until you are ready to spend on it. Without somewhere to express that, the
choice is all roles or none, and "none" means the feature you are testing does not
run at all.

So a lane with no credential does not refuse and does not error: it falls back to
the deterministic provider, which is the same floor the whole product runs on with
no keys configured. A provider is an upgrade, never a dependency. Turning one lane
on is turning one lane on.

The router is invisible to callers. They name a role; the role declares its lane;
the lane decides which client serves it. Nothing upstream learns that two providers
are in play -- except the ledger, which has to, because a row that named the wrong
provider would make the cost record fiction.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Mapping

from app.llm.base import LLMClient, LLMRole, StreamDelta, StructuredResult
from app.llm.registry import ROLES


class LaneRoutedLLMClient:
    """Implements app.llm.base.LLMClient and app.llm.base.StreamingLLMClient."""

    def __init__(self, by_lane: Mapping[str, LLMClient], fallback: LLMClient) -> None:
        self._by_lane = dict(by_lane)
        self._fallback = fallback

    def _client(self, role: LLMRole) -> LLMClient:
        return self._by_lane.get(ROLES[role].lane, self._fallback)

    @property
    def provider(self) -> str:
        """The configured provider, for messages that have no role in hand.

        Ledger rows must not use this -- see `provider_for`, which the gateway
        prefers precisely so a fallen-back lane is recorded as what served it.
        """
        served = {client.provider for client in self._by_lane.values()}
        return sorted(served)[0] if served else self._fallback.provider

    def provider_for(self, role: LLMRole) -> str:
        return self._client(role).provider

    def model_for(self, role: LLMRole) -> str:
        return self._client(role).model_for(role)

    def lanes(self) -> dict[str, str]:
        """Which provider serves each lane. Read by the health surface."""
        from app.llm.registry import LANES

        return {lane: self._by_lane.get(lane, self._fallback).provider for lane in LANES}

    async def structured(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        *,
        course_id: str | None = None,
    ) -> StructuredResult:
        return await self._client(role).structured(role, variables, course_id=course_id)

    def stream_text(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        *,
        course_id: str | None = None,
    ) -> AsyncIterator[StreamDelta]:
        client = self._client(role)
        streamer = getattr(client, "stream_text", None)
        if streamer is None:
            raise AttributeError(f"{client.provider} cannot stream")
        return streamer(role, variables, course_id=course_id)
