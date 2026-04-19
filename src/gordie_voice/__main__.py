"""Entry point: python -m gordie_voice"""

from __future__ import annotations

import sys
from pathlib import Path

import structlog

from gordie_voice.audio.capture import AudioCapture
from gordie_voice.audio.playback import AudioPlayback
from gordie_voice.audio.vad import VADDetector
from gordie_voice.canadagpt.client import CanadaGPTClient
from gordie_voice.canadagpt.shaper import ResponseShaper
from gordie_voice.config import load_settings
from gordie_voice.display.persona import PersonaServer
from gordie_voice.registration.manager import RegistrationManager
from gordie_voice.stt.base import create_stt_provider
from gordie_voice.tts.base import create_tts_provider
from gordie_voice.util.logging import setup_logging
from gordie_voice.util.metrics import MetricsTracker
from gordie_voice.vision.presence import PresenceDetector
from gordie_voice.wake.base import create_wake_detector


def main() -> None:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    settings = load_settings(config_path)

    setup_logging(settings.log_level)
    log = structlog.get_logger()
    log.info("gordie_boot", version="0.1.0")

    metrics = MetricsTracker()

    capture = AudioCapture(settings.audio)
    playback = AudioPlayback(settings.audio)
    vad = VADDetector(settings.vad)
    wake = create_wake_detector(settings)
    stt = create_stt_provider(settings)
    tts = create_tts_provider(settings)
    client = CanadaGPTClient(settings)
    shaper = ResponseShaper(settings.shaper)

    presence = PresenceDetector(settings.vision) if settings.vision.enabled else None
    persona = PersonaServer(settings.display) if settings.display.enabled else None
    registration = RegistrationManager(settings) if settings.registration.enabled else None

    # Opinion recorder + uploader
    recorder = None
    uploader = None
    if settings.vision.enabled:
        from gordie_voice.recording.recorder import OpinionRecorder
        recorder = OpinionRecorder(settings.vision, settings.recording)
        if persona:
            persona.set_recorder(recorder)

    if settings.supabase_url and settings.supabase_service_role_key:
        from gordie_voice.opinions.uploader import OpinionUploader
        uploader = OpinionUploader(settings, stt=stt)
        if persona:
            persona.set_uploader(uploader)

    # Device registry — activation, heartbeat, config sync, riding
    from gordie_voice.device.registry import DeviceRegistry
    device_registry = DeviceRegistry(settings)
    device_registry.start()

    if not device_registry.is_activated:
        log.info(
            "device_pending_activation",
            activation_code=device_registry.activation_code,
            message="Enter this code in the CanadaGPT admin panel to activate this device",
        )

    from gordie_voice.app import GordieApp

    app = GordieApp(
        settings=settings,
        capture=capture,
        playback=playback,
        vad=vad,
        wake=wake,
        stt=stt,
        tts=tts,
        client=client,
        shaper=shaper,
        metrics=metrics,
        presence=presence,
        persona=persona,
        registration=registration,
    )

    # Payment manager — loads per-device config from Supabase
    payment_manager = None
    if settings.supabase_url and settings.supabase_service_role_key:
        from gordie_voice.payments.manager import PaymentManager
        payment_manager = PaymentManager(settings)
        payment_manager.load_config()
        if persona:
            persona.set_payments(payment_manager)

    # Queue manager
    queue_manager = None
    if settings.supabase_url and settings.supabase_service_role_key:
        from gordie_voice.queue.manager import QueueManager
        queue_manager = QueueManager(settings)
        if persona:
            persona.set_queue(queue_manager)

    # Fact-checker
    fact_checker = None
    if settings.recording.fact_check_enabled and settings.canadagpt_api_key:
        from gordie_voice.factcheck.checker import FactChecker
        fact_checker = FactChecker(settings)
        if persona:
            persona.set_fact_checker(fact_checker, stt)

    if persona:
        persona.set_app(app)
        persona.set_device_registry(device_registry)

    app.run()


if __name__ == "__main__":
    main()
