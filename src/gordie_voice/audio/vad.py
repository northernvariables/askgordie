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
        self._speech_detected = False
        self._start_time = time.monotonic()
        self._last_speech_time = self._start_time  # Prevent immediate silence trigger
        if self._model:
            self._model.reset_states()

    def process(self, frames: np.ndarray) -> VADResult:
        """Feed audio frames. Returns VADResult with is_complete=True when utterance ends."""
        import torch

        if not self._speech_detected:
            self._start_time = time.monotonic()
            self._speech_detected = True

        self._audio_buffer.append(frames)

        # Convert to float32 tensor for Silero
        audio_float = frames.astype(np.float32) / 32768.0
        tensor = torch.from_numpy(audio_float).squeeze()

        # Silero VAD needs at least 512 samples (32ms at 16kHz)
        if tensor.numel() < 512:
            return VADResult(is_complete=False)

        confidence = self._model(tensor, 16000).item()
        now = time.monotonic()

        if confidence > 0.5:
            self._last_speech_time = now

        elapsed = now - self._start_time
        silence_duration = (now - self._last_speech_time) * 1000 if self._last_speech_time > 0 else 0

        # End conditions: silence after speech, or max duration
        if self._last_speech_time > 0 and silence_duration >= self.config.min_silence_ms:
            return self._finalize()
        if elapsed >= self.config.max_utterance_s:
            log.info("vad_max_duration_reached", duration_s=elapsed)
            return self._finalize()

        return VADResult(is_complete=False)

    def _finalize(self) -> VADResult:
        audio = np.concatenate(self._audio_buffer)
        audio_bytes = audio.tobytes()
        self.reset()
        return VADResult(is_complete=True, audio=audio_bytes)
