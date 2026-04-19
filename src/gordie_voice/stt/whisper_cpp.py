"""Local whisper.cpp STT provider (v2 sovereignty)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import Settings

from gordie_voice.stt.base import STTProvider

log = structlog.get_logger()


class WhisperCppSTT(STTProvider):
    def __init__(self, settings: Settings) -> None:
        from whispercpp import Whisper

        model_path = settings.stt.model or "ggml-small.en-q5_1.bin"
        self._model = Whisper.from_pretrained(model_path)
        log.info("whisper_cpp_loaded", model=model_path)

    def transcribe(self, audio: bytes) -> str:
        audio_np = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        result = self._model.transcribe(audio_np)
        transcript = result.strip()
        log.info("whisper_cpp_transcribed", length=len(transcript))
        return transcript
