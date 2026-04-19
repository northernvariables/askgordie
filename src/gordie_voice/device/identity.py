"""Device identity — reads Pi hardware serial and generates activation codes."""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

import structlog

log = structlog.get_logger()


def get_hardware_serial() -> str:
    """Read the Raspberry Pi's unique hardware serial from /proc/cpuinfo."""
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text()
        for line in cpuinfo.splitlines():
            if line.startswith("Serial"):
                return line.split(":")[1].strip()
    except Exception:
        log.warning("hardware_serial_unavailable")
    # Fallback: hash the machine-id
    try:
        machine_id = Path("/etc/machine-id").read_text().strip()
        return hashlib.sha256(machine_id.encode()).hexdigest()[:16]
    except Exception:
        return "unknown"


def generate_activation_code() -> str:
    """Generate an 8-character alphanumeric activation code for first-boot pairing."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # No I/O/0/1 to avoid confusion
    return "".join(secrets.choice(alphabet) for _ in range(8))


def generate_api_key() -> str:
    """Generate a device API key: grd_<48 random chars>."""
    return f"grd_{secrets.token_urlsafe(36)}"


def hash_api_key(key: str) -> str:
    """Hash an API key for storage. Uses SHA-256 (sufficient for high-entropy keys)."""
    return hashlib.sha256(key.encode()).hexdigest()


def api_key_prefix(key: str) -> str:
    """Extract the prefix for identification: 'grd_a1b2c3d4'."""
    return key[:12]
