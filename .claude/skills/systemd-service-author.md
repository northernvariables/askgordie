---
name: systemd-service-author
description: Writing correct systemd units — restart policies, security hardening, journal integration, dependencies
---

# systemd Service Authoring

## Basic Service Template
```ini
[Unit]
Description=Service Name
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=serviceuser
Group=serviceuser
WorkingDirectory=/opt/service
EnvironmentFile=/opt/service/.env
ExecStart=/opt/service/venv/bin/python -m package_name
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

## Key Decisions

### Restart Policy
- `Restart=always` for daemons that should never be down
- `Restart=on-failure` for services where a clean exit means "done"
- `RestartSec=5` prevents restart storms

### Security Hardening
- `User=` / `Group=` — never run as root
- `SupplementaryGroups=audio video input` — grant device access
- `MemoryMax=2G` — prevent memory leaks from killing the system
- `CPUQuota=80%` — leave headroom for SSH

### Dependencies
- `After=network-online.target` — wait for network
- `After=graphical.target` — wait for display (kiosk services)
- `Wants=` — soft dependency (start if available)
- `Requires=` — hard dependency (fail if missing)

### Display Services (Chromium Kiosk)
```ini
[Service]
Environment=DISPLAY=:0
ExecStartPre=/bin/sleep 3    # Wait for X to initialize
ExecStart=/usr/bin/chromium-browser --kiosk ...
```
- Use `--window-position=1920,0` for secondary display
- `--touch-events=enabled` for touchscreens
- `--disable-pinch` to prevent zoom gestures

### Logging
- `StandardOutput=journal` sends stdout to systemd journal
- Read with `journalctl -u service-name -n 50`
- structlog JSON output works well with journal

## Commands
```bash
sudo systemctl daemon-reload      # After editing unit files
sudo systemctl enable service     # Start on boot
sudo systemctl start service      # Start now
sudo systemctl status service     # Check status
sudo systemctl restart service    # Restart
journalctl -u service -f          # Follow logs
```
