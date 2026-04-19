"""Face presence detection using MediaPipe — detects if a person is in front of the device."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import cv2
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import VisionConfig

log = structlog.get_logger()


class PresenceDetector:
    """Periodically checks the camera for face presence to switch interaction modes."""

    def __init__(self, config: VisionConfig) -> None:
        self.config = config
        self._present = False
        self._last_seen: float = 0.0
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._camera_released = threading.Event()
        self._camera_released.set()  # Not holding camera initially

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._detection_loop, daemon=True)
        self._thread.start()
        log.info("presence_detector_started", camera=self.config.camera_index)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self._camera_released.wait(timeout=3)
        log.info("presence_detector_stopped")

    def is_present(self) -> bool:
        with self._lock:
            if self._present:
                return True
            # Grace period: still "present" for a few seconds after last detection
            if time.monotonic() - self._last_seen < self.config.presence_timeout_s:
                return True
            return False

    def _detection_loop(self) -> None:
        import mediapipe as mp

        mp_face = mp.solutions.face_detection
        detector = mp_face.FaceDetection(
            min_detection_confidence=self.config.face_min_confidence,
            model_selection=0,  # 0 = short range (< 2m), ideal for kiosk
        )

        self._camera_released.clear()
        cap = cv2.VideoCapture(self.config.camera_index)
        if not cap.isOpened():
            log.error("camera_open_failed", index=self.config.camera_index)
            self._camera_released.set()
            return

        try:
            while self._running:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(self.config.check_interval_s)
                    continue

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = detector.process(rgb)
                face_found = bool(results.detections)

                with self._lock:
                    self._present = face_found
                    if face_found:
                        self._last_seen = time.monotonic()

                time.sleep(self.config.check_interval_s)
        finally:
            cap.release()
            detector.close()
            self._camera_released.set()
