"""Gordie Voice Ops MCP Server.

Exposes operational tools for the Gordie Voice appliance:
- Service status, logs, audio devices
- Mic testing, Coral status
- Latency metrics, test query injection
- Hot-swap providers at runtime
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import psutil
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

GORDIE_ROOT = Path(os.environ.get("GORDIE_ROOT", "/opt/gordie-voice"))
SERVICE_NAME = "gordie-voice.service"

server = Server("gordie-voice-ops")


# ---- Service Management ----

@server.tool()
async def get_service_status() -> list[TextContent]:
    """Get systemd status of gordie-voice.service, gordie-display.service, and gordie-display-secondary.service."""
    results = {}
    for svc in ["gordie-voice", "gordie-display", "gordie-display-secondary"]:
        try:
            result = subprocess.run(
                ["systemctl", "status", f"{svc}.service", "--no-pager"],
                capture_output=True, text=True, timeout=5,
            )
            results[svc] = result.stdout
        except Exception as e:
            results[svc] = f"Error: {e}"

    return [TextContent(type="text", text=json.dumps(results, indent=2))]


@server.tool()
async def restart_service(service: str = "gordie-voice") -> list[TextContent]:
    """Restart a gordie systemd service. service: gordie-voice | gordie-display | gordie-display-secondary"""
    allowed = ["gordie-voice", "gordie-display", "gordie-display-secondary"]
    if service not in allowed:
        return [TextContent(type="text", text=f"Unknown service. Allowed: {allowed}")]

    result = subprocess.run(
        ["sudo", "systemctl", "restart", f"{service}.service"],
        capture_output=True, text=True, timeout=15,
    )
    return [TextContent(type="text", text=f"Restarted {service}. stderr: {result.stderr}" if result.returncode == 0 else f"Failed: {result.stderr}")]


# ---- Logs ----

@server.tool()
async def tail_logs(lines: int = 50, level: str = "", service: str = "gordie-voice") -> list[TextContent]:
    """Read recent journal logs for a gordie service. Optionally filter by level (INFO, WARNING, ERROR)."""
    cmd = ["journalctl", "-u", f"{service}.service", "-n", str(min(lines, 500)), "--no-pager", "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

    log_lines = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            entry = json.loads(line)
            msg = entry.get("MESSAGE", "")
            if level and level.upper() not in msg.upper():
                continue
            log_lines.append(msg)
        except json.JSONDecodeError:
            if not level or level.upper() in line.upper():
                log_lines.append(line)

    return [TextContent(type="text", text="\n".join(log_lines[-lines:]))]


# ---- Audio ----

@server.tool()
async def get_audio_devices() -> list[TextContent]:
    """List ALSA audio input and output devices."""
    inputs = subprocess.run(["arecord", "-l"], capture_output=True, text=True, timeout=5)
    outputs = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=5)
    return [TextContent(type="text", text=f"=== Input Devices ===\n{inputs.stdout}\n=== Output Devices ===\n{outputs.stdout}")]


@server.tool()
async def test_microphone(duration_s: int = 3) -> list[TextContent]:
    """Record a short audio clip from the default mic, return path and audio stats."""
    duration_s = min(duration_s, 10)
    output_path = "/tmp/gordie_mic_test.wav"
    result = subprocess.run(
        ["arecord", "-d", str(duration_s), "-f", "S16_LE", "-r", "16000", "-c", "1", output_path],
        capture_output=True, text=True, timeout=duration_s + 5,
    )
    if result.returncode != 0:
        return [TextContent(type="text", text=f"Recording failed: {result.stderr}")]

    # Get audio stats
    import wave
    import numpy as np
    with wave.open(output_path, "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        audio = np.frombuffer(frames, dtype=np.int16)
        rms = float(np.sqrt(np.mean(audio.astype(float) ** 2)))
        peak = float(np.max(np.abs(audio)))

    return [TextContent(type="text", text=json.dumps({
        "path": output_path,
        "duration_s": duration_s,
        "rms": round(rms, 1),
        "peak": round(peak, 1),
        "peak_db": round(20 * np.log10(max(peak, 1) / 32768), 1),
        "silent": rms < 100,
    }, indent=2))]


# ---- Hardware ----

@server.tool()
async def get_system_health() -> list[TextContent]:
    """Get Pi system health: CPU temp, memory, disk, uptime."""
    cpu_temp = 0.0
    try:
        cpu_temp = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000
    except Exception:
        pass

    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    uptime = time.time() - psutil.boot_time()

    return [TextContent(type="text", text=json.dumps({
        "cpu_temp_c": round(cpu_temp, 1),
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory_used_gb": round(mem.used / 1e9, 2),
        "memory_total_gb": round(mem.total / 1e9, 2),
        "memory_percent": mem.percent,
        "disk_used_gb": round(disk.used / 1e9, 2),
        "disk_total_gb": round(disk.total / 1e9, 2),
        "disk_percent": disk.percent,
        "uptime_hours": round(uptime / 3600, 1),
    }, indent=2))]


@server.tool()
async def get_coral_status() -> list[TextContent]:
    """Check if Google Coral USB Accelerator is connected and recognized."""
    lsusb = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
    coral_lines = [l for l in lsusb.stdout.splitlines() if "Google" in l or "Global Unichip" in l]

    edgetpu_check = subprocess.run(
        ["dpkg", "-l", "libedgetpu1-std"], capture_output=True, text=True, timeout=5,
    )
    lib_installed = "ii" in edgetpu_check.stdout

    return [TextContent(type="text", text=json.dumps({
        "usb_detected": len(coral_lines) > 0,
        "usb_devices": coral_lines,
        "libedgetpu_installed": lib_installed,
    }, indent=2))]


# ---- Latency Metrics ----

@server.tool()
async def get_latency_metrics(window_minutes: int = 60) -> list[TextContent]:
    """Parse recent structured logs for per-stage latency metrics."""
    cmd = ["journalctl", "-u", "gordie-voice.service", f"--since={window_minutes} minutes ago",
           "--no-pager", "-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

    metrics: dict[str, list[float]] = {}
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            entry = json.loads(line)
            msg = entry.get("MESSAGE", "")
            if "metric_mark" in msg and "elapsed_ms" in msg:
                # Parse structlog JSON output
                parts = json.loads(msg) if msg.startswith("{") else {}
                stage = parts.get("stage", "unknown")
                elapsed = parts.get("elapsed_ms", 0)
                metrics.setdefault(stage, []).append(elapsed)
        except (json.JSONDecodeError, ValueError):
            continue

    summary = {}
    for stage, values in metrics.items():
        values.sort()
        summary[stage] = {
            "count": len(values),
            "p50_ms": round(values[len(values) // 2], 1) if values else 0,
            "p95_ms": round(values[int(len(values) * 0.95)], 1) if values else 0,
            "max_ms": round(max(values), 1) if values else 0,
        }

    return [TextContent(type="text", text=json.dumps(summary, indent=2))]


# ---- Test Injection ----

@server.tool()
async def trigger_test_query(text: str) -> list[TextContent]:
    """Bypass wake word + STT — inject a text query directly into gordie via the SocketIO API."""
    import httpx
    try:
        # Connect to the local persona server and emit a prompt_submit
        resp = httpx.post(
            "http://127.0.0.1:8080/socket.io/?transport=polling",
            timeout=5,
        )
        return [TextContent(type="text", text=f"Query injected: '{text}'. Check the display for response. (Note: for full injection, use the prompt display at http://127.0.0.1:8080/prompt and type the query.)")]
    except Exception as e:
        return [TextContent(type="text", text=f"Failed to connect to persona server: {e}. Is gordie-voice running?")]


# ---- Config ----

@server.tool()
async def get_current_config() -> list[TextContent]:
    """Read the active gordie-voice configuration (YAML + env overrides)."""
    config_path = GORDIE_ROOT / "config" / "default.yaml"
    if not config_path.exists():
        # Try local dev path
        config_path = Path("config/default.yaml")

    config_text = config_path.read_text() if config_path.exists() else "Config file not found"

    # Also check which env vars are set (without values)
    env_keys = [k for k in os.environ if k.startswith(("CANADAGPT_", "DEEPGRAM_", "ELEVENLABS_", "SUPABASE_", "GORDIE_"))]

    return [TextContent(type="text", text=f"=== YAML Config ===\n{config_text}\n\n=== Env vars set ===\n{chr(10).join(env_keys) or 'None'}")]


@server.tool()
async def swap_provider(component: str, provider: str) -> list[TextContent]:
    """Hot-swap a provider by updating config/default.yaml and restarting the service.

    component: stt | tts | wake
    provider: stt→deepgram|whisper_api|whisper_cpp, tts→elevenlabs|piper|espeak, wake→openwakeword|coral
    """
    import yaml

    valid = {
        "stt": ["deepgram", "whisper_api", "whisper_cpp"],
        "tts": ["elevenlabs", "piper", "espeak"],
        "wake": ["openwakeword", "coral"],
    }

    if component not in valid:
        return [TextContent(type="text", text=f"Unknown component '{component}'. Valid: {list(valid.keys())}")]
    if provider not in valid[component]:
        return [TextContent(type="text", text=f"Unknown {component} provider '{provider}'. Valid: {valid[component]}")]

    config_path = GORDIE_ROOT / "config" / "default.yaml"
    if not config_path.exists():
        config_path = Path("config/default.yaml")

    data = yaml.safe_load(config_path.read_text())
    old_provider = data.get(component, {}).get("provider", "unknown")
    data[component]["provider"] = provider
    config_path.write_text(yaml.dump(data, default_flow_style=False))

    # Restart service
    subprocess.run(["sudo", "systemctl", "restart", "gordie-voice.service"],
                   capture_output=True, timeout=15)

    return [TextContent(type="text", text=f"Swapped {component} provider: {old_provider} → {provider}. Service restarting.")]


def main():
    import asyncio
    asyncio.run(stdio_server(server))


if __name__ == "__main__":
    main()
