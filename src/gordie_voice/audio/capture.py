"""Microphone audio capture using sounddevice."""

from __future__ import annotations

import queue
from typing import TYPE_CHECKING

import numpy as np
import sounddevice as sd
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import AudioConfig

log = structlog.get_logger()


class AudioCapture:
    """Continuously captures audio from the USB mic into a thread-safe queue."""

    def __init__(self, config: AudioConfig) -> None:
        self.config = config
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=100)
        self._stream: sd.InputStream | None = None

    def _callback(self, indata: np.ndarray, frames: int, time_info: object, status: sd.CallbackFlags) -> None:
        if status:
            log.warning("audio_capture_status", status=str(status))
        self._queue.put(indata.copy())

    def start(self) -> None:
        block_size = int(self.config.sample_rate * self.config.buffer_size_ms / 1000)
        self._stream = sd.InputStream(
            samplerate=self.config.sample_rate,
            channels=self.config.channels,
            dtype="int16",
            blocksize=block_size,
            device=self.config.input_device,
            callback=self._callback,
        )
        self._stream.start()
        log.info("audio_capture_started", sample_rate=self.config.sample_rate, device=self.config.input_device)

    def stop(self) -> None:
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            log.info("audio_capture_stopped")

    def read(self) -> np.ndarray | None:
        """Non-blocking read of the next audio frame. Returns None if empty."""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def read_blocking(self, timeout: float = 1.0) -> np.ndarray | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
