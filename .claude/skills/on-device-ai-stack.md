---
name: on-device-ai-stack
description: Reference for whisper.cpp, Piper TTS, openWakeWord, faster-whisper — installation and tuning on ARM64/Pi 5
---

# On-Device AI Stack for Raspberry Pi 5

## Speech-to-Text

### whisper.cpp (Recommended for sovereignty)
- **Model**: `ggml-small.en-q5_1.bin` (~500MB, quantized)
- **Performance**: ~2-3x realtime on Pi 5 for Small model
- **Install**: Build from source or use Python bindings (`whispercpp`)
- **Tips**:
  - Use quantized models (q5_1) — minimal quality loss, 2x faster
  - Small model is the sweet spot for Pi 5 (Base too inaccurate, Medium too slow)
  - Monitor thermals — sustained inference hits 75°C+ with active cooler
  - `ggml-small.en` (English-only) is faster than `ggml-small` (multilingual)

### faster-whisper (Alternative)
- CTranslate2 backend, Python-native
- Similar performance to whisper.cpp
- Easier Python integration but larger memory footprint
- `pip install faster-whisper`

### Deepgram Nova-3 (Cloud fallback)
- Lowest latency cloud STT
- Strong Canadian English recognition
- Streaming API for real-time transcription
- Good free tier for prototyping

## Text-to-Speech

### Piper (Recommended for sovereignty)
- **Model**: `en_US-lessac-medium` or `en_GB-alan-medium`
- **Performance**: Near-realtime on Pi 5
- **Memory**: ~200MB per model
- **Install**: `pip install piper-tts` or use the CLI binary
- **Tips**:
  - `--output-raw` for headerless PCM (pipe directly to speaker)
  - Evaluate both US and GB voices for Canadian English fit
  - Medium quality is the sweet spot (Low sounds robotic, High is slower)

### ElevenLabs (Cloud, best quality)
- `eleven_turbo_v2_5` model for lowest latency
- `pcm_16000` output format for direct playback
- Streaming supported — play audio as it arrives
- Best for demo polish

### espeak-ng (Zero-dependency fallback)
- Pre-installed on most Linux
- Robotic but functional for testing
- `--stdout` produces WAV — must strip header before raw playback

## Wake Word Detection

### openWakeWord (CPU, v1)
- Python library, runs on Pi CPU
- Stock models: "hey jarvis", "alexa", etc.
- Custom training via `openwakeword` tools
- ~5% CPU on Pi 5
- Download models on first run: `openwakeword.utils.download_models()`

### Google Coral USB Accelerator (Edge TPU, v2)
- Ideal for always-on keyword spotting at sub-watt power
- Poorly suited for transformer-based STT/TTS
- Requires: `libedgetpu1-std`, `pycoral`
- Custom model: Train via Teachable Machine → TFLite → Edge TPU compiler
- USB connection: use short cable, ensure 27W PSU

## Voice Activity Detection

### Silero VAD
- PyTorch-based, runs on CPU
- Excellent speech/silence discrimination
- Key parameters:
  - `min_silence_duration_ms: 700` — how long silence before "done"
  - `max_utterance_duration_s: 15` — hard cutoff
  - `speech_pad_ms: 200` — padding around detected speech
- Must call `reset()` between utterances

## Memory Budget (Pi 5, 8GB)
| Component | Memory |
|-----------|--------|
| OS + system | ~1GB |
| Python + app | ~200MB |
| Whisper Small | ~500MB |
| Piper Medium | ~200MB |
| openWakeWord | ~100MB |
| Silero VAD | ~100MB |
| OpenCV + MediaPipe | ~300MB |
| **Total** | **~2.4GB** |

Leaves ~5.6GB headroom for Chromium, recording buffers, etc.
