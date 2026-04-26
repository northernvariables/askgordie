"""Tests for SessionSync and SessionCleanup — written first (TDD)."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from gordie_voice.sessions.cleanup import SessionCleanup
from gordie_voice.sessions.store import SessionStore
from gordie_voice.sessions.sync import SessionSync


@pytest.fixture
def store():
    """Create a SessionStore backed by a temp file; clean up after."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = SessionStore(db_path=path)
    yield s
    s.close()
    os.unlink(path)


@pytest.fixture
def sync(store):
    """Create a SessionSync with a mocked httpx.Client."""
    syncer = SessionSync(
        store=store,
        supabase_url="https://fake.supabase.co",
        supabase_key="fake-key",
        interval_s=60,
    )
    return syncer


# ---------------------------------------------------------------------------
# 1. test_sync_pushes_ended_sessions
# ---------------------------------------------------------------------------

def test_sync_pushes_ended_sessions(store, sync):
    """sync_once() should sync one ended session and return count=1."""
    session_id = store.create_session(device_id="pi-001")
    store.add_message(session_id, role="user", content="Hello Gordie")
    store.add_message(session_id, role="gordie", content="Hello!")
    store.end_session(session_id)

    # Mock the httpx client so no real HTTP calls are made
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None

    mock_client = MagicMock()
    mock_client.post.return_value = mock_response
    sync._client = mock_client

    result = sync.sync_once()

    assert result == 1

    # Verify session is now marked synced
    session = store.get_session(session_id)
    assert session["synced"] == 1

    # Verify two POST calls: one for session, one for messages
    assert mock_client.post.call_count == 2
    calls = [call[0][0] for call in mock_client.post.call_args_list]
    assert any("kiosk_sessions" in url for url in calls)
    assert any("kiosk_messages" in url for url in calls)


# ---------------------------------------------------------------------------
# 2. test_sync_skips_unended_sessions
# ---------------------------------------------------------------------------

def test_sync_skips_unended_sessions(store, sync):
    """sync_once() should return 0 when no sessions have been ended."""
    store.create_session(device_id="pi-002")
    # Session is NOT ended — should not be synced

    mock_client = MagicMock()
    sync._client = mock_client

    result = sync.sync_once()

    assert result == 0
    mock_client.post.assert_not_called()


# ---------------------------------------------------------------------------
# 3. test_sync_handles_failure
# ---------------------------------------------------------------------------

def test_sync_handles_failure(store, sync):
    """sync_once() should leave session unsynced when HTTP call raises."""
    session_id = store.create_session(device_id="pi-003")
    store.end_session(session_id)

    mock_client = MagicMock()
    mock_client.post.side_effect = Exception("connection refused")
    sync._client = mock_client

    # Should NOT raise — failure is caught and logged as a warning
    result = sync.sync_once()

    assert result == 0

    # Session must remain unsynced
    session = store.get_session(session_id)
    assert session["synced"] == 0


# ---------------------------------------------------------------------------
# 4. test_cleanup_removes_expired_unscanned
# ---------------------------------------------------------------------------

def test_cleanup_removes_expired_unscanned(store):
    """run_once() should delete sessions whose expires_at is in the past."""
    session_id = store.create_session(device_id="pi-004")

    # Force-expire by writing expires_at into the past
    past = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    store._execute(
        "UPDATE sessions SET expires_at = ? WHERE id = ?",
        (past, session_id),
    )

    cleanup = SessionCleanup(store=store, interval_s=3600)
    deleted = cleanup.run_once()

    assert deleted >= 1
    assert store.get_session(session_id) is None
