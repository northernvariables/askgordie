"""Tests for the Gordie state machine transitions."""

from unittest.mock import MagicMock, patch

import numpy as np

from gordie_voice.app import GordieApp, InteractionMode, State
from gordie_voice.config import load_settings


def make_app(**overrides):
    """Create a GordieApp with all dependencies mocked."""
    settings = load_settings()
    defaults = dict(
        settings=settings,
        capture=MagicMock(),
        playback=MagicMock(),
        vad=MagicMock(),
        wake=MagicMock(),
        stt=MagicMock(),
        tts=MagicMock(),
        client=MagicMock(),
        shaper=MagicMock(),
        metrics=MagicMock(),
    )
    defaults.update(overrides)
    return GordieApp(**defaults)


class TestStateTransitions:
    def test_initial_state_is_idle(self):
        app = make_app()
        assert app.state == State.IDLE

    def test_initial_mode_is_voice(self):
        app = make_app()
        assert app.mode == InteractionMode.VOICE

    def test_wake_detection_transitions_to_listening(self):
        wake = MagicMock()
        wake.detect.return_value = True
        capture = MagicMock()
        capture.read.return_value = np.zeros(480, dtype=np.int16)

        app = make_app(wake=wake, capture=capture)
        app._voice_loop_tick()
        assert app.state == State.LISTENING

    def test_no_wake_stays_idle(self):
        wake = MagicMock()
        wake.detect.return_value = False
        capture = MagicMock()
        capture.read.return_value = np.zeros(480, dtype=np.int16)

        app = make_app(wake=wake, capture=capture)
        app._voice_loop_tick()
        assert app.state == State.IDLE

    def test_presence_switches_to_prompt_mode(self):
        presence = MagicMock()
        presence.is_present.return_value = False

        app = make_app(presence=presence)
        app._check_presence()
        assert app.mode == InteractionMode.PROMPT

    def test_presence_returns_to_voice_mode(self):
        presence = MagicMock()
        presence.is_present.return_value = True

        app = make_app(presence=presence)
        app._mode = InteractionMode.PROMPT
        app._check_presence()
        assert app.mode == InteractionMode.VOICE

    def test_no_presence_detector_stays_voice(self):
        app = make_app()
        app._check_presence()
        assert app.mode == InteractionMode.VOICE


class TestTranscribeAndRespond:
    def test_successful_pipeline(self):
        stt = MagicMock()
        stt.transcribe.return_value = "Who is the PM?"

        client = MagicMock()
        client.query.return_value = "Mark Carney is the current Prime Minister."

        shaper = MagicMock()
        shaper.shape.return_value = ["Mark Carney is the current Prime Minister."]

        tts = MagicMock()
        tts.synthesize.return_value = b"\x00" * 100

        playback = MagicMock()
        metrics = MagicMock()

        settings = load_settings()
        settings.canadagpt.streaming = False

        app = make_app(
            settings=settings, stt=stt, client=client, shaper=shaper,
            tts=tts, playback=playback, metrics=metrics,
        )
        app._transcribe_and_respond(b"\x00" * 1000)

        stt.transcribe.assert_called_once()
        client.query.assert_called_once_with("Who is the PM?")
        shaper.shape.assert_called_once()
        # TTS called twice: once for response, once for follow-up prompt
        assert tts.synthesize.call_count == 2
        assert playback.play.call_count == 2
        # Ends in LISTENING (waiting for follow-up response)
        assert app.state == State.LISTENING

    def test_empty_transcription_returns_to_idle(self):
        stt = MagicMock()
        stt.transcribe.return_value = "  "

        app = make_app(stt=stt)
        app._transcribe_and_respond(b"\x00" * 100)
        assert app.state == State.IDLE

    def test_error_speaks_error_message(self):
        stt = MagicMock()
        stt.transcribe.side_effect = RuntimeError("Network down")

        tts = MagicMock()
        tts.synthesize.return_value = b"\x00" * 100
        playback = MagicMock()

        app = make_app(stt=stt, tts=tts, playback=playback)
        app._transcribe_and_respond(b"\x00" * 100)

        assert app.state == State.ERROR
        tts.synthesize.assert_called_once()
        assert "couldn't reach" in tts.synthesize.call_args[0][0].lower()
