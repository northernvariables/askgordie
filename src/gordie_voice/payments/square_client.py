"""Square Reader integration for the Gordie appliance.

Uses the Square Terminal API to drive a paired Square Reader for:
- Recording fees (Speaker's Corner style tap-to-pay)
- Charitable donations
- Commerce transactions (merch, etc.)

The Square Reader connects via USB or Bluetooth to the Pi.
We use the Terminal API to create checkout requests that the reader displays.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

SQUARE_API_BASE = {
    "sandbox": "https://connect.squareupsandbox.com/v2",
    "production": "https://connect.squareup.com/v2",
}


class SquareClient:
    """Manages Square Terminal API interactions for a single device."""

    def __init__(
        self,
        access_token: str,
        location_id: str,
        device_id: str,
        environment: str = "sandbox",
    ) -> None:
        self._access_token = access_token
        self._location_id = location_id
        self._device_id = device_id  # Square Terminal device ID
        self._base_url = SQUARE_API_BASE[environment]
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Square-Version": "2024-12-18",
            },
            timeout=30.0,
        )
        log.info("square_client_ready", environment=environment, location=location_id)

    def create_recording_fee_checkout(
        self,
        amount_cents: int,
        currency: str = "CAD",
        description: str = "Record your opinion",
        reference_id: str | None = None,
    ) -> dict:
        """Create a Terminal checkout for a recording fee."""
        return self._create_checkout(
            amount_cents=amount_cents,
            currency=currency,
            note=description,
            reference_id=reference_id or str(uuid.uuid4()),
        )

    def create_donation_checkout(
        self,
        amount_cents: int,
        recipient_name: str = "CanadaGPT",
        currency: str = "CAD",
        reference_id: str | None = None,
    ) -> dict:
        """Create a Terminal checkout for a donation."""
        return self._create_checkout(
            amount_cents=amount_cents,
            currency=currency,
            note=f"Donation to {recipient_name}",
            reference_id=reference_id or str(uuid.uuid4()),
        )

    def create_commerce_checkout(
        self,
        items: list[dict],
        currency: str = "CAD",
        reference_id: str | None = None,
    ) -> dict:
        """Create a Terminal checkout for commerce items.

        items: [{"name": "CanadaGPT Sticker", "quantity": "1", "base_price_cents": 500}]
        """
        total_cents = sum(
            item["base_price_cents"] * int(item.get("quantity", 1)) for item in items
        )
        item_descriptions = ", ".join(
            f"{item.get('quantity', 1)}x {item['name']}" for item in items
        )
        return self._create_checkout(
            amount_cents=total_cents,
            currency=currency,
            note=item_descriptions,
            reference_id=reference_id or str(uuid.uuid4()),
        )

    def _create_checkout(
        self,
        amount_cents: int,
        currency: str,
        note: str,
        reference_id: str,
    ) -> dict:
        """Create a Square Terminal checkout — this sends the payment prompt to the reader."""
        idempotency_key = str(uuid.uuid4())

        payload = {
            "idempotency_key": idempotency_key,
            "checkout": {
                "amount_money": {
                    "amount": amount_cents,
                    "currency": currency,
                },
                "device_options": {
                    "device_id": self._device_id,
                    "skip_receipt_screen": False,
                    "collect_signature": False,
                    "show_itemized_cart": False,
                },
                "reference_id": reference_id,
                "note": note,
                "payment_type": "CARD_PRESENT",
            },
        }

        try:
            resp = self._client.post(
                f"{self._base_url}/terminals/checkouts",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            checkout = data.get("checkout", {})
            log.info(
                "checkout_created",
                checkout_id=checkout.get("id"),
                amount_cents=amount_cents,
                note=note,
            )
            return checkout
        except httpx.HTTPStatusError as e:
            log.error("checkout_create_failed", status=e.response.status_code, body=e.response.text)
            raise
        except Exception:
            log.exception("checkout_create_error")
            raise

    def get_checkout_status(self, checkout_id: str) -> dict:
        """Poll for the status of a Terminal checkout."""
        try:
            resp = self._client.get(f"{self._base_url}/terminals/checkouts/{checkout_id}")
            resp.raise_for_status()
            return resp.json().get("checkout", {})
        except Exception:
            log.exception("checkout_status_error", checkout_id=checkout_id)
            raise

    def cancel_checkout(self, checkout_id: str) -> bool:
        """Cancel a pending Terminal checkout."""
        try:
            resp = self._client.post(
                f"{self._base_url}/terminals/checkouts/{checkout_id}/cancel",
                json={},
            )
            resp.raise_for_status()
            log.info("checkout_cancelled", checkout_id=checkout_id)
            return True
        except Exception:
            log.exception("checkout_cancel_error", checkout_id=checkout_id)
            return False

    def list_devices(self) -> list[dict]:
        """List Square Terminal devices at this location (for pairing verification)."""
        try:
            resp = self._client.get(
                f"{self._base_url}/terminals/devices",
                params={"location_id": self._location_id},
            )
            resp.raise_for_status()
            return resp.json().get("devices", [])
        except Exception:
            log.exception("list_devices_error")
            return []
