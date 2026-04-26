"""Voice Activity Detection using Silero VAD."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import VADConfig

log = structlog.get_logger()


@dataclass
class VADResult:
    is_complete: bool = False
    audio: bytes = b""


class VADDetector:
    """Wraps Silero VAD to detect end-of-speech in a streaming fashion."""

    def __init__(self, config: VADConfig) -> None:
        self.config = config
        self._model = None
        self._audio_buffer: list[np.ndarray] = []
        self._speech_detected = False
        self._last_speech_time: float = 0.0
        self._start_time: float = 0.0
        self._load_model()

    def _load_model(self) -> None:
        import torch
        self._model, self._utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
        log.info("vad_model_loaded")

    def reset(self) -> None:
        self._audio_buffer.clear()
        self._speech_started = False  # True once VAD detects actual speech
        self._start_time = time.monotonic()
        self._last_speech_time: float = 0.0  # 0 = no speech detected yet
        self._vad_buffer = np.array([], dtype=np.float32)
        if self._model:
            self._model.reset_states()

    def process(self, frames: np.ndarray) -> VADResult:
        """Feed audio frames. Returns VADResult with is_complete=True when utterance ends."""
        import torch

        self._audio_buffer.append(frames)

        # Convert to float32 tensor for Silero
        audio_float = frames.astype(np.float32) / 32768.0

        # Silero VAD requires exactly 512 samples at 16kHz
        # Buffer and process in 512-sample chunks
        if not hasattr(self, '_vad_buffer'):
            self._vad_buffer = np.array([], dtype=np.float32)

        self._vad_buffer = np.concatenate([self._vad_buffer, audio_float.flatten()])
        confidence = 0.0

        while len(self._vad_buffer) >= 512:
            chunk = self._vad_buffer[:512]
            self._vad_buffer = self._vad_buffer[512:]
            chunk_tensor = torch.from_numpy(chunk)
            confidence = max(confidence, self._model(chunk_tensor, 16000).item())
        now = time.monotonic()

        if confidence > 0.5:
            if not self._speech_started:
                self._speech_started = True
                log.debug("vad_speech_started")
            self._last_speech_time = now

        elapsed = now - self._start_time

        # Only check for silence AFTER we've heard actual speech
        if self._speech_started and self._last_speech_time > 0:
            silence_duration = (now - self._last_speech_time) * 1000
            if silence_duration >= self.config.min_silence_ms:
                return self._finalize()

        # No speech timeout — if nobody speaks within 5s of listening, give up
        if not self._speech_started and elapsed >= 5.0:
            log.info("vad_no_speech_timeout", elapsed_s=round(elapsed, 1))
            self.reset()
            return VADResult(is_complete=True, audio=b"")

        # Max duration safety valve (even if no speech detected)
        if elapsed >= self.config.max_utterance_s:
            log.info("vad_max_duration_reached", duration_s=elapsed)
            return self._finalize()

        return VADResult(is_complete=False)

    def _finalize(self) -> VADResult:
        audio = np.concatenate(self._audio_buffer)
        audio_bytes = audio.tobytes()
        self.reset()
        return VADResult(is_complete=True, audio=audio_bytes)
