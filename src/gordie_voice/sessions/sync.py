"""Background thread that syncs ended sessions to Supabase."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    pass

import httpx

from gordie_voice.sessions.store import SessionStore

log = structlog.get_logger(__name__)


class SessionSync:
    """Periodically syncs unsynced ended sessions to Supabase REST API."""

    def __init__(
        self,
        store: SessionStore,
        supabase_url: str,
        supabase_key: str,
        interval_s: int = 60,
    ) -> None:
        self._store = store
        self._url = supabase_url.rstrip("/")
        self._interval_s = interval_s
        self._running = False
        self._thread: threading.Thread | None = None
        self._client = httpx.Client(
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            }
        )

    def start(self) -> None:
        """Launch daemon thread running _loop()."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="session-sync")
        self._thread.start()
        log.info("session_sync.started", interval_s=self._interval_s)

    def stop(self) -> None:
        """Signal the sync loop to stop."""
        self._running = False
        log.info("session_sync.stopped")

    def _loop(self) -> None:
        """Continuously call sync_once() every interval_s seconds."""
        while self._running:
            try:
                synced = self.sync_once()
                if synced:
                    log.info("session_sync.cycle", synced=synced)
            except Exception:
                log.exception("session_sync.loop_error")
            time.sleep(self._interval_s)

    def sync_once(self) -> int:
        """Sync all unsynced ended sessions to Supabase.

        POSTs each session row to kiosk_sessions and its messages to
        kiosk_messages, then marks the session synced.

        Returns:
            Number of sessions successfully synced.
        """
        sessions = self._store.get_unsynced_sessions()
        synced_count = 0

        for session in sessions:
            session_id = session["id"]
            try:
                # POST session row
                resp = self._client.post(
                    f"{self._url}/rest/v1/kiosk_sessions",
                    json=session,
                )
                resp.raise_for_status()

                # POST messages
                messages = self._store.get_messages(session_id)
                if messages:
                    resp = self._client.post(
                        f"{self._url}/rest/v1/kiosk_messages",
                        json=messages,
                    )
                    resp.raise_for_status()

                self._store.mark_synced(session_id)
                synced_count += 1
                log.debug("session_sync.synced", session_id=session_id)
            except Exception:
                log.warning("session_sync.failed", session_id=session_id)

        return synced_count
