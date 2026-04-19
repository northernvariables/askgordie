"""CanadaGPT API client with SSE streaming support.

Calls the CanadaGPT chat endpoint at /api/chat with the 'askgordie' context type.
Uses the canadagpt-public-api-key for device authentication.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import Settings

log = structlog.get_logger()


class CanadaGPTClient:
    """Sends transcribed queries to the CanadaGPT backend."""

    def __init__(self, settings: Settings) -> None:
        self._url = settings.canadagpt_api_url
        self._api_key = settings.canadagpt_api_key
        self._timeout = settings.canadagpt.timeout_s
        self._retry_count = settings.canadagpt.retry_count
        self._conversation_id = str(uuid.uuid4())
        self._client = httpx.Client(
            timeout=self._timeout,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": self._api_key,
            },
        )
        log.info("canadagpt_client_ready", url=self._url)

    def new_conversation(self) -> None:
        """Start a fresh conversation (new UUID)."""
        self._conversation_id = str(uuid.uuid4())

    def query(self, text: str) -> str:
        """Send query, collect full streaming response into a single string."""
        chunks = list(self.query_stream(text))
        return " ".join(chunks)

    def query_stream(self, text: str) -> Iterator[str]:
        """Send query, yield response sentence chunks as they arrive via SSE."""
        payload = {
            "conversation_id": self._conversation_id,
            "message": text,
            "context": {
                "type": "askgordie",
            },
        }

        last_error: Exception | None = None
        for attempt in range(1 + self._retry_count):
            try:
                start = time.monotonic()
                with self._client.stream("POST", self._url, json=payload) as response:
                    if response.status_code != 200:
                        body = response.read().decode()
                        log.error("canadagpt_http_error", status=response.status_code, body=body[:200])
                        raise httpx.HTTPStatusError(
                            f"HTTP {response.status_code}", request=response.request, response=response
                        )

                    buffer = ""
                    first_token = True
                    for line in response.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue

                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            if buffer.strip():
                                yield buffer.strip()
                            elapsed_ms = (time.monotonic() - start) * 1000
                            log.info("canadagpt_stream_complete", latency_ms=round(elapsed_ms))
                            return

                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        # Handle error events
                        if "error" in chunk:
                            log.error("canadagpt_stream_error_event", error=chunk["error"])
                            raise RuntimeError(f"CanadaGPT error: {chunk['error']}")

                        # Handle content chunks
                        content = chunk.get("content", "")
                        if not content:
                            continue

                        if first_token:
                            elapsed_ms = (time.monotonic() - start) * 1000
                            log.info("canadagpt_first_token", latency_ms=round(elapsed_ms))
                            first_token = False

                        buffer += content

                        # Yield at sentence boundaries for TTS chunking
                        while True:
                            best_idx = -1
                            for sep in (". ", "? ", "! ", ".\n", "?\n", "!\n"):
                                idx = buffer.find(sep)
                                if idx != -1 and (best_idx == -1 or idx < best_idx):
                                    best_idx = idx

                            if best_idx == -1:
                                break

                            sentence = buffer[: best_idx + 1].strip()
                            buffer = buffer[best_idx + 2:]
                            if sentence:
                                yield sentence

                    # Stream ended without [DONE]
                    if buffer.strip():
                        yield buffer.strip()
                    return

            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_error = e
                log.warning("canadagpt_error", attempt=attempt + 1, error=str(e))
                if attempt < self._retry_count:
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"CanadaGPT query failed after {1 + self._retry_count} attempts") from last_error
