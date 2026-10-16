"""ElevenLabs, against the real endpoint, through the same seams a take uses.

`synthesize_feedback` and `stream_feedback` never raise -- a failed synthesis
degrades to text so the take survives -- which is exactly why a dead key or a
retired model is invisible everywhere except here: the learner simply stops
hearing the coach. Both seams are asserted to return audio, not merely to
return.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.services.voice import stream_feedback, streaming_audio_format, synthesize_feedback

MP3_FRAME_SYNC = 0xFF
ID3_MAGIC = b"ID3"


def _looks_like_mp3(content: bytes) -> bool:
    return content.startswith(ID3_MAGIC) or (len(content) > 1 and content[0] == MP3_FRAME_SYNC)


# @spec COACH-VOICE-010, COACH-VOICE-005
async def test_synthesis_returns_mp3_from_the_selected_provider(elevenlabs_settings) -> None:
    artifact = await synthesize_feedback("Sit back on the beat through the second half.")
    assert artifact.provider == "elevenlabs", "synthesis fell through to the floor; the key or model is dead"
    assert artifact.format == "mp3"
    assert len(artifact.content) > 1000
    assert _looks_like_mp3(artifact.content)


# @spec COACH-VOICE-010, COACH-VOICE-006, COACH-VOICE-007
async def test_streaming_synthesis_yields_audio_per_sentence(elevenlabs_settings) -> None:
    async def sentences() -> AsyncIterator[str]:
        yield "Lovely, that was even."
        yield "Now the left hand alone."

    chunks = [chunk async for chunk in stream_feedback(sentences())]
    assert chunks, "streamed synthesis produced nothing; the failure was logged and the take went silent"
    assert streaming_audio_format(elevenlabs_settings.voice_provider) == "mp3"
    assert _looks_like_mp3(b"".join(chunks))
