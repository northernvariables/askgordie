"""CanadaGPT API client with streaming support."""

from __future__ import annotations

import json
import time
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
        self._client = httpx.Client(
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        log.info("canadagpt_client_ready", url=self._url)

    def query(self, text: str) -> str:
        """Send query, return full response text."""
        payload = {"query": text}
        last_error: Exception | None = None

        for attempt in range(1 + self._retry_count):
            try:
                start = time.monotonic()
                response = self._client.post(self._url, json=payload)
                response.raise_for_status()
                elapsed_ms = (time.monotonic() - start) * 1000
                data = response.json()
                answer = data.get("response", data.get("answer", str(data)))
                log.info("canadagpt_response", latency_ms=round(elapsed_ms), length=len(answer))
                return answer
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_error = e
                log.warning("canadagpt_error", attempt=attempt + 1, error=str(e))
                if attempt < self._retry_count:
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"CanadaGPT query failed after {1 + self._retry_count} attempts") from last_error

    def query_stream(self, text: str) -> Iterator[str]:
        """Send query, yield response chunks as they arrive via SSE."""
        payload = {"query": text, "stream": True}

        try:
            with self._client.stream("POST", self._url, json=payload) as response:
                response.raise_for_status()
                buffer = ""
                for line in response.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            if buffer:
                                yield buffer
                            return
                        try:
                            chunk_data = json.loads(data_str)
                            token = chunk_data.get("token", chunk_data.get("delta", ""))
                            buffer += token
                            # Yield at sentence boundaries
                            while ". " in buffer or "? " in buffer or "! " in buffer:
                                for sep in (". ", "? ", "! "):
                                    idx = buffer.find(sep)
                                    if idx != -1:
                                        yield buffer[: idx + 1]
                                        buffer = buffer[idx + 2:]
                                        break
                        except json.JSONDecodeError:
                            buffer += data_str
                    else:
                        # Non-SSE streaming — raw text chunks
                        buffer += line
                        while ". " in buffer:
                            idx = buffer.find(". ")
                            yield buffer[: idx + 1]
                            buffer = buffer[idx + 2:]

                if buffer.strip():
                    yield buffer

        except (httpx.HTTPError, httpx.TimeoutException) as e:
            log.error("canadagpt_stream_error", error=str(e))
            raise RuntimeError(f"CanadaGPT stream failed: {e}") from e
