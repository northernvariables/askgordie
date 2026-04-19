"""Direct Anthropic API client — bypass for when CanadaGPT chat route requires session auth.

Uses the same Gordie system prompt as CanadaGPT. Calls Claude directly.
Intended as a temporary bridge until device API key auth is added to CanadaGPT.
"""

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

GORDIE_SYSTEM_PROMPT = """You are Gordie, the AI assistant for CanadaGPT — a sovereign Canadian civic AI platform.

You are an expert on Canadian government, parliament, politics, legislation, and public policy. You answer questions clearly, accurately, and concisely.

Key guidelines:
- Be conversational and warm — you're speaking through a voice interface on a physical kiosk
- Keep answers concise (2-4 sentences for simple questions, more for complex ones)
- When citing sources, name them naturally ("according to Hansard", "Statistics Canada reports")
- For questions about current MPs, bills, or votes, provide the most recent information you have
- If you're unsure, say so honestly
- You represent Canadian values: bilingual respect, democratic principles, transparency
- Never make up legislation, votes, or quotes that you're not confident about

You are running on a Raspberry Pi 5 appliance called a "Gordie" — a physical kiosk that people walk up to and talk to. Your responses will be converted to speech, so:
- Avoid markdown formatting (no asterisks, headers, bullet points)
- Don't use URLs — describe the source instead
- Spell out abbreviations on first use
- Keep sentences natural and conversational
"""


class DirectAnthropicClient:
    """Calls the Anthropic API directly with the Gordie system prompt."""

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.anthropic_api_key
        self._model = "claude-sonnet-4-20250514"
        self._timeout = settings.canadagpt.timeout_s
        self._retry_count = settings.canadagpt.retry_count
        self._messages: list[dict] = []  # Conversation history
        self._client = httpx.Client(
            timeout=self._timeout,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        log.info("direct_anthropic_ready", model=self._model)

    def new_conversation(self) -> None:
        self._messages.clear()

    def query(self, text: str) -> str:
        chunks = list(self.query_stream(text))
        return " ".join(chunks)

    def query_stream(self, text: str) -> Iterator[str]:
        self._messages.append({"role": "user", "content": text})

        # Keep last 10 messages to avoid context overflow
        messages = self._messages[-10:]

        payload = {
            "model": self._model,
            "max_tokens": 1024,
            "system": GORDIE_SYSTEM_PROMPT,
            "messages": messages,
            "stream": True,
        }

        last_error: Exception | None = None
        for attempt in range(1 + self._retry_count):
            try:
                start = time.monotonic()
                full_response = ""
                buffer = ""
                first_token = True

                with self._client.stream("POST", "https://api.anthropic.com/v1/messages", json=payload) as response:
                    if response.status_code != 200:
                        body = response.read().decode()
                        log.error("anthropic_http_error", status=response.status_code, body=body[:200])
                        raise httpx.HTTPStatusError(
                            f"HTTP {response.status_code}", request=response.request, response=response
                        )

                    for line in response.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue

                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break

                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        event_type = event.get("type", "")

                        if event_type == "content_block_delta":
                            delta = event.get("delta", {})
                            text_chunk = delta.get("text", "")
                            if not text_chunk:
                                continue

                            if first_token:
                                elapsed_ms = (time.monotonic() - start) * 1000
                                log.info("anthropic_first_token", latency_ms=round(elapsed_ms))
                                first_token = False

                            full_response += text_chunk
                            buffer += text_chunk

                            # Yield at sentence boundaries
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

                        elif event_type == "message_stop":
                            break

                if buffer.strip():
                    yield buffer.strip()

                # Save assistant response to conversation history
                self._messages.append({"role": "assistant", "content": full_response})
                elapsed_ms = (time.monotonic() - start) * 1000
                log.info("anthropic_stream_complete", latency_ms=round(elapsed_ms), length=len(full_response))
                return

            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_error = e
                log.warning("anthropic_error", attempt=attempt + 1, error=str(e))
                if attempt < self._retry_count:
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"Anthropic query failed after {1 + self._retry_count} attempts") from last_error
