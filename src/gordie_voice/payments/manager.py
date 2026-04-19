"""Payment manager — orchestrates Square checkout flows and syncs with Supabase.

Pulls per-device payment config from Supabase, creates Square checkouts,
polls for completion, logs transactions.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import TYPE_CHECKING

import httpx
import structlog

from gordie_voice.payments.square_client import SquareClient

if TYPE_CHECKING:
    from gordie_voice.config import Settings

log = structlog.get_logger()

CHECKOUT_POLL_INTERVAL_S = 2
CHECKOUT_TIMEOUT_S = 120  # Cancel if not completed in 2 minutes


class PaymentConfig:
    """Per-device payment configuration loaded from Supabase."""

    def __init__(self, data: dict) -> None:
        self.raw = data
        # Recording fee
        self.recording_fee_enabled = data.get("recording_fee_enabled", False)
        self.recording_fee_cents = data.get("recording_fee_cents", 100)
        self.recording_fee_currency = data.get("recording_fee_currency", "CAD")
        self.recording_fee_description = data.get("recording_fee_description", "Record your opinion")
        # Donations
        self.donation_enabled = data.get("donation_enabled", False)
        self.donation_presets_cents = data.get("donation_preset_amounts_cents", [200, 500, 1000, 2000])
        self.donation_custom = data.get("donation_custom_amount", True)
        self.donation_min_cents = data.get("donation_min_cents", 100)
        self.donation_max_cents = data.get("donation_max_cents", 50000)
        self.donation_recipient = data.get("donation_recipient_name", "CanadaGPT")
        self.donation_charity_number = data.get("donation_charity_number")
        self.donation_tax_receipt = data.get("donation_tax_receipt", False)
        # Commerce
        self.commerce_enabled = data.get("commerce_enabled", False)
        self.commerce_catalog = data.get("commerce_catalog", [])
        # Square
        self.square_access_token = data.get("square_access_token_encrypted", "")
        self.square_location_id = data.get("square_location_id", "")
        self.square_device_id = data.get("square_device_id", "")
        self.square_environment = data.get("square_environment", "sandbox")

    @property
    def any_enabled(self) -> bool:
        return self.recording_fee_enabled or self.donation_enabled or self.commerce_enabled

    @property
    def square_configured(self) -> bool:
        return bool(self.square_access_token and self.square_location_id and self.square_device_id)


class PaymentManager:
    """Manages payment flows for a single Gordie device."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._supabase_url = settings.supabase_url
        self._supabase_key = settings.supabase_service_role_key
        self._device_id = settings.device_id
        self._config: PaymentConfig | None = None
        self._square: SquareClient | None = None
        self._active_checkout_id: str | None = None
        self._checkout_callback = None
        self._client = httpx.Client(
            headers={
                "apikey": self._supabase_key,
                "Authorization": f"Bearer {self._supabase_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    @property
    def config(self) -> PaymentConfig | None:
        return self._config

    @property
    def is_ready(self) -> bool:
        return self._config is not None and self._config.any_enabled and self._square is not None

    def load_config(self) -> bool:
        """Fetch payment config for this device from Supabase."""
        try:
            url = f"{self._supabase_url}/rest/v1/payment_configs?device_id=eq.{self._device_id}&select=*"
            resp = self._client.get(url)
            resp.raise_for_status()
            rows = resp.json()
            if not rows:
                log.info("no_payment_config", device_id=self._device_id)
                return False

            self._config = PaymentConfig(rows[0])

            if self._config.square_configured:
                self._square = SquareClient(
                    access_token=self._config.square_access_token,
                    location_id=self._config.square_location_id,
                    device_id=self._config.square_device_id,
                    environment=self._config.square_environment,
                )
                log.info("payment_config_loaded", recording_fee=self._config.recording_fee_enabled,
                         donation=self._config.donation_enabled, commerce=self._config.commerce_enabled)
                return True
            else:
                log.warning("square_not_configured", device_id=self._device_id)
                return False

        except Exception:
            log.exception("payment_config_load_failed")
            return False

    def charge_recording_fee(self, callback=None) -> str | None:
        """Initiate a recording fee checkout on the Square Reader.

        Returns the checkout_id. Calls callback(success, payment_data) when done.
        """
        if not self._square or not self._config or not self._config.recording_fee_enabled:
            return None

        ref_id = str(uuid.uuid4())
        try:
            checkout = self._square.create_recording_fee_checkout(
                amount_cents=self._config.recording_fee_cents,
                currency=self._config.recording_fee_currency,
                description=self._config.recording_fee_description,
                reference_id=ref_id,
            )
            checkout_id = checkout.get("id")
            if checkout_id:
                self._poll_checkout(checkout_id, "recording_fee", ref_id, callback)
            return checkout_id
        except Exception:
            log.exception("recording_fee_checkout_failed")
            return None

    def charge_donation(self, amount_cents: int, donor_email: str | None = None, callback=None) -> str | None:
        """Initiate a donation checkout."""
        if not self._square or not self._config or not self._config.donation_enabled:
            return None

        ref_id = str(uuid.uuid4())
        try:
            checkout = self._square.create_donation_checkout(
                amount_cents=amount_cents,
                recipient_name=self._config.donation_recipient,
                reference_id=ref_id,
            )
            checkout_id = checkout.get("id")
            if checkout_id:
                self._poll_checkout(checkout_id, "donation", ref_id, callback, extra={"donor_email": donor_email})
            return checkout_id
        except Exception:
            log.exception("donation_checkout_failed")
            return None

    def charge_commerce(self, items: list[dict], callback=None) -> str | None:
        """Initiate a commerce checkout for catalog items."""
        if not self._square or not self._config or not self._config.commerce_enabled:
            return None

        ref_id = str(uuid.uuid4())
        try:
            checkout = self._square.create_commerce_checkout(
                items=items,
                reference_id=ref_id,
            )
            checkout_id = checkout.get("id")
            if checkout_id:
                self._poll_checkout(checkout_id, "commerce", ref_id, callback, extra={"items": items})
            return checkout_id
        except Exception:
            log.exception("commerce_checkout_failed")
            return None

    def cancel_active_checkout(self) -> None:
        """Cancel the currently active checkout."""
        if self._active_checkout_id and self._square:
            self._square.cancel_checkout(self._active_checkout_id)
            self._active_checkout_id = None

    def _poll_checkout(
        self,
        checkout_id: str,
        payment_type: str,
        reference_id: str,
        callback,
        extra: dict | None = None,
    ) -> None:
        """Poll Square for checkout completion in a background thread."""
        self._active_checkout_id = checkout_id

        def _poll():
            start = time.monotonic()
            while time.monotonic() - start < CHECKOUT_TIMEOUT_S:
                try:
                    checkout = self._square.get_checkout_status(checkout_id)
                    status = checkout.get("status", "")

                    if status == "COMPLETED":
                        payment_ids = checkout.get("payment_ids", [])
                        self._log_transaction(
                            payment_type=payment_type,
                            amount_cents=checkout.get("amount_money", {}).get("amount", 0),
                            square_payment_id=payment_ids[0] if payment_ids else None,
                            reference_id=reference_id,
                            status="completed",
                            extra=extra,
                        )
                        self._active_checkout_id = None
                        if callback:
                            callback(True, {"checkout_id": checkout_id, "payment_ids": payment_ids})
                        return

                    elif status in ("CANCELLED", "CANCEL_REQUESTED"):
                        self._log_transaction(
                            payment_type=payment_type,
                            amount_cents=0,
                            reference_id=reference_id,
                            status="cancelled",
                            extra=extra,
                        )
                        self._active_checkout_id = None
                        if callback:
                            callback(False, {"reason": "cancelled"})
                        return

                except Exception:
                    log.warning("checkout_poll_error", checkout_id=checkout_id)

                time.sleep(CHECKOUT_POLL_INTERVAL_S)

            # Timeout — cancel
            log.warning("checkout_timeout", checkout_id=checkout_id)
            self._square.cancel_checkout(checkout_id)
            self._log_transaction(
                payment_type=payment_type,
                amount_cents=0,
                reference_id=reference_id,
                status="cancelled",
                failure_reason="timeout",
                extra=extra,
            )
            self._active_checkout_id = None
            if callback:
                callback(False, {"reason": "timeout"})

        threading.Thread(target=_poll, daemon=True).start()

    def _log_transaction(
        self,
        payment_type: str,
        amount_cents: int,
        reference_id: str,
        status: str,
        square_payment_id: str | None = None,
        failure_reason: str | None = None,
        extra: dict | None = None,
    ) -> None:
        """Log a payment transaction to Supabase."""
        extra = extra or {}
        row = {
            "device_id": self._device_id,
            "payment_type": payment_type,
            "amount_cents": amount_cents,
            "currency": self._config.recording_fee_currency if self._config else "CAD",
            "square_payment_id": square_payment_id,
            "status": status,
            "failure_reason": failure_reason,
            "commerce_items": extra.get("items"),
            "donor_email": extra.get("donor_email"),
        }

        try:
            url = f"{self._supabase_url}/rest/v1/payments"
            self._client.post(url, json=row, headers={"Prefer": "return=minimal"}).raise_for_status()
            log.info("payment_logged", type=payment_type, status=status, amount_cents=amount_cents)
        except Exception:
            log.exception("payment_log_failed")
