"""Device registry client — handles activation, heartbeat, config sync, and key exchange.

Lifecycle:
1. First boot: device generates an activation code, registers as 'pending' in Supabase
2. Admin enters the code in the CanadaGPT admin panel → status becomes 'activated'
3. Device polls for activation, receives its API key
4. Device stores API key locally in /opt/gordie-voice/.device_key
5. Ongoing: periodic heartbeats, config sync, riding resolution
"""

from __future__ import annotations

import platform
import time
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import structlog

from gordie_voice.device.identity import (
    api_key_prefix,
    generate_activation_code,
    generate_api_key,
    get_hardware_serial,
    hash_api_key,
)

if TYPE_CHECKING:
    from gordie_voice.config import Settings

log = structlog.get_logger()

DEVICE_KEY_PATH = Path("/opt/gordie-voice/.device_key")
HEARTBEAT_INTERVAL_S = 60


class DeviceRegistry:
    """Manages this device's relationship with the CanadaGPT mothership."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._supabase_url = settings.supabase_url
        self._supabase_key = settings.supabase_service_role_key
        self._device_id = settings.device_id
        self._hardware_serial = get_hardware_serial()
        self._api_key: str | None = None
        self._activation_code: str | None = None
        self._device_record: dict | None = None
        self._running = False
        self._thread: threading.Thread | None = None

        self._client = httpx.Client(
            headers={
                "apikey": self._supabase_key,
                "Authorization": f"Bearer {self._supabase_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

        # Try loading existing API key
        self._load_api_key()

    @property
    def is_activated(self) -> bool:
        return self._api_key is not None

    @property
    def activation_code(self) -> str | None:
        return self._activation_code

    @property
    def riding_name(self) -> str | None:
        if self._device_record:
            return self._device_record.get("riding_name")
        return None

    @property
    def riding_code(self) -> str | None:
        if self._device_record:
            return self._device_record.get("riding_code")
        return None

    @property
    def config_override(self) -> dict:
        if self._device_record:
            return self._device_record.get("config_override", {})
        return {}

    def start(self) -> None:
        """Start the device registry lifecycle."""
        self._running = True
        if not self.is_activated:
            self._register_or_resume()
        self._thread = threading.Thread(target=self._lifecycle_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _load_api_key(self) -> None:
        """Load stored API key from disk."""
        if DEVICE_KEY_PATH.exists():
            self._api_key = DEVICE_KEY_PATH.read_text().strip()
            log.info("device_key_loaded", prefix=api_key_prefix(self._api_key))

    def _save_api_key(self, key: str) -> None:
        """Save API key to disk with restrictive permissions."""
        DEVICE_KEY_PATH.write_text(key)
        DEVICE_KEY_PATH.chmod(0o600)
        self._api_key = key
        log.info("device_key_saved", prefix=api_key_prefix(key))

    def _register_or_resume(self) -> None:
        """Register as a new device or resume an existing pending registration."""
        # Check if we already exist in the registry
        existing = self._fetch_device()
        if existing:
            self._device_record = existing
            if existing["status"] == "activated" and not self._api_key:
                # Activated but we lost our key — need admin to re-issue
                log.warning("device_activated_but_key_missing", device_id=self._device_id)
                self._activation_code = existing.get("activation_code")
            elif existing["status"] == "pending":
                self._activation_code = existing.get("activation_code")
                log.info("device_pending_activation", code=self._activation_code)
            return

        # New device — register with activation code
        self._activation_code = generate_activation_code()
        row = {
            "device_id": self._device_id,
            "hardware_serial": self._hardware_serial,
            "activation_code": self._activation_code,
            "status": "pending",
            "software_version": "0.1.0",
            "os_version": platform.platform(),
        }

        try:
            url = f"{self._supabase_url}/rest/v1/devices"
            resp = self._client.post(url, json=row, headers={"Prefer": "return=representation"})
            resp.raise_for_status()
            self._device_record = resp.json()[0] if resp.json() else row
            log.info(
                "device_registered",
                device_id=self._device_id,
                activation_code=self._activation_code,
            )
        except Exception:
            log.exception("device_registration_failed")

    def _fetch_device(self) -> dict | None:
        """Fetch this device's record from the registry."""
        try:
            url = f"{self._supabase_url}/rest/v1/devices?device_id=eq.{self._device_id}&select=*"
            resp = self._client.get(url)
            resp.raise_for_status()
            rows = resp.json()
            return rows[0] if rows else None
        except Exception:
            log.exception("device_fetch_failed")
            return None

    def _lifecycle_loop(self) -> None:
        """Main loop: poll for activation, then heartbeat + config sync."""
        while self._running:
            try:
                if not self.is_activated:
                    self._poll_for_activation()
                else:
                    self._send_heartbeat()
                    self._sync_config()
            except Exception:
                log.exception("lifecycle_loop_error")

            time.sleep(HEARTBEAT_INTERVAL_S)

    def _poll_for_activation(self) -> None:
        """Check if admin has activated this device. If so, complete key exchange."""
        record = self._fetch_device()
        if not record:
            return

        self._device_record = record

        if record["status"] == "activated" and not self._api_key:
            # Admin activated us — generate and store API key
            new_key = generate_api_key()
            key_hash = hash_api_key(new_key)
            prefix = api_key_prefix(new_key)

            try:
                from datetime import datetime, timezone
                url = f"{self._supabase_url}/rest/v1/devices?device_id=eq.{self._device_id}"
                self._client.patch(url, json={
                    "api_key_hash": key_hash,
                    "api_key_prefix": prefix,
                    "api_key_issued_at": datetime.now(timezone.utc).isoformat(),
                }, headers={"Prefer": "return=minimal"}).raise_for_status()

                self._save_api_key(new_key)
                log.info("device_activated", device_id=self._device_id, key_prefix=prefix)
            except Exception:
                log.exception("key_exchange_failed")

    def _send_heartbeat(self) -> None:
        """Send periodic heartbeat with device health data."""
        from datetime import datetime, timezone

        heartbeat = {
            "uptime_s": self._get_uptime(),
            "cpu_temp_c": self._get_cpu_temp(),
            "software_version": "0.1.0",
        }

        try:
            url = f"{self._supabase_url}/rest/v1/devices?device_id=eq.{self._device_id}"
            self._client.patch(url, json={
                "last_heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "heartbeat_data": heartbeat,
                "software_version": "0.1.0",
                "api_key_last_used_at": datetime.now(timezone.utc).isoformat(),
            }, headers={"Prefer": "return=minimal"}).raise_for_status()
        except Exception:
            log.warning("heartbeat_failed")

    def _sync_config(self) -> None:
        """Pull remote config overrides if version has changed."""
        record = self._fetch_device()
        if not record:
            return

        self._device_record = record
        remote_version = record.get("config_version", 0)
        local_version = record.get("device_config_version", 0)

        if remote_version > local_version:
            log.info("config_update_available", remote=remote_version, local=local_version)
            # Acknowledge the config
            try:
                url = f"{self._supabase_url}/rest/v1/devices?device_id=eq.{self._device_id}"
                self._client.patch(url, json={
                    "device_config_version": remote_version,
                }, headers={"Prefer": "return=minimal"}).raise_for_status()
                log.info("config_acknowledged", version=remote_version)
            except Exception:
                log.warning("config_ack_failed")

    def set_location(self, latitude: float, longitude: float, address: str = "", postal_code: str = "") -> None:
        """Set device location and trigger riding resolution."""
        try:
            from datetime import datetime, timezone
            update: dict = {
                "latitude": latitude,
                "longitude": longitude,
            }
            if address:
                update["address"] = address
            if postal_code:
                update["postal_code"] = postal_code

            url = f"{self._supabase_url}/rest/v1/devices?device_id=eq.{self._device_id}"
            self._client.patch(url, json=update, headers={"Prefer": "return=minimal"}).raise_for_status()
            log.info("device_location_set", lat=latitude, lon=longitude, postal=postal_code)

            # Resolve riding from postal code
            if postal_code:
                self._resolve_riding(postal_code)
        except Exception:
            log.exception("set_location_failed")

    def _resolve_riding(self, postal_code: str) -> None:
        """Resolve federal electoral riding from postal code via the Represent API."""
        try:
            import re
            clean_postal = postal_code.replace(" ", "").upper()
            if not re.match(r"^[A-Z]\d[A-Z]\d[A-Z]\d$", clean_postal):
                log.warning("invalid_postal_code", postal_code=postal_code)
                return
            resp = httpx.get(
                f"https://represent.opennorth.ca/postcodes/{clean_postal}/",
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()

            # Find the federal riding in the boundaries
            riding_name = None
            riding_code = None
            province = None
            for boundary in data.get("boundaries_concordance", data.get("boundaries_centroid", [])):
                boundary_set = boundary.get("boundary_set_name", "")
                if "Federal" in boundary_set or "federal" in boundary_set:
                    riding_name = boundary.get("name")
                    riding_code = boundary.get("external_id")
                    break

            # Also check representatives for riding info
            for rep in data.get("representatives_centroid", []):
                if rep.get("elected_office") == "MP":
                    riding_name = riding_name or rep.get("district_name")
                    province = rep.get("province")
                    break

            if riding_name:
                from datetime import datetime, timezone
                url = f"{self._supabase_url}/rest/v1/devices?device_id=eq.{self._device_id}"
                self._client.patch(url, json={
                    "riding_name": riding_name,
                    "riding_code": riding_code or "",
                    "province": province or "",
                    "riding_resolved_at": datetime.now(timezone.utc).isoformat(),
                }, headers={"Prefer": "return=minimal"}).raise_for_status()
                log.info("riding_resolved", riding=riding_name, code=riding_code)
                # Refresh local record
                self._device_record = self._fetch_device()
            else:
                log.warning("riding_not_found", postal_code=postal_code)

        except Exception:
            log.exception("riding_resolution_failed", postal_code=postal_code)

    def _get_uptime(self) -> float:
        try:
            return float(Path("/proc/uptime").read_text().split()[0])
        except Exception:
            return 0.0

    def _get_cpu_temp(self) -> float:
        try:
            temp_str = Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()
            return int(temp_str) / 1000.0
        except Exception:
            return 0.0
