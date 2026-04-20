"""Abstract base for text-to-speech providers."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gordie_voice.config import Settings


class TTSProvider(abc.ABC):
    @abc.abstractmethod
    def synthesize(self, text: str) -> bytes:
        """Convert text to raw audio bytes (16kHz, 16-bit, mono)."""


def create_tts_provider(settings: Settings) -> TTSProvider:
    provider = settings.tts.provider
    if provider == "elevenlabs":
        from gordie_voice.tts.elevenlabs import ElevenLabsTTS
        return ElevenLabsTTS(settings)
    elif provider == "piper":
        from gordie_voice.tts.piper import PiperTTS
        return PiperTTS(settings)
    elif provider == "google_cloud":
        from gordie_voice.tts.google_cloud import GoogleCloudTTS
        return GoogleCloudTTS(settings)
    elif provider == "resemble":
        from gordie_voice.tts.resemble import ResembleAITTS
        return ResembleAITTS(settings)
    elif provider == "espeak":
        from gordie_voice.tts.espeak import ESpeakTTS
        return ESpeakTTS()
    raise ValueError(f"Unknown TTS provider: {provider}")
