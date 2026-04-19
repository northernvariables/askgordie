---
name: pi5-provisioning
description: First-boot provisioning for Raspberry Pi 5 appliances — OS, users, Python, security, systemd patterns
---

# Raspberry Pi 5 Provisioning

## Base Image
- Raspberry Pi OS Bookworm 64-bit (Lite or Desktop depending on display needs)
- Kernel 6.6+
- Flash with Raspberry Pi Imager, enable SSH in advanced options

## First Boot Checklist
1. **Update**: `sudo apt update && sudo apt upgrade -y`
2. **Create service user**: `sudo useradd -m -s /bin/bash -G audio,video,input,gpio gordie`
3. **SSH hardening**: disable password auth, add authorized keys
4. **Install Python 3.11+**: available in Bookworm repos
5. **Install uv**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
6. **Install system deps**: portaudio, libsndfile, opencv, ffmpeg, espeak-ng, chromium
7. **Create venv**: `uv venv --python python3.11 /opt/gordie-voice/venv`
8. **Install app**: `uv pip install -e . --python /opt/gordie-voice/venv/bin/python`
9. **Copy .env**: from `.env.example`, fill in API keys
10. **Install systemd services**: copy from `systemd/` to `/etc/systemd/system/`
11. **Enable and start**: `systemctl enable --now gordie-voice gordie-display`

## Thermal Management
- **Required**: Official Pi 5 Active Cooler
- Monitor: `cat /sys/class/thermal/thermal_zone0/temp`
- Throttling starts at 80°C — sustained STT/TTS inference will hit this without active cooling

## Power
- **Required**: Official 27W USB-C PSU
- Under-powered PSU causes: Coral USB failures, SD card corruption, random reboots

## Storage
- Minimum: 32GB microSD Class A2
- Recommended: NVMe SSD via M.2 HAT (faster cold start, model loading)

## Auto-Start on Boot
systemd services with `WantedBy=multi-user.target` (voice service) and `WantedBy=graphical.target` (display services).

## Kiosk Mode (Chromium)
```
chromium-browser --kiosk --noerrdialogs --disable-translate --no-first-run \
  --touch-events=enabled --disable-pinch --overscroll-history-navigation=disabled \
  http://127.0.0.1:8080/primary
```

## Networking
- Bind Flask to `0.0.0.0` if mobile devices need to reach the queue join page
- QR codes use LAN IP detection (UDP socket trick to 8.8.8.8)
- Consider Tailscale for remote management

## Security
- API keys in `/opt/gordie-voice/.env`, chmod 600, owned by gordie
- Device API key in `/opt/gordie-voice/.device_key`, chmod 600
- No root access needed at runtime (systemd handles privileged ports)
- Supabase service_role key: never expose to browser, only used server-side
