"""OpenAI Whisper API STT provider (fallback)."""

from __future__ import annotations

import io
import wave
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import Settings

from gordie_voice.stt.base import STTProvider

log = structlog.get_logger()


class WhisperAPISTT(STTProvider):
    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.openai_api_key
        log.info("whisper_api_stt_ready")

    def transcribe(self, audio: bytes) -> str:
        # Wrap raw PCM in a WAV container for the API
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio)
        wav_buffer.seek(0)

        response = httpx.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            files={"file": ("audio.wav", wav_buffer, "audio/wav")},
            data={"model": "whisper-1", "language": "en"},
            timeout=30.0,
        )
        response.raise_for_status()
        transcript = response.json()["text"]
        log.info("whisper_api_transcribed", length=len(transcript))
        return transcript
