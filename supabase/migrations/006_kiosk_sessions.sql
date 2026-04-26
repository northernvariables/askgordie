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
