"""openWakeWord-based wake word detection (v1, CPU)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import WakeConfig

from gordie_voice.wake.base import WakeWordDetector

log = structlog.get_logger()


class OpenWakeWordDetector(WakeWordDetector):
    def __init__(self, config: WakeConfig) -> None:
        import openwakeword
        from openwakeword.model import Model

        # Only download if models aren't already cached
        try:
            openwakeword.utils.download_models()
        except Exception:
            log.warning("openwakeword_download_failed_using_cached")
        self.threshold = config.threshold
        self._model = Model(
            wakeword_models=config.model_path.split(",") if config.model_path else None,
        )
        log.info("openwakeword_loaded", threshold=self.threshold)

    def detect(self, frames: np.ndarray) -> bool:
        audio_int16 = frames.flatten()
        prediction = self._model.predict(audio_int16)
        for model_name, score in prediction.items():
            if score >= self.threshold:
                log.debug("wake_score", model=model_name, score=score)
                self.reset()
                return True
        return False

    def reset(self) -> None:
        self._model.reset()
