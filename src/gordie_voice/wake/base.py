"""Abstract base for wake-word detectors."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from gordie_voice.config import Settings


class WakeWordDetector(abc.ABC):
    @abc.abstractmethod
    def detect(self, frames: np.ndarray) -> bool:
        """Return True if wake word detected in the given audio frames."""

    @abc.abstractmethod
    def reset(self) -> None:
        """Reset internal state."""


def create_wake_detector(settings: Settings) -> WakeWordDetector:
    provider = settings.wake.provider
    if provider == "openwakeword":
        from gordie_voice.wake.openwakeword import OpenWakeWordDetector
        return OpenWakeWordDetector(settings.wake)
    elif provider == "coral":
        from gordie_voice.wake.coral import CoralWakeDetector
        return CoralWakeDetector(settings.wake)
    raise ValueError(f"Unknown wake provider: {provider}")
