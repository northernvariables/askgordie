from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class AudioConfig(BaseModel):
    sample_rate: int = 16000
    channels: int = 1
    buffer_size_ms: int = 30
    input_device: int | str | None = None
    output_device: int | str | None = None


class WakeConfig(BaseModel):
    provider: Literal["openwakeword", "coral"] = "openwakeword"
    model_path: str | None = None
    threshold: float = 0.5


class VADConfig(BaseModel):
    min_silence_ms: int = 700
    max_utterance_s: int = 15
    speech_pad_ms: int = 200


class STTConfig(BaseModel):
    provider: Literal["deepgram", "whisper_api", "whisper_cpp", "faster_whisper"] = "deepgram"
    model: str = "nova-3"
    streaming: bool = True


class TTSConfig(BaseModel):
    provider: Literal["elevenlabs", "piper", "google_cloud", "resemble", "espeak"] = "elevenlabs"
    model: str = "en_US-lessac-medium"  # Piper voice model name
    streaming: bool = True
    chunk_strategy: Literal["sentence", "paragraph"] = "sentence"


class CanadaGPTConfig(BaseModel):
    timeout_s: int = 30
    retry_count: int = 1
    streaming: bool = True


class ShaperConfig(BaseModel):
    max_response_words: int = 400
    strip_citations: bool = False
    strip_urls: bool = True


class VisionConfig(BaseModel):
    enabled: bool = True
    camera_index: int = 0
    check_interval_s: float = 1.0
    presence_timeout_s: float = 10.0
    face_min_confidence: float = 0.5


class DisplayConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8080
    fullscreen: bool = True
    theme: Literal["canadian", "dark", "light"] = "canadian"
    dual_display: bool = False  # When True, primary=voice persona, secondary=prompt
    primary_mode: Literal["voice", "prompt"] = "voice"  # What the primary display shows
    secondary_mode: Literal["voice", "prompt"] = "prompt"  # What the secondary display shows
    touch_enabled: bool = True  # Enable touch-friendly UI (larger targets, on-screen inputs)
    registration_url: str = "https://canadagpt.ca/register"  # QR code target URL


class RecordingConfig(BaseModel):
    max_duration_s: int = 30          # Default Speaker's Corner style — short and punchy
    max_duration_registered_s: int = 60  # Registered users get longer
    countdown_warning_s: int = 10     # Flash red in last N seconds
    fact_check_enabled: bool = True   # Run fact-checker after recording


class RegistrationConfig(BaseModel):
    enabled: bool = True
    verification_timeout_s: int = 300
    code_length: int = 6


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__")

    # API keys (from .env — no prefix, mapped directly)
    canadagpt_api_url: str = "https://api.canadagpt.ca/v1/chat"
    canadagpt_api_key: str = ""
    deepgram_api_key: str = ""
    openai_api_key: str = ""       # For Whisper API fallback STT
    anthropic_api_key: str = ""    # For direct Anthropic API (bypass when CanadaGPT needs session auth)
    resemble_api_key: str = ""     # For Resemble AI voice cloning TTS
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""  # For server-side uploads (never expose to client)
    gordie_device_id: str = "gordie-001"
    active_persona: str = "laurier"  # laurier | pearson | douglas | diefenbaker
    gordie_wake_word: str = "hey_gordie"
    gordie_log_level: str = "INFO"

    @property
    def device_id(self) -> str:
        return self.gordie_device_id

    @property
    def wake_word(self) -> str:
        return self.gordie_wake_word

    @property
    def log_level(self) -> str:
        return self.gordie_log_level

    # Subsystem configs (from YAML)
    audio: AudioConfig = AudioConfig()
    wake: WakeConfig = WakeConfig()
    vad: VADConfig = VADConfig()
    stt: STTConfig = STTConfig()
    tts: TTSConfig = TTSConfig()
    canadagpt: CanadaGPTConfig = CanadaGPTConfig()
    shaper: ShaperConfig = ShaperConfig()
    vision: VisionConfig = VisionConfig()
    display: DisplayConfig = DisplayConfig()
    recording: RecordingConfig = RecordingConfig()
    registration: RegistrationConfig = RegistrationConfig()


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from YAML config file, overridden by environment variables."""
    yaml_data: dict = {}
    if config_path and config_path.exists():
        yaml_data = yaml.safe_load(config_path.read_text()) or {}
    elif (default := Path("config/default.yaml")).exists():
        yaml_data = yaml.safe_load(default.read_text()) or {}

    return Settings(**yaml_data)
