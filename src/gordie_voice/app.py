"""Main state machine loop for the Gordie Voice appliance."""

from __future__ import annotations

import enum
import threading
import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from gordie_voice.audio.capture import AudioCapture
    from gordie_voice.audio.playback import AudioPlayback
    from gordie_voice.audio.vad import VADDetector
    from gordie_voice.canadagpt.client import CanadaGPTClient
    from gordie_voice.canadagpt.shaper import ResponseShaper
    from gordie_voice.config import Settings
    from gordie_voice.display.persona import PersonaServer
    from gordie_voice.registration.manager import RegistrationManager
    from gordie_voice.stt.base import STTProvider
    from gordie_voice.tts.base import TTSProvider
    from gordie_voice.util.metrics import MetricsTracker
    from gordie_voice.vision.presence import PresenceDetector
    from gordie_voice.wake.base import WakeWordDetector

log = structlog.get_logger()


class State(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    QUERYING = "querying"
    SPEAKING = "speaking"
    FOLLOW_UP = "follow_up"   # After answering — waiting for follow-up or opinion recording
    REGISTERING = "registering"
    RECORDING = "recording"   # User is recording an opinion video
    ERROR = "error"


class InteractionMode(enum.Enum):
    VOICE = "voice"   # User is present — voice-only, no prompt input
    PROMPT = "prompt"  # No user present — accepts text input on display


class GordieApp:
    """Core application coordinating all subsystems via a state machine."""

    def __init__(
        self,
        settings: Settings,
        capture: AudioCapture,
        playback: AudioPlayback,
        vad: VADDetector,
        wake: WakeWordDetector,
        stt: STTProvider,
        tts: TTSProvider,
        client: CanadaGPTClient,
        shaper: ResponseShaper,
        metrics: MetricsTracker,
        presence: PresenceDetector | None = None,
        persona: PersonaServer | None = None,
        registration: RegistrationManager | None = None,
    ) -> None:
        self.settings = settings
        self.capture = capture
        self.playback = playback
        self.vad = vad
        self.wake = wake
        self.stt = stt
        self.tts = tts
        self.client = client
        self.shaper = shaper
        self.metrics = metrics
        self.presence = presence
        self.persona = persona
        self.registration = registration

        self._state = State.IDLE
        self._mode = InteractionMode.VOICE
        self._running = False
        self._barge_in = threading.Event()
        self._awaiting_follow_up = False  # True when LISTENING state is for follow-up intent
        self._pending_follow_up_query: str | None = None

    @property
    def state(self) -> State:
        return self._state

    @property
    def mode(self) -> InteractionMode:
        return self._mode

    def _set_state(self, new_state: State) -> None:
        old = self._state
        self._state = new_state
        log.info("state_transition", old=old.value, new=new_state.value)
        if self.persona:
            self.persona.broadcast_state(new_state.value, self._mode.value)

    def _set_mode(self, new_mode: InteractionMode) -> None:
        old = self._mode
        self._mode = new_mode
        log.info("mode_change", old=old.value, new=new_mode.value)
        if self.persona:
            self.persona.broadcast_state(self._state.value, new_mode.value)

    def run(self) -> None:
        """Main loop — runs until stopped."""
        import signal

        def _handle_signal(signum, frame):
            log.info("signal_received", signal=signum)
            self._running = False

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        self._running = True
        log.info("gordie_starting", mode=self._mode.value)

        if self.presence:
            self.presence.start()
        if self.persona:
            self.persona.start()

        self.capture.start()

        # Discard first 2 seconds of audio to avoid false wake triggers from mic init noise
        import time as _time
        _startup_discard_until = _time.monotonic() + 2.0

        try:
            while self._running:
                if _time.monotonic() < _startup_discard_until:
                    self.capture.read()  # Drain the buffer
                    _time.sleep(0.01)
                    continue
                self._check_presence()
                if self._mode == InteractionMode.VOICE:
                    self._voice_loop_tick()
                else:
                    # In prompt mode, the display handles text input via websocket
                    time.sleep(0.1)
        except KeyboardInterrupt:
            log.info("gordie_interrupted")
        finally:
            self.stop()

    def stop(self) -> None:
        self._running = False
        self.capture.stop()
        if self.presence:
            self.presence.stop()
        if self.persona:
            self.persona.stop()
        log.info("gordie_stopped")

    def _check_presence(self) -> None:
        """Switch modes based on whether a face is detected."""
        if not self.presence:
            return
        face_present = self.presence.is_present()
        if face_present and self._mode == InteractionMode.PROMPT:
            self._set_mode(InteractionMode.VOICE)
        elif not face_present and self._mode == InteractionMode.VOICE:
            if self._state == State.IDLE:
                self._set_mode(InteractionMode.PROMPT)

    def _voice_loop_tick(self) -> None:
        """Single tick of the voice interaction state machine."""
        if self._state == State.IDLE:
            self._awaiting_follow_up = False
            frames = self.capture.read()
            if frames is not None and self.wake.detect(frames):
                log.info("wake_detected")
                self.metrics.start_interaction()
                self.metrics.mark("wake_detection")
                self._barge_in.clear()
                self.vad.reset()
                self._set_state(State.LISTENING)

        elif self._state == State.LISTENING:
            frames = self.capture.read()
            if frames is None:
                return
            result = self.vad.process(frames)
            if result.is_complete:
                self.metrics.mark("vad_end_of_speech")
                # Stop capture during processing to prevent feedback loop
                self.capture.stop()
                self._set_state(State.TRANSCRIBING)
                self._transcribe_and_respond(result.audio, is_follow_up=self._awaiting_follow_up)
                # Resume capture after response
                self.capture.start()

        elif self._state == State.FOLLOW_UP:
            # This state is transient — _offer_follow_up speaks the prompt
            # then sets state to LISTENING with _awaiting_follow_up=True
            pass

        elif self._state == State.QUERYING and self._pending_follow_up_query:
            # Follow-up question queued — run it iteratively from main loop
            query = self._pending_follow_up_query
            self._pending_follow_up_query = None
            self._run_query_pipeline(query)

        elif self._state in (State.TRANSCRIBING, State.QUERYING, State.SPEAKING):
            # These states are driven by _transcribe_and_respond
            frames = self.capture.read()
            if frames is not None and self.wake.detect(frames):
                log.info("barge_in_detected")
                self.metrics.increment("barge_ins")
                self._barge_in.set()
                self.playback.stop()
                self._awaiting_follow_up = False
                self._set_state(State.LISTENING)

        elif self._state == State.RECORDING:
            # Recording is managed by the display/recorder — listen for "stop"
            frames = self.capture.read()
            if frames is not None:
                # Simple check: if wake word detected during recording, stop it
                if self.wake.detect(frames):
                    if self.persona:
                        self.persona.socketio.emit("opinion_stop_recording", {})
                    self._set_state(State.IDLE)

        elif self._state == State.ERROR:
            time.sleep(1)
            self._set_state(State.IDLE)

    def _transcribe_and_respond(self, audio: bytes, is_follow_up: bool = False) -> None:
        """Full pipeline: STT -> CanadaGPT -> shape -> TTS -> playback."""
        try:
            # STT
            self._set_state(State.TRANSCRIBING)
            transcript = self.stt.transcribe(audio)
            self.metrics.mark("stt_complete")
            log.info("transcription", text=transcript)

            if not transcript.strip():
                self._set_state(State.IDLE)
                return

            # If this came after a follow-up prompt, route through intent detection
            if is_follow_up:
                self._handle_follow_up_intent(transcript)
                return

            # Query CanadaGPT
            self._set_state(State.QUERYING)

            if self.settings.canadagpt.streaming:
                self._set_state(State.SPEAKING)
                for chunk in self.client.query_stream(transcript):
                    if self._barge_in.is_set():
                        return
                    shaped = self.shaper.shape(chunk)
                    for sentence in shaped:
                        if self._barge_in.is_set():
                            return
                        audio_data = self.tts.synthesize(sentence)
                        self.playback.play(audio_data)
            else:
                response = self.client.query(transcript)
                self.metrics.mark("canadagpt_complete")
                shaped_sentences = self.shaper.shape(response)

                self._set_state(State.SPEAKING)
                for sentence in shaped_sentences:
                    if self._barge_in.is_set():
                        return
                    audio_data = self.tts.synthesize(sentence)
                    self.playback.play(audio_data)

            self.metrics.mark("end_to_end")
            self._offer_follow_up()

        except Exception:
            log.exception("pipeline_error")
            self.metrics.increment("errors_by_stage")
            try:
                error_audio = self.tts.synthesize(
                    "I couldn't reach CanadaGPT. Please try again."
                )
                self.playback.play(error_audio)
            except Exception:
                log.exception("error_tts_failed")
            self._set_state(State.ERROR)

    def _offer_follow_up(self) -> None:
        """After answering, ask if the user wants a follow-up or to record an opinion."""
        self._set_state(State.FOLLOW_UP)
        try:
            prompt_audio = self.tts.synthesize(
                "Would you like to ask a follow-up question? "
                "You can also say 'record my opinion' if you'd like to share your thoughts."
            )
            self.playback.play(prompt_audio)
        except Exception:
            log.exception("follow_up_prompt_tts_failed")

        # Now listen for the user's response (reuse the listening pipeline)
        self._awaiting_follow_up = True
        self._set_state(State.LISTENING)
        self.vad.reset()

    def _handle_follow_up_intent(self, transcript: str) -> None:
        """Route follow-up transcript: new question, record opinion, or done."""
        lower = transcript.lower().strip()

        # Check for opinion recording intent
        record_phrases = [
            "record my opinion", "record opinion", "share my opinion",
            "record my thoughts", "i want to record", "let me record",
            "share my thoughts", "record a video",
        ]
        if any(phrase in lower for phrase in record_phrases):
            log.info("follow_up_intent", intent="record_opinion")
            self._initiate_voice_recording()
            return

        # Check for "done" / "no" / "that's all" intent
        done_phrases = [
            "no", "nope", "that's all", "that is all", "i'm good",
            "i'm done", "nothing", "no thanks", "no thank you", "goodbye",
        ]
        if any(phrase in lower for phrase in done_phrases):
            log.info("follow_up_intent", intent="done")
            try:
                goodbye_audio = self.tts.synthesize("Thanks for using Gordie. I'll be here if you need me.")
                self.playback.play(goodbye_audio)
            except Exception:
                pass
            # Clear user session so the next person starts fresh
            if self.registration:
                self.registration.clear_session()
            self._set_state(State.IDLE)
            return

        # Otherwise treat it as a follow-up question — queue it for the main loop
        log.info("follow_up_intent", intent="follow_up_question")
        self._pending_follow_up_query = transcript
        self._set_state(State.QUERYING)

    def _run_query_pipeline(self, transcript: str) -> None:
        """Query CanadaGPT and speak the response, then offer follow-up again.

        Note: _offer_follow_up sets state to LISTENING with _awaiting_follow_up=True,
        which causes the main voice loop to call _transcribe_and_respond(is_follow_up=True)
        on the next utterance. This avoids recursive call chains.
        """
        try:
            if self.settings.canadagpt.streaming:
                self._set_state(State.SPEAKING)
                for chunk in self.client.query_stream(transcript):
                    if self._barge_in.is_set():
                        return
                    shaped = self.shaper.shape(chunk)
                    for sentence in shaped:
                        if self._barge_in.is_set():
                            return
                        audio_data = self.tts.synthesize(sentence)
                        self.playback.play(audio_data)
            else:
                response = self.client.query(transcript)
                self.metrics.mark("canadagpt_complete")
                shaped_sentences = self.shaper.shape(response)
                self._set_state(State.SPEAKING)
                for sentence in shaped_sentences:
                    if self._barge_in.is_set():
                        return
                    audio_data = self.tts.synthesize(sentence)
                    self.playback.play(audio_data)

            # Return to main loop which will handle the follow-up listening
            self._offer_follow_up()

        except Exception:
            log.exception("follow_up_query_error")
            self._set_state(State.ERROR)

    def _initiate_voice_recording(self) -> None:
        """Start the opinion recording flow via voice command."""
        self._set_state(State.RECORDING)
        try:
            prompt_audio = self.tts.synthesize(
                "Great! I'll start recording in a moment. "
                "You'll have 60 seconds to share your opinion. "
                "You can see yourself on the screen. "
                "Say 'stop' when you're done."
            )
            self.playback.play(prompt_audio)
        except Exception:
            log.exception("recording_prompt_tts_failed")

        # Signal the display to show the recording UI
        if self.persona:
            self.persona.socketio.emit("opinion_voice_record_start", {})

    def handle_prompt_query(self, text: str) -> None:
        """Handle a text query from the display's prompt mode."""
        if self._mode != InteractionMode.PROMPT:
            return
        try:
            self._set_state(State.QUERYING)
            if self.settings.canadagpt.streaming:
                full_response: list[str] = []
                for chunk in self.client.query_stream(text):
                    full_response.append(chunk)
                    if self.persona:
                        self.persona.broadcast_response_chunk(chunk)
                if self.persona:
                    self.persona.broadcast_response_done()
            else:
                response = self.client.query(text)
                if self.persona:
                    self.persona.broadcast_response_chunk(response)
                    self.persona.broadcast_response_done()
            self._set_state(State.IDLE)
        except Exception:
            log.exception("prompt_query_error")
            self._set_state(State.ERROR)
