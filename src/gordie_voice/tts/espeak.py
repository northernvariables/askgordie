"""espeak-ng fallback TTS for zero-dependency testing."""

from __future__ import annotations

import io
import subprocess
import wave

import numpy as np
import structlog

from gordie_voice.tts.base import TTSProvider

log = structlog.get_logger()


class ESpeakTTS(TTSProvider):
    def synthesize(self, text: str) -> bytes:
        result = subprocess.run(
            ["espeak-ng", "--stdout", "-s", "160", text],
            capture_output=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(f"espeak-ng failed: {result.stderr.decode()}")

        # espeak-ng --stdout produces WAV; extract raw PCM
        wav_buf = io.BytesIO(result.stdout)
        with wave.open(wav_buf, "rb") as wf:
            pcm_data = wf.readframes(wf.getnframes())

        log.debug("espeak_synthesized", text_len=len(text))
        return pcm_data
