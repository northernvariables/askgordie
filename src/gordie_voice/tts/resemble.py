"""Resemble AI TTS provider — Canadian voice cloning platform.

Uses the Resemble AI API for high-quality voice synthesis with
custom voice clones (historical figures from CBC Archives audio).

Supports both synchronous and streaming synthesis.
"""

from __future__ import annotations

import base64
import io
import wave
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import Settings

from gordie_voice.tts.base import TTSProvider

log = structlog.get_logger()

SYNC_ENDPOINT = "https://f.cluster.resemble.ai/synthesize"
STREAM_ENDPOINT = "https://f.cluster.resemble.ai/stream"


class ResembleAITTS(TTSProvider):
    """Resemble AI text-to-speech with custom voice clones."""

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.resemble_api_key
        self._voice_uuid = settings.tts.model  # voice_uuid stored in tts.model field
        self._client = httpx.Client(
            timeout=15.0,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        log.info("resemble_ai_tts_ready", voice_uuid=self._voice_uuid)

    def synthesize(self, text: str) -> bytes:
        response = self._client.post(
            SYNC_ENDPOINT,
            json={
                "voice_uuid": self._voice_uuid,
                "data": text,
                "precision": "PCM_16",
                "output_format": "wav",
                "sample_rate": 16000,
            },
        )

        if response.status_code != 200:
            error = response.json().get("message", response.text)
            log.error("resemble_tts_error", status=response.status_code, error=error)
            raise RuntimeError(f"Resemble AI TTS failed: {error}")

        data = response.json()
        audio_b64 = data["audio_content"]
        audio_bytes = base64.b64decode(audio_b64)

        # Extract raw PCM from WAV
        wav_buf = io.BytesIO(audio_bytes)
        with wave.open(wav_buf, "rb") as wf:
            pcm_data = wf.readframes(wf.getnframes())

        log.debug(
            "resemble_tts_synthesized",
            text_len=len(text),
            audio_bytes=len(pcm_data),
            duration_s=data.get("duration", 0),
        )
        return pcm_data
