"""Deepgram Nova-3 STT provider."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from gordie_voice.config import Settings

from gordie_voice.stt.base import STTProvider

log = structlog.get_logger()


class DeepgramSTT(STTProvider):
    def __init__(self, settings: Settings) -> None:
        from deepgram import DeepgramClient

        self._client = DeepgramClient(settings.deepgram_api_key)
        self._model = settings.stt.model
        log.info("deepgram_stt_ready", model=self._model)

    def transcribe(self, audio: bytes) -> str:
        from deepgram import PrerecordedOptions

        options = PrerecordedOptions(
            model=self._model,
            language="en",
            smart_format=True,
        )

        source = {"buffer": audio, "mimetype": "audio/raw;encoding=linear16;sample_rate=16000;channels=1"}
        response = self._client.listen.rest.v("1").transcribe_file(source, options)

        transcript = response.results.channels[0].alternatives[0].transcript
        log.info("deepgram_transcribed", length=len(transcript))
        return transcript
