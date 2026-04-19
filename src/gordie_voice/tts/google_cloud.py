"""Google Cloud Text-to-Speech provider.

Uses the Google Cloud TTS API with WaveNet/Neural2/Studio voices.
Produces high-quality natural-sounding speech.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from gordie_voice.config import Settings

from gordie_voice.tts.base import TTSProvider

log = structlog.get_logger()

# Good Canadian English voice options:
# en-US-Neural2-D  — male, natural
# en-US-Neural2-A  — female, natural
# en-US-Studio-O   — male, studio quality (higher cost)
# en-US-Wavenet-D  — male, wavenet
# en-GB-Neural2-B  — British male (some prefer for Canadian)
DEFAULT_VOICE = "en-US-Neural2-D"


class GoogleCloudTTS(TTSProvider):
    def __init__(self, settings: Settings) -> None:
        from google.cloud import texttospeech

        self._voice_name = settings.tts.model or DEFAULT_VOICE
        self._client = texttospeech.TextToSpeechClient()

        # Parse voice name to determine language code
        # Voice names follow pattern: {lang}-{variant}-{type}-{letter}
        parts = self._voice_name.rsplit("-", 2)
        self._language_code = parts[0] if len(parts) >= 3 else "en-US"

        self._voice = texttospeech.VoiceSelectionParams(
            language_code=self._language_code,
            name=self._voice_name,
        )
        self._audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
        )
        log.info("google_cloud_tts_ready", voice=self._voice_name, language=self._language_code)

    def synthesize(self, text: str) -> bytes:
        from google.cloud import texttospeech

        synthesis_input = texttospeech.SynthesisInput(text=text)
        response = self._client.synthesize_speech(
            input=synthesis_input,
            voice=self._voice,
            audio_config=self._audio_config,
        )

        # response.audio_content is a WAV file — strip the header for raw PCM
        import io
        import wave
        wav_buf = io.BytesIO(response.audio_content)
        with wave.open(wav_buf, "rb") as wf:
            pcm_data = wf.readframes(wf.getnframes())

        log.debug("google_tts_synthesized", text_len=len(text), audio_bytes=len(pcm_data))
        return pcm_data
