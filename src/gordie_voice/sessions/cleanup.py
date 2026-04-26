"""Background thread that deletes expired unscanned sessions from the store."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import structlog

from gordie_voice.sessions.store import SessionStore

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)


class SessionCleanup:
    """Periodically removes expired, unscanned sessions from SQLite."""

    def __init__(
        self,
        store: SessionStore,
        interval_s: int = 3600,
    ) -> None:
        self._store = store
        self._interval_s = interval_s
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Launch daemon thread running _loop()."""
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="session-cleanup"
        )
        self._thread.start()
        log.info("session_cleanup.started", interval_s=self._interval_s)

    def stop(self) -> None:
        """Signal the cleanup loop to stop."""
        self._running = False
        log.info("session_cleanup.stopped")

    def _loop(self) -> None:
        """Continuously call run_once() every interval_s seconds."""
        while self._running:
            try:
                deleted = self.run_once()
                if deleted:
                    log.info("session_cleanup.cycle", deleted=deleted)
            except Exception:
                log.exception("session_cleanup.loop_error")
            time.sleep(self._interval_s)

    def run_once(self) -> int:
        """Delete expired unscanned sessions.

        Returns:
            Number of sessions deleted.
        """
        return self._store.cleanup_expired()
