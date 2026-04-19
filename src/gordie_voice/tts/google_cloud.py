"""Google Cloud Text-to-Speech provider — Chirp3 HD voices.

Uses the v1beta1 REST API (required for Chirp3 HD voices).
Same voices and API as the CanadaGPT frontend.
"""

from __future__ import annotations

import base64
import io
import json
import wave
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import Settings

from gordie_voice.tts.base import TTSProvider

log = structlog.get_logger()

# Chirp3 HD voices (same as CanadaGPT frontend):
# Alnilam (default), Achird, Algieba, Enceladus, Fenrir, Puck, Aoede, Charon, Kore
DEFAULT_VOICE = "Alnilam"
DEFAULT_LANGUAGE = "en-US"
TTS_ENDPOINT = "https://texttospeech.googleapis.com/v1beta1/text:synthesize"


class GoogleCloudTTS(TTSProvider):
    def __init__(self, settings: Settings) -> None:
        self._voice_name = settings.tts.model or DEFAULT_VOICE
        self._language_code = DEFAULT_LANGUAGE
        self._project_id = "canada-gpt-ca"
        self._access_token: str | None = None
        self._token_expiry: float = 0

        # Build full voice name: "en-US-Chirp3-HD-Alnilam"
        if "-" not in self._voice_name:
            self._full_voice_name = f"{self._language_code}-Chirp3-HD-{self._voice_name}"
        else:
            self._full_voice_name = self._voice_name

        log.info("google_cloud_tts_ready", voice=self._full_voice_name)

    def _get_access_token(self) -> str:
        """Get an access token from the service account key."""
        import time
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token

        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        import os
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        creds = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        creds.refresh(Request())
        self._access_token = creds.token
        self._token_expiry = time.time() + 3500  # Tokens last 3600s
        return self._access_token

    def synthesize(self, text: str) -> bytes:
        token = self._get_access_token()

        response = httpx.post(
            TTS_ENDPOINT,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "x-goog-user-project": self._project_id,
            },
            json={
                "input": {"text": text},
                "voice": {
                    "name": self._full_voice_name,
                    "languageCode": self._language_code,
                },
                "audioConfig": {
                    "audioEncoding": "LINEAR16",
                    "sampleRateHertz": 16000,
                    "speakingRate": 1.0,
                },
            },
            timeout=15.0,
        )

        if response.status_code != 200:
            error_msg = response.json().get("error", {}).get("message", response.text)
            log.error("google_tts_error", status=response.status_code, error=error_msg)
            raise RuntimeError(f"Google TTS failed: {error_msg}")

        audio_b64 = response.json()["audioContent"]
        audio_bytes = base64.b64decode(audio_b64)

        # LINEAR16 response is raw WAV — strip header for PCM
        wav_buf = io.BytesIO(audio_bytes)
        with wave.open(wav_buf, "rb") as wf:
            pcm_data = wf.readframes(wf.getnframes())

        log.debug("google_tts_synthesized", text_len=len(text), audio_bytes=len(pcm_data))
        return pcm_data
