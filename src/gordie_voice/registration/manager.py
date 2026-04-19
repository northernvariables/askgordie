"""User registration via Supabase Auth phone OTP.

Flow:
1. User says "Register me" or taps register on display
2. Gordie asks for their phone number (voice or on-screen keypad)
3. We call Supabase Auth signInWithOtp({ phone })
4. Supabase sends an SMS code to the user's phone
5. User speaks or types the 6-digit code
6. We call Supabase Auth verifyOtp({ phone, token, type: 'sms' })
7. On success, store the session — user is now authenticated for CanadaGPT
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import Settings

log = structlog.get_logger()


class RegistrationManager:
    """Handles phone-based registration via Supabase Auth OTP."""

    def __init__(self, settings: Settings) -> None:
        self._supabase_url = settings.supabase_url
        self._supabase_anon_key = settings.supabase_anon_key
        self._timeout = settings.registration.verification_timeout_s
        self._code_length = settings.registration.code_length
        self._session: dict | None = None
        self._client = httpx.Client(
            base_url=f"{self._supabase_url}/auth/v1",
            headers={
                "apikey": self._supabase_anon_key,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        log.info("registration_manager_ready")

    @property
    def is_authenticated(self) -> bool:
        return self._session is not None

    @property
    def access_token(self) -> str | None:
        if self._session:
            return self._session.get("access_token")
        return None

    def send_otp(self, phone: str) -> bool:
        """Send OTP to phone number. Returns True on success."""
        # Normalize Canadian phone numbers
        phone = self._normalize_phone(phone)
        try:
            response = self._client.post("/otp", json={
                "phone": phone,
            })
            response.raise_for_status()
            log.info("otp_sent", phone=phone[:4] + "****")
            return True
        except httpx.HTTPError as e:
            log.error("otp_send_failed", error=str(e))
            return False

    def verify_otp(self, phone: str, code: str) -> bool:
        """Verify the OTP code. Returns True and stores session on success."""
        phone = self._normalize_phone(phone)
        try:
            response = self._client.post("/verify", json={
                "phone": phone,
                "token": code,
                "type": "sms",
            })
            response.raise_for_status()
            data = response.json()
            self._session = data
            log.info("otp_verified", user_id=data.get("user", {}).get("id"))
            return True
        except httpx.HTTPError as e:
            log.error("otp_verify_failed", error=str(e))
            return False

    def clear_session(self) -> None:
        """Clear the current session without calling the logout API.
        Used between kiosk interactions so the next user starts fresh."""
        self._session = None
        log.info("session_cleared")

    def sign_out(self) -> None:
        if self._session:
            try:
                self._client.post(
                    "/logout",
                    headers={"Authorization": f"Bearer {self._session['access_token']}"},
                )
            except httpx.HTTPError:
                pass
            self._session = None
            log.info("user_signed_out")

    def _normalize_phone(self, phone: str) -> str:
        """Ensure phone is in +1XXXXXXXXXX format for Canadian numbers."""
        digits = "".join(c for c in phone if c.isdigit())
        if len(digits) == 10:
            return f"+1{digits}"
        if len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
        if phone.startswith("+"):
            return phone
        return f"+{digits}"
