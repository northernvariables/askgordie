"""Piper local TTS provider (v2 sovereignty)."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from gordie_voice.config import Settings

from gordie_voice.tts.base import TTSProvider

log = structlog.get_logger()


class PiperTTS(TTSProvider):
    def __init__(self, settings: Settings) -> None:
        self._model = settings.tts.model
        log.info("piper_tts_ready", model=self._model)

    def synthesize(self, text: str) -> bytes:
        result = subprocess.run(
            [
                "piper",
                "--model", self._model,
                "--output-raw",
            ],
            input=text.encode(),
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.error("piper_error", stderr=result.stderr.decode())
            raise RuntimeError(f"Piper TTS failed: {result.stderr.decode()}")

        log.debug("piper_synthesized", text_len=len(text), audio_bytes=len(result.stdout))
        return result.stdout
