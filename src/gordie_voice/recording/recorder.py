"""Server-side video+audio opinion recorder.

Records from the Pi camera and USB mic simultaneously, muxes into a single
MP4 file using ffmpeg. Streams MJPEG preview frames to the browser via a
Flask endpoint while recording.

All recordings stay on-device in /opt/gordie-voice/recordings/.
"""

from __future__ import annotations

import io
import os
import subprocess
import threading
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import RecordingConfig, VisionConfig

log = structlog.get_logger()

RECORDINGS_DIR = Path(os.environ.get("GORDIE_ROOT", "/opt/gordie-voice")) / "recordings"
FRAME_RATE = 24
AUDIO_SAMPLE_RATE = 16000


class OpinionRecorder:
    """Manages camera preview streaming and opinion recording."""

    def __init__(self, vision_config: VisionConfig, recording_config: RecordingConfig | None = None) -> None:
        self._camera_index = vision_config.camera_index
        self._max_duration_s = recording_config.max_duration_s if recording_config else 30
        self._max_duration_registered_s = recording_config.max_duration_registered_s if recording_config else 60
        self._countdown_warning_s = recording_config.countdown_warning_s if recording_config else 10
        self._active_max_duration: int = self._max_duration_s
        self._cap: cv2.VideoCapture | None = None
        self._recording = False
        self._preview_active = False
        self._lock = threading.Lock()

        # Recording state
        self._record_thread: threading.Thread | None = None
        self._video_frames: list[np.ndarray] = []
        self._audio_chunks: list[np.ndarray] = []
        self._start_time: float = 0
        self._category_id: str = ""
        self._current_frame: bytes = b""  # Latest JPEG for MJPEG stream

        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    def start_preview(self) -> bool:
        """Open camera and start generating preview frames."""
        with self._lock:
            if self._preview_active:
                return True
            self._cap = cv2.VideoCapture(self._camera_index)
            if not self._cap.isOpened():
                log.error("recorder_camera_failed", index=self._camera_index)
                return False
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self._preview_active = True

        threading.Thread(target=self._preview_loop, daemon=True).start()
        log.info("preview_started")
        return True

    def stop_preview(self) -> None:
        """Stop camera preview (and recording if active)."""
        if self._recording:
            self.stop_recording()
        with self._lock:
            self._preview_active = False
            if self._cap:
                self._cap.release()
                self._cap = None
        log.info("preview_stopped")

    def get_frame_jpeg(self) -> bytes:
        """Get the latest camera frame as JPEG bytes for MJPEG streaming."""
        return self._current_frame

    def generate_mjpeg(self):
        """Generator yielding MJPEG frames for Flask streaming response."""
        while self._preview_active:
            frame = self._current_frame
            if frame:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            time.sleep(1.0 / FRAME_RATE)

    def set_duration_for_user(self, is_registered: bool) -> None:
        """Set recording duration based on whether user is registered."""
        self._active_max_duration = (
            self._max_duration_registered_s if is_registered else self._max_duration_s
        )

    def start_recording(self, category_id: str) -> bool:
        """Begin recording video+audio."""
        if self._recording:
            return False
        if not self._preview_active:
            if not self.start_preview():
                return False

        self._category_id = category_id
        self._video_frames.clear()
        self._audio_chunks.clear()
        self._recording = True
        self._start_time = time.monotonic()

        self._record_thread = threading.Thread(target=self._audio_capture_loop, daemon=True)
        self._record_thread.start()

        log.info("recording_started", category=category_id)
        return True

    def stop_recording(self) -> str | None:
        """Stop recording and mux video+audio to MP4. Returns file path."""
        if not self._recording:
            return None

        self._recording = False
        if self._record_thread:
            self._record_thread.join(timeout=3)

        elapsed = time.monotonic() - self._start_time
        log.info("recording_stopped", duration_s=round(elapsed, 1), frames=len(self._video_frames))

        if not self._video_frames:
            log.warning("no_frames_captured")
            return None

        return self._mux_to_file()

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def elapsed_seconds(self) -> float:
        if not self._recording:
            return 0
        return time.monotonic() - self._start_time

    @property
    def remaining_seconds(self) -> float:
        return max(0, self._active_max_duration - self.elapsed_seconds)

    def _preview_loop(self) -> None:
        """Continuously read frames for preview; also captures for recording."""
        while self._preview_active:
            with self._lock:
                if not self._cap:
                    break
                ret, frame = self._cap.read()

            if not ret:
                time.sleep(0.01)
                continue

            # Mirror the frame so user sees themselves naturally
            frame = cv2.flip(frame, 1)

            # If recording, add countdown overlay and save frame
            if self._recording:
                remaining = int(self.remaining_seconds)
                self._draw_recording_overlay(frame, remaining)
                self._video_frames.append(frame.copy())

                # Auto-stop at 60s
                if remaining <= 0:
                    threading.Thread(target=self.stop_recording, daemon=True).start()

            # Encode to JPEG for MJPEG stream
            _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            self._current_frame = jpeg.tobytes()

            time.sleep(1.0 / FRAME_RATE)

    def _draw_recording_overlay(self, frame: np.ndarray, remaining: int) -> None:
        """Draw recording indicator and countdown on the video frame."""
        h, w = frame.shape[:2]

        # Red recording dot
        cv2.circle(frame, (30, 30), 10, (0, 0, 255), -1)
        cv2.putText(frame, "REC", (48, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # Countdown timer
        mins, secs = divmod(remaining, 60)
        timer_text = f"{mins}:{secs:02d}"
        cv2.putText(frame, timer_text, (w - 120, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

        # Progress bar at bottom
        progress = 1.0 - (remaining / self._active_max_duration)
        bar_width = int(w * progress)
        cv2.rectangle(frame, (0, h - 6), (bar_width, h), (0, 0, 255), -1)

    def _audio_capture_loop(self) -> None:
        """Capture audio from the mic while recording."""
        import sounddevice as sd

        try:
            with sd.InputStream(samplerate=AUDIO_SAMPLE_RATE, channels=1, dtype="int16",
                                blocksize=int(AUDIO_SAMPLE_RATE * 0.05)) as stream:
                while self._recording:
                    data, _ = stream.read(int(AUDIO_SAMPLE_RATE * 0.05))
                    self._audio_chunks.append(data.copy())
        except Exception:
            log.exception("audio_capture_error_during_recording")

    def _mux_to_file(self) -> str:
        """Mux captured video frames and audio into an MP4 file using ffmpeg."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"opinion_{self._category_id}_{timestamp}"
        output_path = RECORDINGS_DIR / f"{filename}.mp4"
        temp_video = RECORDINGS_DIR / f"{filename}_video.avi"
        temp_audio = RECORDINGS_DIR / f"{filename}_audio.wav"

        try:
            # Write video frames to temp AVI
            h, w = self._video_frames[0].shape[:2]
            fourcc = cv2.VideoWriter.fourcc(*"MJPG")
            writer = cv2.VideoWriter(str(temp_video), fourcc, FRAME_RATE, (w, h))
            for frame in self._video_frames:
                writer.write(frame)
            writer.release()

            # Write audio to temp WAV
            audio_data = np.concatenate(self._audio_chunks) if self._audio_chunks else np.zeros(1600, dtype=np.int16)
            with wave.open(str(temp_audio), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(AUDIO_SAMPLE_RATE)
                wf.writeframes(audio_data.tobytes())

            # Mux with ffmpeg
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(temp_video),
                    "-i", str(temp_audio),
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "128k",
                    "-shortest",
                    str(output_path),
                ],
                capture_output=True,
                timeout=120,
            )

            log.info("recording_saved", path=str(output_path))
            return str(output_path)

        finally:
            # Clean up temp files
            temp_video.unlink(missing_ok=True)
            temp_audio.unlink(missing_ok=True)
            self._video_frames.clear()
            self._audio_chunks.clear()
