"""Audio playback via sounddevice."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import numpy as np
import sounddevice as sd
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import AudioConfig

log = structlog.get_logger()


class AudioPlayback:
    """Plays audio data through the configured output device."""

    def __init__(self, config: AudioConfig) -> None:
        self.config = config
        self._stop_event = threading.Event()

    def play(self, audio_data: bytes | np.ndarray, sample_rate: int | None = None) -> None:
        """Play audio synchronously. Respects stop() for barge-in."""
        self._stop_event.clear()
        sr = sample_rate or self.config.sample_rate

        if isinstance(audio_data, bytes):
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
        else:
            audio_array = audio_data

        try:
            sd.play(audio_array, samplerate=sr, device=self.config.output_device)
            # Poll for completion so we can honor barge-in
            stream = sd.get_stream()
            while stream and stream.active:
                if self._stop_event.is_set():
                    sd.stop()
                    log.info("playback_interrupted")
                    return
                sd.sleep(50)
        except Exception:
            log.exception("playback_error")

    def play_background(self, audio_data: bytes | np.ndarray, sample_rate: int | None = None) -> None:
        """Play audio in a background thread. Call stop() to interrupt."""
        self._stop_event.clear()
        t = threading.Thread(target=self.play, args=(audio_data, sample_rate), daemon=True)
        t.start()

    def stop(self) -> None:
        """Signal to stop current playback (barge-in support)."""
        self._stop_event.set()
        sd.stop()
