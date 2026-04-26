"""Tests for SQLite SessionStore — written first (TDD)."""

import json
import os
import tempfile
import time
from datetime import datetime, timedelta

import pytest

from gordie_voice.sessions.store import SessionStore


@pytest.fixture
def store():
    """Create a SessionStore backed by a temp file; clean up after."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = SessionStore(db_path=path)
    yield s
    s.close()
    os.unlink(path)


# ---------------------------------------------------------------------------
# 1. test_create_session
# ---------------------------------------------------------------------------

def test_create_session(store):
    session_id = store.create_session(device_id="pi-001")
    assert session_id  # non-empty string

    session = store.get_session(session_id)
    assert session is not None
    assert session["device_id"] == "pi-001"
    assert session["ended_at"] is None
    assert session["scanned"] == 0
    assert session["synced"] == 0
    # expires_at should be roughly 24 h from now
    expires = datetime.fromisoformat(session["expires_at"])
    now = datetime.utcnow()
    assert timedelta(hours=23) < (expires - now) < timedelta(hours=25)


# ---------------------------------------------------------------------------
# 2. test_add_message
# ---------------------------------------------------------------------------

def test_add_message(store):
    session_id = store.create_session(device_id="pi-002")

    store.add_message(session_id, role="user", content="Hello?")
    store.add_message(
        session_id,
        role="gordie",
        content="Hi there!",
        sources=[{"url": "https://example.com"}],
    )

    messages = store.get_messages(session_id)
    assert len(messages) == 2

    user_msg = messages[0]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "Hello?"
    assert json.loads(user_msg["sources"]) == []  # default

    gordie_msg = messages[1]
    assert gordie_msg["role"] == "gordie"
    assert json.loads(gordie_msg["sources"]) == [{"url": "https://example.com"}]


# ---------------------------------------------------------------------------
# 3. test_end_session
# ---------------------------------------------------------------------------

def test_end_session(store):
    session_id = store.create_session(device_id="pi-003")

    # 2 Q&A pairs → topic_count should be 2 (count of user messages)
    store.add_message(session_id, role="user", content="Q1")
    store.add_message(session_id, role="gordie", content="A1")
    store.add_message(session_id, role="user", content="Q2")
    store.add_message(session_id, role="gordie", content="A2")

    store.end_session(session_id)

    session = store.get_session(session_id)
    assert session["ended_at"] is not None
    assert session["topic_count"] == 2


# ---------------------------------------------------------------------------
# 4. test_mark_scanned
# ---------------------------------------------------------------------------

def test_mark_scanned(store):
    session_id = store.create_session(device_id="pi-004")
    store.mark_scanned(session_id)

    session = store.get_session(session_id)
    assert session["scanned"] == 1

    # expires_at should now be ~30 days from now
    expires = datetime.fromisoformat(session["expires_at"])
    now = datetime.utcnow()
    assert timedelta(days=29) < (expires - now) < timedelta(days=31)


# ---------------------------------------------------------------------------
# 5. test_delete_session
# ---------------------------------------------------------------------------

def test_delete_session(store):
    session_id = store.create_session(device_id="pi-005")
    store.add_message(session_id, role="user", content="Will be deleted")

    store.delete_session(session_id)

    assert store.get_session(session_id) is None
    assert store.get_messages(session_id) == []


# ---------------------------------------------------------------------------
# 6. test_get_unsynced_sessions
# ---------------------------------------------------------------------------

def test_get_unsynced_sessions(store):
    ended_id = store.create_session(device_id="pi-006")
    store.end_session(ended_id)

    active_id = store.create_session(device_id="pi-006")
    # active session is NOT ended — should not appear

    unsynced = store.get_unsynced_sessions()
    ids = [s["id"] for s in unsynced]
    assert ended_id in ids
    assert active_id not in ids

    # After marking synced it should disappear
    store.mark_synced(ended_id)
    unsynced2 = store.get_unsynced_sessions()
    ids2 = [s["id"] for s in unsynced2]
    assert ended_id not in ids2


# ---------------------------------------------------------------------------
# 7. test_cleanup_expired
# ---------------------------------------------------------------------------

def test_cleanup_expired(store):
    session_id = store.create_session(device_id="pi-007")

    # Force-expire by directly updating expires_at to the past
    past = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    store._execute(
        "UPDATE sessions SET expires_at = ? WHERE id = ?",
        (past, session_id),
    )

    deleted = store.cleanup_expired()
    assert deleted >= 1
    assert store.get_session(session_id) is None
