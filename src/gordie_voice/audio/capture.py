"""Microphone audio capture using sounddevice.

Handles device quirks automatically:
- Stereo-only devices (e.g., C922 webcam) → downmixed to mono
- Mismatched sample rates (e.g., 8kHz Bluetooth HFP) → resampled to target rate
"""

from __future__ import annotations

import queue
from typing import TYPE_CHECKING

import numpy as np
import sounddevice as sd
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import AudioConfig

log = structlog.get_logger()


def _resample_linear(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Simple linear interpolation resampler (no scipy dependency)."""
    if src_rate == dst_rate:
        return audio
    ratio = dst_rate / src_rate
    n_out = int(len(audio) * ratio)
    indices = np.arange(n_out) / ratio
    indices = np.clip(indices, 0, len(audio) - 1)
    idx_floor = indices.astype(np.int64)
    idx_ceil = np.minimum(idx_floor + 1, len(audio) - 1)
    frac = (indices - idx_floor).astype(audio.dtype)
    return audio[idx_floor] + frac * (audio[idx_ceil] - audio[idx_floor])


class AudioCapture:
    """Continuously captures audio from the mic into a thread-safe queue.

    Automatically detects the device's native sample rate and channel count,
    then normalizes output to mono int16 at the configured target sample rate.
    """

    def __init__(self, config: AudioConfig) -> None:
        self.config = config
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=100)
        self._stream: sd.InputStream | None = None
        self._device_rate: int = config.sample_rate
        self._device_channels: int = config.channels
        self._needs_resample = False
        self._needs_downmix = False

    def _detect_device_caps(self) -> None:
        """Query the actual device capabilities and set up conversion flags."""
        device = self.config.input_device
        try:
            info = sd.query_devices(device, "input")
        except Exception:
            log.warning("device_query_failed", device=device)
            return

        native_rate = int(info["default_samplerate"])
        max_channels = int(info["max_input_channels"])

        # Determine channels: use mono if device supports it, otherwise use device native
        if max_channels < self.config.channels:
            log.warning("device_channels_limited", requested=self.config.channels, available=max_channels)
            self._device_channels = max_channels
        elif self.config.channels == 1 and max_channels >= 1:
            # Try mono first — if it fails, start() will retry with stereo
            self._device_channels = 1
        else:
            self._device_channels = self.config.channels

        self._needs_downmix = self._device_channels > 1

        # Check if we need to resample
        # Try the target rate first; if the device doesn't support it, use native
        try:
            sd.check_input_settings(
                device=device,
                samplerate=self.config.sample_rate,
                channels=self._device_channels,
                dtype="int16",
            )
            self._device_rate = self.config.sample_rate
        except sd.PortAudioError:
            self._device_rate = native_rate
            self._needs_resample = True
            log.info(
                "device_rate_mismatch",
                target=self.config.sample_rate,
                native=native_rate,
            )

        log.info(
            "device_caps_detected",
            device=info.get("name", device),
            native_rate=native_rate,
            capture_rate=self._device_rate,
            channels=self._device_channels,
            needs_resample=self._needs_resample,
            needs_downmix=self._needs_downmix,
        )

    def _callback(self, indata: np.ndarray, frames: int, time_info: object, status: sd.CallbackFlags) -> None:
        if status:
            log.warning("audio_capture_status", status=str(status))

        audio = indata.copy()

        # Downmix stereo to mono by averaging channels
        if self._needs_downmix and audio.ndim == 2 and audio.shape[1] > 1:
            audio = audio.mean(axis=1).astype(np.int16).reshape(-1, 1)

        # Resample to target rate
        if self._needs_resample:
            mono = audio.flatten()
            resampled = _resample_linear(mono.astype(np.float32), self._device_rate, self.config.sample_rate)
            audio = resampled.astype(np.int16).reshape(-1, 1)

        self._queue.put(audio)

    def start(self) -> None:
        self._detect_device_caps()

        block_size = int(self._device_rate * self.config.buffer_size_ms / 1000)

        try:
            self._stream = sd.InputStream(
                samplerate=self._device_rate,
                channels=self._device_channels,
                dtype="int16",
                blocksize=block_size,
                device=self.config.input_device,
                callback=self._callback,
            )
            self._stream.start()
        except sd.PortAudioError as e:
            # Mono failed — retry with stereo
            if self._device_channels == 1:
                log.warning("mono_capture_failed_retrying_stereo", error=str(e))
                self._device_channels = 2
                self._needs_downmix = True
                block_size = int(self._device_rate * self.config.buffer_size_ms / 1000)
                self._stream = sd.InputStream(
                    samplerate=self._device_rate,
                    channels=2,
                    dtype="int16",
                    blocksize=block_size,
                    device=self.config.input_device,
                    callback=self._callback,
                )
                self._stream.start()
            else:
                raise

        log.info(
            "audio_capture_started",
            sample_rate=self._device_rate,
            target_rate=self.config.sample_rate,
            channels=self._device_channels,
            device=self.config.input_device,
            resample=self._needs_resample,
            downmix=self._needs_downmix,
        )

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
