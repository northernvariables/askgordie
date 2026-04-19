"""Queue manager for Gordie devices.

Flow:
1. Secondary display shows a QR code linking to /queue/join?device=gordie-001
2. User scans, enters name + postal code on their phone
3. They get a ticket number and estimated wait time
4. Gordie display shows "Now Serving #XX" and calls the next person
5. When done, marks entry complete and calls next

The QR links to a lightweight mobile-friendly page served by the Gordie device
itself — no external infrastructure needed.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import Settings

log = structlog.get_logger()

AVG_INTERACTION_MINUTES = 3


class QueueEntry:
    def __init__(self, data: dict) -> None:
        self.id = data.get("id", "")
        self.ticket_number = data.get("ticket_number", 0)
        self.display_name = data.get("display_name", "")
        self.postal_code = data.get("postal_code", "")
        self.riding_name = data.get("riding_name", "")
        self.riding_code = data.get("riding_code", "")
        self.phone = data.get("phone", "")
        self.status = data.get("status", "waiting")
        self.user_id = data.get("user_id")
        self.created_at = data.get("created_at", "")


class QueueManager:
    """Manages the queue for a single Gordie device."""

    def __init__(self, settings: Settings) -> None:
        self._device_id = settings.device_id
        self._supabase_url = settings.supabase_url
        self._supabase_key = settings.supabase_service_role_key
        self._client = httpx.Client(
            headers={
                "apikey": self._supabase_key,
                "Authorization": f"Bearer {self._supabase_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        self._current_serving: QueueEntry | None = None
        self._today_ticket_count = 0
        self._load_today_count()

    @property
    def now_serving(self) -> QueueEntry | None:
        return self._current_serving

    @property
    def now_serving_number(self) -> int | None:
        return self._current_serving.ticket_number if self._current_serving else None

    def add_to_queue(
        self,
        display_name: str,
        postal_code: str = "",
        phone: str = "",
        user_id: str | None = None,
    ) -> dict:
        """Add a person to the queue. Returns ticket info."""
        self._today_ticket_count += 1
        ticket_number = self._today_ticket_count

        # Resolve riding from postal code
        riding_name, riding_code = "", ""
        if postal_code:
            riding_name, riding_code = self._resolve_riding(postal_code)

        row = {
            "device_id": self._device_id,
            "display_name": display_name,
            "postal_code": postal_code,
            "riding_name": riding_name,
            "riding_code": riding_code,
            "phone": phone,
            "user_id": user_id,
            "ticket_number": ticket_number,
            "status": "waiting",
            "estimated_wait_minutes": self._estimate_wait(),
        }

        try:
            url = f"{self._supabase_url}/rest/v1/queue_entries"
            resp = self._client.post(url, json=row, headers={"Prefer": "return=representation"})
            resp.raise_for_status()
            entry = resp.json()[0] if resp.json() else row
            log.info("queue_added", ticket=ticket_number, name=display_name)
            return {
                "ticket_number": ticket_number,
                "estimated_wait_minutes": row["estimated_wait_minutes"],
                "position": self._get_waiting_count(),
                "riding_name": riding_name,
            }
        except Exception:
            log.exception("queue_add_failed")
            return {"ticket_number": ticket_number, "estimated_wait_minutes": 0, "position": 0}

    def call_next(self) -> QueueEntry | None:
        """Mark current as completed, call the next person in the queue."""
        # Complete current
        if self._current_serving:
            self._update_status(self._current_serving.id, "completed")

        # Get next waiting
        try:
            url = (
                f"{self._supabase_url}/rest/v1/queue_entries"
                f"?device_id=eq.{self._device_id}"
                f"&status=eq.waiting"
                f"&order=ticket_number.asc"
                f"&limit=1"
                f"&select=*"
            )
            resp = self._client.get(url)
            resp.raise_for_status()
            rows = resp.json()

            if not rows:
                self._current_serving = None
                log.info("queue_empty")
                return None

            entry = QueueEntry(rows[0])
            self._update_status(entry.id, "now_serving")
            self._current_serving = entry
            log.info("now_serving", ticket=entry.ticket_number, name=entry.display_name)
            return entry

        except Exception:
            log.exception("call_next_failed")
            return None

    def skip_current(self) -> None:
        """Mark current as no-show and call next."""
        if self._current_serving:
            self._update_status(self._current_serving.id, "no_show")
            self._current_serving = None
        self.call_next()

    def get_queue_status(self) -> dict:
        """Get current queue status for display."""
        waiting = self._get_waiting_count()
        return {
            "now_serving": self._current_serving.ticket_number if self._current_serving else None,
            "now_serving_name": self._current_serving.display_name if self._current_serving else None,
            "waiting_count": waiting,
            "estimated_wait_minutes": waiting * AVG_INTERACTION_MINUTES,
        }

    def get_waiting_list(self) -> list[dict]:
        """Get all waiting entries for display."""
        try:
            url = (
                f"{self._supabase_url}/rest/v1/queue_entries"
                f"?device_id=eq.{self._device_id}"
                f"&status=eq.waiting"
                f"&order=ticket_number.asc"
                f"&select=ticket_number,display_name,postal_code,riding_name"
            )
            resp = self._client.get(url)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return []

    def _get_waiting_count(self) -> int:
        try:
            url = (
                f"{self._supabase_url}/rest/v1/queue_entries"
                f"?device_id=eq.{self._device_id}"
                f"&status=eq.waiting"
                f"&select=id"
            )
            resp = self._client.get(url, headers={"Prefer": "count=exact"})
            count = resp.headers.get("content-range", "*/0").split("/")[-1]
            return int(count) if count != "*" else 0
        except Exception:
            return 0

    def _estimate_wait(self) -> int:
        return self._get_waiting_count() * AVG_INTERACTION_MINUTES

    def _update_status(self, entry_id: str, status: str) -> None:
        from datetime import datetime, timezone
        update: dict = {"status": status}
        if status == "now_serving":
            update["called_at"] = datetime.now(timezone.utc).isoformat()
        elif status in ("completed", "no_show", "cancelled"):
            update["completed_at"] = datetime.now(timezone.utc).isoformat()

        try:
            url = f"{self._supabase_url}/rest/v1/queue_entries?id=eq.{entry_id}"
            self._client.patch(url, json=update, headers={"Prefer": "return=minimal"}).raise_for_status()
        except Exception:
            log.exception("queue_status_update_failed", id=entry_id)

    def _load_today_count(self) -> None:
        """Load today's ticket count to resume numbering."""
        try:
            today = date.today().isoformat()
            url = (
                f"{self._supabase_url}/rest/v1/queue_entries"
                f"?device_id=eq.{self._device_id}"
                f"&created_at=gte.{today}T00:00:00Z"
                f"&order=ticket_number.desc"
                f"&limit=1"
                f"&select=ticket_number"
            )
            resp = self._client.get(url)
            resp.raise_for_status()
            rows = resp.json()
            self._today_ticket_count = rows[0]["ticket_number"] if rows else 0
        except Exception:
            self._today_ticket_count = 0

    def _resolve_riding(self, postal_code: str) -> tuple[str, str]:
        """Resolve riding from postal code."""
        try:
            import re
            clean = postal_code.replace(" ", "").upper()
            # Validate Canadian postal code format to prevent path traversal
            if not re.match(r"^[A-Z]\d[A-Z]\d[A-Z]\d$", clean):
                log.warning("invalid_postal_code", postal_code=postal_code)
                return "", ""
            resp = httpx.get(f"https://represent.opennorth.ca/postcodes/{clean}/", timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            for boundary in data.get("boundaries_concordance", data.get("boundaries_centroid", [])):
                if "Federal" in boundary.get("boundary_set_name", ""):
                    return boundary.get("name", ""), boundary.get("external_id", "")
        except Exception:
            log.warning("riding_resolve_failed", postal_code=postal_code)
        return "", ""
