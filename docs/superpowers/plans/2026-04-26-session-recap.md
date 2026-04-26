# Session Recap & QR Takeaway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store kiosk conversations in SQLite, display a QR code after each session, and serve a mobile recap page so users can take their conversation home.

**Architecture:** SQLite for local session storage on each Pi, background sync to Supabase. Flask serves the recap page and QR code. SocketIO pushes session events to the display. Keyboard overlay enables typed input without leaving voice mode.

**Tech Stack:** Python 3.11, SQLite3, Flask, Flask-SocketIO, httpx, qrcode, Jinja2, vanilla JS/CSS

---

### Task 1: Session Store (SQLite)

**Files:**
- Create: `src/gordie_voice/sessions/__init__.py`
- Create: `src/gordie_voice/sessions/store.py`
- Test: `tests/test_session_store.py`

- [ ] **Step 1: Write failing tests for SessionStore**

```python
# tests/test_session_store.py
"""Tests for SQLite session storage."""

import json
import os
import tempfile

import pytest

from gordie_voice.sessions.store import SessionStore


@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = SessionStore(db_path=path)
    yield s
    s.close()
    os.unlink(path)


class TestSessionLifecycle:
    def test_create_session(self, store):
        session_id = store.create_session("gordie-001")
        assert session_id is not None
        session = store.get_session(session_id)
        assert session["device_id"] == "gordie-001"
        assert session["ended_at"] is None
        assert session["scanned"] == 0

    def test_add_message(self, store):
        sid = store.create_session("gordie-001")
        store.add_message(sid, "user", "What is Bill C-21?")
        store.add_message(sid, "gordie", "Bill C-21 is...", sources=[{"title": "Bill C-21", "url": "https://canadagpt.ca/n/c-21"}])
        messages = store.get_messages(sid)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "gordie"
        assert json.loads(messages[1]["sources"])[0]["title"] == "Bill C-21"

    def test_end_session(self, store):
        sid = store.create_session("gordie-001")
        store.add_message(sid, "user", "Q1")
        store.add_message(sid, "gordie", "A1")
        store.add_message(sid, "user", "Q2")
        store.add_message(sid, "gordie", "A2")
        store.end_session(sid)
        session = store.get_session(sid)
        assert session["ended_at"] is not None
        assert session["topic_count"] == 2

    def test_mark_scanned(self, store):
        sid = store.create_session("gordie-001")
        store.end_session(sid)
        store.mark_scanned(sid)
        session = store.get_session(sid)
        assert session["scanned"] == 1
        # expires_at should be extended to ~30 days from now
        from datetime import datetime, timedelta
        expires = datetime.fromisoformat(session["expires_at"])
        assert expires > datetime.utcnow() + timedelta(days=29)

    def test_delete_session(self, store):
        sid = store.create_session("gordie-001")
        store.add_message(sid, "user", "test")
        store.delete_session(sid)
        assert store.get_session(sid) is None
        assert store.get_messages(sid) == []

    def test_get_unsynced_sessions(self, store):
        sid1 = store.create_session("gordie-001")
        store.end_session(sid1)
        sid2 = store.create_session("gordie-001")
        # sid2 not ended yet — should not appear
        unsynced = store.get_unsynced_sessions()
        assert len(unsynced) == 1
        assert unsynced[0]["id"] == sid1

    def test_cleanup_expired(self, store):
        sid = store.create_session("gordie-001")
        store.add_message(sid, "user", "old")
        # Force expire
        store._execute(
            "UPDATE sessions SET expires_at = '2020-01-01T00:00:00' WHERE id = ?",
            (sid,),
        )
        deleted = store.cleanup_expired()
        assert deleted == 1
        assert store.get_session(sid) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/matthewdufresne/askgordie && python -m pytest tests/test_session_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gordie_voice.sessions'`

- [ ] **Step 3: Implement SessionStore**

```python
# src/gordie_voice/sessions/__init__.py
# (empty)
```

```python
# src/gordie_voice/sessions/store.py
"""SQLite session storage for kiosk conversations."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any

import structlog

log = structlog.get_logger()

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    topic_count INTEGER DEFAULT 0,
    synced INTEGER DEFAULT 0,
    expires_at TEXT NOT NULL,
    scanned INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_synced ON sessions(synced) WHERE synced = 0;
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
"""


class SessionStore:
    """Thread-safe SQLite session storage."""

    def __init__(self, db_path: str = "/opt/gordie-voice/data/sessions.db") -> None:
        self._db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript(SCHEMA)
        conn.commit()

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        conn = self._get_conn()
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor

    def create_session(self, device_id: str) -> str:
        session_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        expires = (datetime.utcnow() + timedelta(hours=24)).isoformat()
        self._execute(
            "INSERT INTO sessions (id, device_id, started_at, expires_at) VALUES (?, ?, ?, ?)",
            (session_id, device_id, now, expires),
        )
        log.info("session_created", session_id=session_id, device_id=device_id)
        return session_id

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        sources: list[dict[str, str]] | None = None,
    ) -> None:
        now = datetime.utcnow().isoformat()
        sources_json = json.dumps(sources or [])
        self._execute(
            "INSERT INTO messages (session_id, role, content, sources, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, sources_json, now),
        )

    def end_session(self, session_id: str) -> None:
        now = datetime.utcnow().isoformat()
        conn = self._get_conn()
        topic_count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ? AND role = 'user'",
            (session_id,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE sessions SET ended_at = ?, topic_count = ? WHERE id = ?",
            (now, topic_count, session_id),
        )
        conn.commit()
        log.info("session_ended", session_id=session_id, topic_count=topic_count)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self._get_conn().execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._get_conn().execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_scanned(self, session_id: str) -> None:
        expires = (datetime.utcnow() + timedelta(days=30)).isoformat()
        self._execute(
            "UPDATE sessions SET scanned = 1, expires_at = ? WHERE id = ?",
            (expires, session_id),
        )
        log.info("session_scanned", session_id=session_id)

    def mark_synced(self, session_id: str) -> None:
        self._execute(
            "UPDATE sessions SET synced = 1 WHERE id = ?", (session_id,)
        )

    def get_unsynced_sessions(self) -> list[dict[str, Any]]:
        rows = self._get_conn().execute(
            "SELECT * FROM sessions WHERE synced = 0 AND ended_at IS NOT NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str) -> None:
        self._execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        log.info("session_deleted", session_id=session_id)

    def cleanup_expired(self) -> int:
        now = datetime.utcnow().isoformat()
        cursor = self._execute(
            "DELETE FROM sessions WHERE expires_at < ? AND scanned = 0",
            (now,),
        )
        count = cursor.rowcount
        if count:
            log.info("sessions_cleaned_up", count=count)
        return count

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/matthewdufresne/askgordie && python -m pytest tests/test_session_store.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/matthewdufresne/askgordie
git add src/gordie_voice/sessions/ tests/test_session_store.py
git commit -m "feat: add SQLite session store for kiosk conversations"
```

---

### Task 2: Supabase Sync & Cleanup Threads

**Files:**
- Create: `src/gordie_voice/sessions/sync.py`
- Create: `src/gordie_voice/sessions/cleanup.py`
- Test: `tests/test_session_sync.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_session_sync.py
"""Tests for session sync and cleanup background threads."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from gordie_voice.sessions.store import SessionStore
from gordie_voice.sessions.sync import SessionSync
from gordie_voice.sessions.cleanup import SessionCleanup


@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = SessionStore(db_path=path)
    yield s
    s.close()
    os.unlink(path)


class TestSessionSync:
    def test_sync_pushes_ended_sessions(self, store):
        sid = store.create_session("gordie-001")
        store.add_message(sid, "user", "test question")
        store.add_message(sid, "gordie", "test answer")
        store.end_session(sid)

        mock_client = MagicMock()
        mock_client.post.return_value = MagicMock(status_code=201, json=lambda: {})
        sync = SessionSync(store, supabase_url="https://test.supabase.co", supabase_key="test-key")
        sync._client = mock_client

        synced = sync.sync_once()
        assert synced == 1
        assert store.get_session(sid)["synced"] == 1

    def test_sync_skips_unended_sessions(self, store):
        store.create_session("gordie-001")  # not ended
        sync = SessionSync(store, supabase_url="https://test.supabase.co", supabase_key="test-key")
        synced = sync.sync_once()
        assert synced == 0

    def test_sync_handles_failure(self, store):
        sid = store.create_session("gordie-001")
        store.end_session(sid)

        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("connection failed")
        sync = SessionSync(store, supabase_url="https://test.supabase.co", supabase_key="test-key")
        sync._client = mock_client

        synced = sync.sync_once()
        assert synced == 0
        assert store.get_session(sid)["synced"] == 0  # still unsynced


class TestSessionCleanup:
    def test_cleanup_removes_expired_unscanned(self, store):
        sid = store.create_session("gordie-001")
        store.add_message(sid, "user", "old question")
        store._execute(
            "UPDATE sessions SET expires_at = '2020-01-01T00:00:00' WHERE id = ?",
            (sid,),
        )

        cleanup = SessionCleanup(store)
        deleted = cleanup.run_once()
        assert deleted == 1
        assert store.get_session(sid) is None

    def test_cleanup_preserves_scanned(self, store):
        sid = store.create_session("gordie-001")
        store.end_session(sid)
        store.mark_scanned(sid)
        store._execute(
            "UPDATE sessions SET expires_at = '2020-01-01T00:00:00' WHERE id = ?",
            (sid,),
        )

        cleanup = SessionCleanup(store)
        deleted = cleanup.run_once()
        assert deleted == 0  # scanned sessions are not cleaned up by unscanned query
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/matthewdufresne/askgordie && python -m pytest tests/test_session_sync.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement sync and cleanup**

```python
# src/gordie_voice/sessions/sync.py
"""Background thread to sync sessions to Supabase."""

from __future__ import annotations

import json
import threading
import time
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from gordie_voice.sessions.store import SessionStore

log = structlog.get_logger()


class SessionSync:
    """Periodically pushes ended sessions to Supabase."""

    def __init__(
        self,
        store: SessionStore,
        supabase_url: str,
        supabase_key: str,
        interval_s: int = 60,
    ) -> None:
        self._store = store
        self._url = supabase_url.rstrip("/")
        self._key = supabase_key
        self._interval = interval_s
        self._client = httpx.Client(
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            timeout=15.0,
        )
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("session_sync_started", interval_s=self._interval)

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            try:
                self.sync_once()
            except Exception:
                log.exception("session_sync_error")
            time.sleep(self._interval)

    def sync_once(self) -> int:
        unsynced = self._store.get_unsynced_sessions()
        if not unsynced:
            return 0

        synced_count = 0
        for session in unsynced:
            try:
                messages = self._store.get_messages(session["id"])

                # Push session
                self._client.post(
                    f"{self._url}/rest/v1/kiosk_sessions",
                    content=json.dumps({
                        "id": session["id"],
                        "device_id": session["device_id"],
                        "started_at": session["started_at"],
                        "ended_at": session["ended_at"],
                        "topic_count": session["topic_count"],
                        "scanned": bool(session["scanned"]),
                        "expires_at": session["expires_at"],
                    }),
                )

                # Push messages
                if messages:
                    self._client.post(
                        f"{self._url}/rest/v1/kiosk_messages",
                        content=json.dumps([
                            {
                                "session_id": m["session_id"],
                                "role": m["role"],
                                "content": m["content"],
                                "sources": m["sources"],
                                "created_at": m["created_at"],
                            }
                            for m in messages
                        ]),
                    )

                self._store.mark_synced(session["id"])
                synced_count += 1
                log.info("session_synced", session_id=session["id"])

            except Exception:
                log.warning("session_sync_failed", session_id=session["id"])

        return synced_count
```

```python
# src/gordie_voice/sessions/cleanup.py
"""Hourly cleanup of expired sessions."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from gordie_voice.sessions.store import SessionStore

log = structlog.get_logger()


class SessionCleanup:
    """Periodically removes expired unscanned sessions."""

    def __init__(self, store: SessionStore, interval_s: int = 3600) -> None:
        self._store = store
        self._interval = interval_s
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("session_cleanup_started", interval_s=self._interval)

    def stop(self) -> None:
        self._running = False

    def _loop(self) -> None:
        while self._running:
            try:
                self.run_once()
            except Exception:
                log.exception("session_cleanup_error")
            time.sleep(self._interval)

    def run_once(self) -> int:
        return self._store.cleanup_expired()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/matthewdufresne/askgordie && python -m pytest tests/test_session_sync.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/matthewdufresne/askgordie
git add src/gordie_voice/sessions/sync.py src/gordie_voice/sessions/cleanup.py tests/test_session_sync.py
git commit -m "feat: add Supabase sync and cleanup threads for sessions"
```

---

### Task 3: Integrate SessionStore into App

**Files:**
- Modify: `src/gordie_voice/__main__.py`
- Modify: `src/gordie_voice/app.py`
- Modify: `src/gordie_voice/display/persona.py`

- [ ] **Step 1: Add SessionStore initialization to `__main__.py`**

Add after the device registry block (around line 80), before `GordieApp` construction:

```python
# Session storage
from gordie_voice.sessions.store import SessionStore
import os
os.makedirs("/opt/gordie-voice/data", exist_ok=True)
session_store = SessionStore()
```

Add `session_store=session_store` to the `GordieApp(...)` constructor call.

After the app construction, add sync and cleanup:

```python
# Session sync to Supabase
if settings.supabase_url and settings.supabase_service_role_key:
    from gordie_voice.sessions.sync import SessionSync
    session_sync = SessionSync(session_store, settings.supabase_url, settings.supabase_service_role_key)
    session_sync.start()

# Session cleanup
from gordie_voice.sessions.cleanup import SessionCleanup
session_cleanup = SessionCleanup(session_store)
session_cleanup.start()
```

Pass session_store to persona:

```python
if persona:
    persona.set_session_store(session_store)
```

- [ ] **Step 2: Add session lifecycle to `app.py`**

Add `session_store` parameter to `GordieApp.__init__`:

```python
def __init__(self, ..., session_store=None):
    ...
    self.session_store = session_store
    self._session_id: str | None = None
```

In the IDLE → LISTENING transition (wake detected), create a new session:

```python
if frames is not None and self.wake.detect(frames):
    log.info("wake_detected")
    # Create new session if we don't have one
    if self.session_store and not self._session_id:
        self._session_id = self.session_store.create_session(self.settings.device_id)
    ...
```

In `_transcribe_and_respond`, after transcription save user message:

```python
if self.session_store and self._session_id:
    self.session_store.add_message(self._session_id, "user", transcript)
```

After TTS response completes (before `_offer_follow_up`), save gordie message:

```python
if self.session_store and self._session_id:
    self.session_store.add_message(self._session_id, "gordie", " ".join(all_sentences))
```

When conversation ends (in `_handle_follow_up_intent` done branch, and on presence loss idle transition), end the session and emit QR event:

```python
def _end_current_session(self) -> None:
    if self.session_store and self._session_id:
        self.session_store.end_session(self._session_id)
        if self.persona:
            self.persona.emit_session_qr(self._session_id)
        self._session_id = None
```

Call `_end_current_session()` in:
- The "done" branch of `_handle_follow_up_intent`
- When presence detector switches to PROMPT mode from VOICE (user walked away)

- [ ] **Step 3: Run existing tests**

Run: `cd /Users/matthewdufresne/askgordie && python -m pytest tests/ -v`
Expected: All existing tests still pass

- [ ] **Step 4: Commit**

```bash
cd /Users/matthewdufresne/askgordie
git add src/gordie_voice/__main__.py src/gordie_voice/app.py
git commit -m "feat: integrate session store into app lifecycle"
```

---

### Task 4: Flask Routes for Recap Page & QR

**Files:**
- Modify: `src/gordie_voice/display/persona.py`
- Create: `src/gordie_voice/display/templates/session.html`
- Create: `src/gordie_voice/display/static/css/session.css`

- [ ] **Step 1: Add session routes to `persona.py`**

Add `set_session_store` method and new routes to `PersonaServer`:

```python
def set_session_store(self, store) -> None:
    self._session_store = store
```

In `_setup_routes`, add:

```python
@self.flask.route("/s/<session_id>")
def session_recap(session_id):
    if not self._session_store:
        return "Sessions not available", 503
    session = self._session_store.get_session(session_id)
    if not session:
        return "Session not found or expired", 404
    messages = self._session_store.get_messages(session_id)
    # Mark as scanned (extends expiry)
    self._session_store.mark_scanned(session_id)
    # Calculate duration
    from datetime import datetime
    started = datetime.fromisoformat(session["started_at"])
    ended = datetime.fromisoformat(session["ended_at"]) if session["ended_at"] else datetime.utcnow()
    duration_min = max(1, round((ended - started).total_seconds() / 60))
    # Riding info
    riding_name = None
    if self._device_registry:
        riding_name = self._device_registry.riding_name
    return render_template(
        "session.html",
        session=session,
        messages=messages,
        duration_min=duration_min,
        riding_name=riding_name,
    )

@self.flask.route("/s/<session_id>/delete", methods=["POST"])
def session_delete(session_id):
    if not self._session_store:
        return "Sessions not available", 503
    self._session_store.delete_session(session_id)
    return render_template("session.html", deleted=True)

@self.flask.route("/qr/session/<session_id>")
def qr_session(session_id):
    import io
    import qrcode
    host = _get_lan_ip()
    port = self.config.port
    url = f"http://{host}:{port}/s/{session_id}"
    qr = qrcode.QRCode(version=1, box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#EC2024", back_color="#0a0a0f")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png")
```

Add `emit_session_qr` method:

```python
def emit_session_qr(self, session_id: str) -> None:
    self.socketio.emit("session_ended", {"session_id": session_id})
```

- [ ] **Step 2: Create session recap HTML template**

Create `src/gordie_voice/display/templates/session.html` with:
- AskGordie logo header
- Summary card ("You explored N topics in M minutes")
- Chat bubble messages with collapsible sources
- CTA to canadagpt.ca/register
- Share/PDF/delete buttons
- Privacy banner
- Full responsive mobile-first CSS

(See spec for complete layout requirements. Template renders `session`, `messages`, `duration_min`, `riding_name` variables.)

- [ ] **Step 3: Create session recap CSS**

Create `src/gordie_voice/display/static/css/session.css` with mobile-first styles for:
- Chat bubbles (user grey left, gordie red right)
- Summary card
- Source collapsibles
- CTA button
- Privacy banner
- Share/delete controls

- [ ] **Step 4: Test manually**

Run the app, create a session via the store directly, then visit `http://localhost:8080/s/<uuid>` in a browser.

- [ ] **Step 5: Commit**

```bash
cd /Users/matthewdufresne/askgordie
git add src/gordie_voice/display/persona.py src/gordie_voice/display/templates/session.html src/gordie_voice/display/static/css/session.css
git commit -m "feat: add session recap page and QR code routes"
```

---

### Task 5: QR Display on Kiosk Screen

**Files:**
- Modify: `src/gordie_voice/display/templates/persona.html`
- Modify: `src/gordie_voice/display/static/js/persona.js`
- Modify: `src/gordie_voice/display/static/css/badge-pulse.css`

- [ ] **Step 1: Add QR container to voice view in `persona.html`**

After the `#tap-to-wake` button, before `#waveform`:

```html
<!-- Session QR — appears after conversation ends -->
<div id="session-qr" class="session-qr hidden">
    <img id="session-qr-img" src="" alt="Scan to save your conversation" width="180" height="180">
    <p class="session-qr-cta">Scan to save your conversation</p>
</div>
```

- [ ] **Step 2: Add QR display logic to `persona.js`**

```javascript
// ---- Session QR ----

const sessionQr = document.getElementById('session-qr');
const sessionQrImg = document.getElementById('session-qr-img');
let sessionQrTimeout = null;

socket.on('session_ended', (data) => {
    if (!data.session_id || !sessionQr || !sessionQrImg) return;
    sessionQrImg.src = `/qr/session/${data.session_id}`;
    sessionQr.classList.remove('hidden');
    sessionQr.classList.add('fade-in');

    // Clear any existing timeout
    if (sessionQrTimeout) clearTimeout(sessionQrTimeout);

    // Auto-dismiss after 30 seconds if no new user
    sessionQrTimeout = setTimeout(() => {
        sessionQr.classList.add('hidden');
        sessionQr.classList.remove('fade-in');
    }, 30000);
});

// When new wake word detected, keep QR for 10 more seconds then dismiss
socket.on('state', (data) => {
    if (data.state === 'listening' && !sessionQr.classList.contains('hidden')) {
        if (sessionQrTimeout) clearTimeout(sessionQrTimeout);
        sessionQrTimeout = setTimeout(() => {
            sessionQr.classList.add('hidden');
            sessionQr.classList.remove('fade-in');
        }, 10000);
    }
});
```

- [ ] **Step 3: Add QR positioning and fade CSS to `badge-pulse.css`**

```css
/* Session QR */
.session-qr {
    position: fixed;
    bottom: 40px;
    right: 40px;
    text-align: center;
    z-index: 10;
    transition: opacity 0.5s ease;
}

.session-qr.hidden {
    opacity: 0;
    pointer-events: none;
}

.session-qr.fade-in {
    opacity: 1;
}

.session-qr img {
    border-radius: 12px;
    box-shadow: 0 4px 24px rgba(236, 32, 36, 0.3);
}

.session-qr-cta {
    margin-top: 8px;
    color: rgba(255, 255, 255, 0.7);
    font-size: 0.9rem;
}
```

- [ ] **Step 4: Test on Pi**

Deploy files, restart service, have a conversation, verify QR appears after goodbye.

- [ ] **Step 5: Commit**

```bash
cd /Users/matthewdufresne/askgordie
git add src/gordie_voice/display/templates/persona.html src/gordie_voice/display/static/js/persona.js src/gordie_voice/display/static/css/badge-pulse.css
git commit -m "feat: display session QR code after conversation ends"
```

---

### Task 6: Keyboard Prompt Overlay

**Files:**
- Modify: `src/gordie_voice/display/templates/persona.html`
- Modify: `src/gordie_voice/display/static/js/persona.js`
- Modify: `src/gordie_voice/display/static/css/badge-pulse.css`
- Modify: `src/gordie_voice/app.py`

- [ ] **Step 1: Add keyboard input bar to `persona.html`**

After the voice view branding div:

```html
<!-- Keyboard prompt overlay — appears on keypress in voice mode -->
<div id="keyboard-prompt" class="keyboard-prompt hidden">
    <form id="keyboard-form">
        <input type="text" id="keyboard-input" placeholder="Type your question..."
               autocomplete="off" enterkeyhint="send">
        <button type="submit" aria-label="Send">
            <svg viewBox="0 0 24 24" width="24" height="24" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
            </svg>
        </button>
    </form>
</div>
```

- [ ] **Step 2: Add keyboard listener to `persona.js`**

```javascript
// ---- Keyboard prompt overlay ----

const keyboardPrompt = document.getElementById('keyboard-prompt');
const keyboardInput = document.getElementById('keyboard-input');
const keyboardForm = document.getElementById('keyboard-form');

document.addEventListener('keydown', (e) => {
    // Only trigger in voice view, idle state, with alphanumeric keys
    if (body.dataset.mode !== 'voice') return;
    if (!keyboardPrompt.classList.contains('hidden')) return;
    if (e.key === 'Escape' || e.key === 'Tab' || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key.length !== 1) return;  // Only single character keys

    keyboardPrompt.classList.remove('hidden');
    keyboardInput.value = e.key;
    keyboardInput.focus();
    // Move cursor to end
    keyboardInput.setSelectionRange(1, 1);
    e.preventDefault();
});

// Escape dismisses
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !keyboardPrompt.classList.contains('hidden')) {
        keyboardPrompt.classList.add('hidden');
        keyboardInput.value = '';
    }
});

// Submit sends prompt and dismisses
keyboardForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = keyboardInput.value.trim();
    if (!text) return;
    socket.emit('prompt_submit', { text });
    keyboardInput.value = '';
    keyboardPrompt.classList.add('hidden');
});

// Auto-dismiss when Gordie starts speaking
socket.on('state', (data) => {
    if (data.state === 'speaking' && !keyboardPrompt.classList.contains('hidden')) {
        keyboardPrompt.classList.add('hidden');
        keyboardInput.value = '';
    }
});
```

- [ ] **Step 3: Add keyboard overlay CSS**

```css
/* Keyboard prompt overlay */
.keyboard-prompt {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    padding: 20px 24px;
    background: rgba(10, 10, 15, 0.95);
    border-top: 1px solid rgba(236, 32, 36, 0.3);
    z-index: 100;
    transition: transform 0.2s ease, opacity 0.2s ease;
}

.keyboard-prompt.hidden {
    transform: translateY(100%);
    opacity: 0;
    pointer-events: none;
}

.keyboard-prompt form {
    display: flex;
    gap: 12px;
    max-width: 800px;
    margin: 0 auto;
}

.keyboard-prompt input {
    flex: 1;
    padding: 14px 18px;
    font-size: 1.1rem;
    border: 1px solid rgba(236, 32, 36, 0.4);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.05);
    color: white;
    outline: none;
}

.keyboard-prompt input:focus {
    border-color: #EC2024;
}

.keyboard-prompt button {
    padding: 14px 18px;
    background: #EC2024;
    color: white;
    border: none;
    border-radius: 8px;
    cursor: pointer;
}
```

- [ ] **Step 4: Route keyboard prompts through voice pipeline in `app.py`**

Modify `handle_prompt_query` to speak the response when in voice mode:

```python
def handle_prompt_query(self, text: str) -> None:
    """Handle a text query from keyboard or prompt mode."""
    try:
        # Save user message
        if self.session_store and self._session_id:
            self.session_store.add_message(self._session_id, "user", text)

        self._set_state(State.QUERYING)
        if self.settings.canadagpt.streaming:
            self._set_state(State.SPEAKING)
            self.playback.stop()  # Stop thinking music
            all_text = []
            for chunk in self.client.query_stream(text):
                if self._barge_in.is_set():
                    return
                shaped = self.shaper.shape(chunk)
                for sentence in shaped:
                    if self._barge_in.is_set():
                        return
                    all_text.append(sentence)
                    audio_data = self.tts.synthesize(sentence)
                    self.playback.play(audio_data)
                    if self.persona:
                        self.persona.broadcast_response_chunk(sentence + " ")
            if self.persona:
                self.persona.broadcast_response_done()

            # Save gordie message
            if self.session_store and self._session_id:
                self.session_store.add_message(self._session_id, "gordie", " ".join(all_text))
        else:
            response = self.client.query(text)
            shaped_sentences = self.shaper.shape(response)
            self._set_state(State.SPEAKING)
            self.playback.stop()
            for sentence in shaped_sentences:
                if self._barge_in.is_set():
                    return
                audio_data = self.tts.synthesize(sentence)
                self.playback.play(audio_data)
            if self.persona:
                self.persona.broadcast_response_chunk(response)
                self.persona.broadcast_response_done()
            if self.session_store and self._session_id:
                self.session_store.add_message(self._session_id, "gordie", response)

        self._offer_follow_up()
    except Exception:
        log.exception("prompt_query_error")
        self._set_state(State.ERROR)
```

- [ ] **Step 5: Test on Pi**

Deploy, restart, type on keyboard while badge is showing. Verify input bar appears, question submits, Gordie speaks the answer.

- [ ] **Step 6: Commit**

```bash
cd /Users/matthewdufresne/askgordie
git add src/gordie_voice/display/templates/persona.html src/gordie_voice/display/static/js/persona.js src/gordie_voice/display/static/css/badge-pulse.css src/gordie_voice/app.py
git commit -m "feat: keyboard prompt overlay with voice response"
```

---

### Task 7: Supabase Migration

**Files:**
- Create: `supabase/migrations/006_kiosk_sessions.sql`

- [ ] **Step 1: Write the migration**

```sql
-- supabase/migrations/006_kiosk_sessions.sql
-- Kiosk session storage for AskGordie devices

CREATE TABLE kiosk_sessions (
    id UUID PRIMARY KEY,
    device_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    topic_count INTEGER DEFAULT 0,
    scanned BOOLEAN DEFAULT FALSE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE kiosk_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES kiosk_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'gordie')),
    content TEXT NOT NULL,
    sources JSONB DEFAULT '[]'::JSONB,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_kiosk_messages_session ON kiosk_messages(session_id);
CREATE INDEX idx_kiosk_sessions_device ON kiosk_sessions(device_id);
CREATE INDEX idx_kiosk_sessions_expires ON kiosk_sessions(expires_at);

-- RLS: service role can insert (from kiosk sync), anon can read (for recap page)
ALTER TABLE kiosk_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE kiosk_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role can manage sessions"
    ON kiosk_sessions FOR ALL
    USING (auth.role() = 'service_role');

CREATE POLICY "Anyone can read sessions by ID"
    ON kiosk_sessions FOR SELECT
    USING (true);

CREATE POLICY "Service role can manage messages"
    ON kiosk_messages FOR ALL
    USING (auth.role() = 'service_role');

CREATE POLICY "Anyone can read messages by session"
    ON kiosk_messages FOR SELECT
    USING (true);
```

- [ ] **Step 2: Commit**

```bash
cd /Users/matthewdufresne/askgordie
git add supabase/migrations/006_kiosk_sessions.sql
git commit -m "feat: add Supabase migration for kiosk sessions"
```

---

### Task 8: Privacy Notice on Kiosk Display

**Files:**
- Modify: `src/gordie_voice/display/templates/persona.html`
- Modify: `src/gordie_voice/display/static/css/badge-pulse.css`

- [ ] **Step 1: Add privacy notice to voice view**

In `persona.html`, after the branding div:

```html
<!-- Privacy notice -->
<div id="privacy-notice" class="privacy-notice">
    This conversation is temporarily stored. Scan the QR code to save it, or it will be automatically deleted.
</div>
```

- [ ] **Step 2: Style the privacy notice**

```css
.privacy-notice {
    position: fixed;
    bottom: 12px;
    left: 50%;
    transform: translateX(-50%);
    color: rgba(255, 255, 255, 0.35);
    font-size: 0.75rem;
    text-align: center;
    max-width: 500px;
    padding: 0 20px;
}
```

- [ ] **Step 3: Commit**

```bash
cd /Users/matthewdufresne/askgordie
git add src/gordie_voice/display/templates/persona.html src/gordie_voice/display/static/css/badge-pulse.css
git commit -m "feat: add PIPEDA privacy notice to kiosk display"
```

---

### Task 9: Deploy & End-to-End Test

- [ ] **Step 1: Push all changes to GitHub**

```bash
cd /Users/matthewdufresne/askgordie
git push origin main
```

- [ ] **Step 2: Pull on Pi and restart**

```bash
ssh matthewdufresne@10.0.0.46 "cd /opt/gordie-voice && git pull origin main && sudo systemctl restart gordie-voice && sudo systemctl restart gordie-display"
```

- [ ] **Step 3: End-to-end test checklist**

1. Say "hey jarvis" → hear O Canada chime
2. Ask a question → hear Jeopardy thinking music → Gordie speaks response
3. Say goodbye → QR code appears alongside badge
4. Scan QR on phone → see recap page with conversation
5. Verify recap shows summary card, chat bubbles, sources, CTA
6. Tap "Delete this session" → session removed
7. Type on keyboard → input bar appears → Gordie speaks response
8. Walk away → QR persists briefly then fades
9. New wake word → QR stays 10s then fades, new session starts
10. Check SQLite: `sqlite3 /opt/gordie-voice/data/sessions.db "SELECT * FROM sessions;"`
