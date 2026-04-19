"""ElevenLabs streaming TTS provider (v1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from gordie_voice.config import Settings

from gordie_voice.tts.base import TTSProvider

log = structlog.get_logger()


class ElevenLabsTTS(TTSProvider):
    def __init__(self, settings: Settings) -> None:
        from elevenlabs import ElevenLabs

        self._client = ElevenLabs(api_key=settings.elevenlabs_api_key)
        self._voice_id = settings.elevenlabs_voice_id
        log.info("elevenlabs_tts_ready", voice_id=self._voice_id)

    def synthesize(self, text: str) -> bytes:
        audio_generator = self._client.text_to_speech.convert(
            voice_id=self._voice_id,
            text=text,
            model_id="eleven_turbo_v2_5",
            output_format="pcm_16000",
        )
        # Collect all chunks into a single bytes object
        audio_bytes = b"".join(audio_generator)
        log.debug("elevenlabs_synthesized", text_len=len(text), audio_bytes=len(audio_bytes))
        return audio_bytes
