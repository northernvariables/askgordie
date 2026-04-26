"""Thread-safe SQLite session store for Gordie voice kiosk conversations."""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

_DEFAULT_DB_PATH = "/opt/gordie-voice/data/sessions.db"

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    device_id   TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    topic_count INT  DEFAULT 0,
    synced      INT  DEFAULT 0,
    expires_at  TEXT NOT NULL,
    scanned     INT  DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    sources     TEXT    DEFAULT '[]',
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session  ON messages (session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_synced   ON sessions (synced) WHERE synced = 0;
CREATE INDEX IF NOT EXISTS idx_sessions_expires  ON sessions (expires_at);
"""


class SessionStore:
    """Thread-safe SQLite-backed session store.

    Each thread gets its own connection via ``threading.local()``.  WAL mode
    enables concurrent readers and a single writer without blocking.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._local = threading.local()
        # Initialise schema on the calling thread's connection.
        self._init_schema()
        log.info("session_store.ready", db_path=db_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        """Return (or create) the per-thread SQLite connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def _init_schema(self) -> None:
        conn = self._conn()
        conn.executescript(_SCHEMA_SQL)
        conn.commit()

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a write statement and commit."""
        conn = self._conn()
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_session(self, device_id: str) -> str:
        """Create a new session and return its UUID."""
        session_id = str(uuid.uuid4())
        now = self._now()
        expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat()
        self._execute(
            """
            INSERT INTO sessions (id, device_id, started_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, device_id, now, expires_at),
        )
        log.info("session.created", session_id=session_id, device_id=device_id)
        return session_id

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        sources: Optional[list] = None,
    ) -> None:
        """Append a message to a session."""
        self._execute(
            """
            INSERT INTO messages (session_id, role, content, sources, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content, json.dumps(sources or []), self._now()),
        )

    def end_session(self, session_id: str) -> None:
        """Mark the session as ended; count user messages as topic_count."""
        now = self._now()
        conn = self._conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role = 'user'",
            (session_id,),
        ).fetchone()
        topic_count = row[0] if row else 0
        self._execute(
            "UPDATE sessions SET ended_at = ?, topic_count = ? WHERE id = ?",
            (now, topic_count, session_id),
        )
        log.info("session.ended", session_id=session_id, topic_count=topic_count)

    def get_session(self, session_id: str) -> Optional[dict]:
        """Return the session as a dict, or None if not found."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_messages(self, session_id: str) -> list[dict]:
        """Return all messages for a session ordered by created_at."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_scanned(self, session_id: str) -> None:
        """Record that the user scanned the QR code; extend expiry to 30 days."""
        expires_at = (datetime.utcnow() + timedelta(days=30)).isoformat()
        self._execute(
            "UPDATE sessions SET scanned = 1, expires_at = ? WHERE id = ?",
            (expires_at, session_id),
        )
        log.info("session.scanned", session_id=session_id)

    def mark_synced(self, session_id: str) -> None:
        """Mark the session as synced to Supabase."""
        self._execute(
            "UPDATE sessions SET synced = 1 WHERE id = ?",
            (session_id,),
        )

    def get_unsynced_sessions(self) -> list[dict]:
        """Return all ended sessions that have not yet been synced."""
        conn = self._conn()
        rows = conn.execute(
            """
            SELECT * FROM sessions
            WHERE synced = 0 AND ended_at IS NOT NULL
            ORDER BY started_at ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str) -> None:
        """Delete a session and all its messages (cascade)."""
        self._execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        log.info("session.deleted", session_id=session_id)

    def cleanup_expired(self) -> int:
        """Delete sessions where expires_at < now AND scanned = 0.

        Returns the number of sessions deleted.
        """
        now = self._now()
        cursor = self._execute(
            "DELETE FROM sessions WHERE expires_at < ? AND scanned = 0",
            (now,),
        )
        count = cursor.rowcount
        if count:
            log.info("session.cleanup", deleted=count)
        return count

    def close(self) -> None:
        """Close the current thread's connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
