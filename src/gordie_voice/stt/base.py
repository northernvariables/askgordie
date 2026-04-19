"""Abstract base for speech-to-text providers."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gordie_voice.config import Settings


class STTProvider(abc.ABC):
    @abc.abstractmethod
    def transcribe(self, audio: bytes) -> str:
        """Transcribe raw audio bytes (16kHz, 16-bit, mono) to text."""


def create_stt_provider(settings: Settings) -> STTProvider:
    provider = settings.stt.provider
    if provider == "deepgram":
        from gordie_voice.stt.deepgram import DeepgramSTT
        return DeepgramSTT(settings)
    elif provider == "whisper_api":
        from gordie_voice.stt.whisper_api import WhisperAPISTT
        return WhisperAPISTT(settings)
    elif provider == "whisper_cpp":
        from gordie_voice.stt.whisper_cpp import WhisperCppSTT
        return WhisperCppSTT(settings)
    elif provider == "faster_whisper":
        from gordie_voice.stt.faster_whisper import FasterWhisperSTT
        return FasterWhisperSTT(settings)
    raise ValueError(f"Unknown STT provider: {provider}")
