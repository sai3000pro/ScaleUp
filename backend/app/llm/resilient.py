"""The deterministic provider as the floor under a credentialed one.

Every seam in this product has a working fallback, and the language model was the
one that did not. A role reached its provider, and if that provider was having a
bad minute the caller got an exception -- which, at the top of a request, is a
learner watching a drill fail to issue rather than reading a slightly plainer
question.

So a provider outage costs answer *quality* here, never the feature. The drill
still issues, the take is still graded, the examiner still speaks; they are served
by the deterministic provider, which is a real implementation held to the same
schemas and the same tests as the credentialed ones, not a stub.

Two boundaries stop this from becoming the silent downgrade `factory` otherwise
refuses:

* it is a **runtime** answer to an outage, never a **startup** answer to a missing
  credential. An unimplemented provider name and an absent key still refuse, because
  those are configuration mistakes a fallback would hide for as long as the
  deployment lived;
* it is **recorded**. `StructuredResult` carries the provider that produced it, and
  `services.llm_gateway` writes that provider to the ledger -- so "how much of last
  week ran on the word matcher?" is a query rather than a guess.

A schema failure and a refusal are deliberately *not* caught. Those are the model
answering, and answering badly; sending them to the floor would replace a defect
worth seeing with a shrug.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Mapping

from app.llm.base import LLMClient, LLMRole, ProviderError, StreamDelta, StructuredResult


class FloorFallbackLLMClient:
    """Implements app.llm.base.LLMClient and app.llm.base.StreamingLLMClient."""

    def __init__(self, primary: LLMClient, floor: LLMClient) -> None:
        self._primary = primary
        self._floor = floor

    @property
    def provider(self) -> str:
        """What is configured, not what served any particular call.

        Ledger rows must not read this -- they read the provider off the result,
        which is how a degraded call is recorded as degraded.
        """
        return self._primary.provider

    def provider_for(self, role: LLMRole) -> str:
        inner = getattr(self._primary, "provider_for", None)
        return inner(role) if inner else self._primary.provider

    def model_for(self, role: LLMRole) -> str:
        return self._primary.model_for(role)

    def lanes(self) -> dict[str, str]:
        """Which provider serves each lane, for the health surface.

        Answered on the primary's behalf when it is not itself lane-routed, so
        that wrapping a client does not turn a populated lane report into an
        empty one -- the report exists to show a demo which lanes are running on
        the deterministic floor, and an empty one shows nothing at all.
        """
        from app.llm.registry import LANES

        inner = getattr(self._primary, "lanes", None)
        return inner() if inner is not None else {lane: self._primary.provider for lane in LANES}

    # @spec LLM-PROV-012, LLM-PROV-013
    async def structured(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        *,
        course_id: str | None = None,
    ) -> StructuredResult:
        try:
            return await self._primary.structured(role, variables, course_id=course_id)
        except ProviderError:
            return await self._floor.structured(role, variables, course_id=course_id)

    def stream_text(
        self,
        role: LLMRole,
        variables: Mapping[str, Any],
        *,
        course_id: str | None = None,
    ) -> AsyncIterator[StreamDelta]:
        """Delegated unwrapped, because the coach already has a floor of its own.

        A cue that fails mid-stream is answered by the deterministic sentence in
        `domain.coach_policy`, which is a better answer than a second model's
        opening words arriving seconds after the learner started playing again.
        """
        streamer = getattr(self._primary, "stream_text", None)
        if streamer is None:
            raise ProviderError(f"{self._primary.provider} cannot stream")
        return streamer(role, variables, course_id=course_id)
