"""Coral Edge TPU wake word detection (v2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import WakeConfig

from gordie_voice.wake.base import WakeWordDetector

log = structlog.get_logger()


class CoralWakeDetector(WakeWordDetector):
    def __init__(self, config: WakeConfig) -> None:
        if not config.model_path:
            raise ValueError("Coral wake detector requires model_path to a .tflite model")

        from pycoral.utils.edgetpu import make_interpreter

        self.threshold = config.threshold
        self._interpreter = make_interpreter(config.model_path)
        self._interpreter.allocate_tensors()
        self._input_details = self._interpreter.get_input_details()
        self._output_details = self._interpreter.get_output_details()
        log.info("coral_wake_loaded", model=config.model_path)

    def detect(self, frames: np.ndarray) -> bool:
        audio_float = frames.astype(np.float32) / 32768.0
        input_shape = self._input_details[0]["shape"]
        audio_reshaped = np.resize(audio_float, input_shape)

        self._interpreter.set_tensor(self._input_details[0]["index"], audio_reshaped)
        self._interpreter.invoke()
        output = self._interpreter.get_tensor(self._output_details[0]["index"])

        score = float(output[0][0])
        if score >= self.threshold:
            log.debug("coral_wake_score", score=score)
            return True
        return False

    def reset(self) -> None:
        pass
