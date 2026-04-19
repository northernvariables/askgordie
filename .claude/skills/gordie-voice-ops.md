---
name: gordie-voice-ops
description: Operational runbook for Gordie Voice appliance — service health, logs, audio diagnostics, provider swapping, common failure modes
---

# Gordie Voice Operations

## Service Management
- Main service: `gordie-voice.service` — the Python app (state machine, audio, STT/TTS, CanadaGPT client)
- Primary display: `gordie-display.service` — Chromium kiosk showing `/primary`
- Secondary display: `gordie-display-secondary.service` — Chromium kiosk showing `/secondary`
- All run as user `gordie`, managed by systemd

## Checking Health
1. `systemctl status gordie-voice` — is the main service running?
2. `journalctl -u gordie-voice -n 50 --no-pager` — recent logs (structlog JSON)
3. Check CPU temp: `cat /sys/class/thermal/thermal_zone0/temp` (divide by 1000 for °C; throttling starts at 80°C)
4. Check audio: `arecord -l` (inputs), `aplay -l` (outputs)
5. Check Coral: `lsusb | grep Google`

## Common Failure Modes

### "Wake word never triggers"
- Check mic: `arecord -d 3 -f S16_LE -r 16000 test.wav && aplay test.wav`
- If silent: USB mic not recognized or wrong device index in config
- If audio works: check `wake.threshold` in config (lower = more sensitive, more false positives)
- openwakeword models may not have downloaded on first boot if offline

### "STT returns empty/garbage"
- Check Deepgram API key is set in `/opt/gordie-voice/.env`
- Check network: `curl -s https://api.deepgram.com/v1/listen` should return 401 not connection error
- If using whisper_cpp: check model file exists, check Pi thermal throttling

### "TTS produces noise/clicks"
- If using espeak: ensure the WAV header stripping fix is in place (C6 from code review)
- If using ElevenLabs: check API key, check voice_id is valid
- Test: `espeak-ng --stdout "test" | aplay` — should be intelligible

### "Camera not working"
- `ls /dev/video*` — camera should appear as /dev/video0
- PresenceDetector and OpinionRecorder share the camera — only one can hold it at a time
- The PresenceDetector releases via a threading.Event; check `_camera_released` is signaled

### "Display shows nothing / blank screen"
- Check Chromium is running: `ps aux | grep chromium`
- Check persona server is running: `curl http://127.0.0.1:8080/`
- Check DISPLAY env var is set in the service file

## Provider Swapping
Edit `config/default.yaml` and restart:
```yaml
stt:
  provider: whisper_cpp   # swap from deepgram
tts:
  provider: piper          # swap from elevenlabs
wake:
  provider: coral          # swap from openwakeword (needs model_path)
```
Then: `sudo systemctl restart gordie-voice`

Or use the gordie-voice-ops MCP tool: `swap_provider(component="stt", provider="whisper_cpp")`

## Log Reading
Logs are structured JSON via structlog. Key events:
- `gordie_boot` — startup
- `wake_detected` — wake word triggered
- `state_transition` — state machine change (old, new)
- `metric_mark` — per-stage latency (stage, elapsed_ms)
- `transcription` — STT result (text)
- `canadagpt_response` — API response (latency_ms, length)
- `pipeline_error` — something broke in the STT→query→TTS pipeline
- `fact_check_complete` — fact-check results (claims, accuracy)

## Device Registry
- Activation code shown on display at first boot
- Device heartbeats every 60s to Supabase
- Config overrides pushed via `devices.config_override` JSON field
- Riding resolved from postal code via Represent API
