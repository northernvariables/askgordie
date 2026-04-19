"""Local faster-whisper STT provider (v2 sovereignty).

Uses CTranslate2 backend — proper ARM64 support, Python-native.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import Settings

from gordie_voice.stt.base import STTProvider

log = structlog.get_logger()


class FasterWhisperSTT(STTProvider):
    def __init__(self, settings: Settings) -> None:
        from faster_whisper import WhisperModel

        model_size = settings.stt.model or "small.en"
        self._model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",  # Fastest on ARM64
        )
        log.info("faster_whisper_loaded", model=model_size)

    def transcribe(self, audio: bytes) -> str:
        audio_np = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        segments, info = self._model.transcribe(audio_np, language="en", beam_size=1)
        transcript = " ".join(segment.text for segment in segments).strip()
        log.info("faster_whisper_transcribed", length=len(transcript))
        return transcript
