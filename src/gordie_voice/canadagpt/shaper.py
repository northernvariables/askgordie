"""Transform CanadaGPT markdown responses into voice-friendly prose."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gordie_voice.config import ShaperConfig


class ResponseShaper:
    """Converts markdown text into speakable sentences."""

    def __init__(self, config: ShaperConfig) -> None:
        self.config = config

    def shape(self, text: str) -> list[str]:
        """Full pipeline: strip markdown, flatten citations, chunk into sentences."""
        text = self._strip_markdown(text)
        text = self._handle_citations(text)
        text = self._handle_urls(text)
        text = self._convert_lists(text)
        text = self._truncate(text)
        return self._chunk_sentences(text)

    def _strip_markdown(self, text: str) -> str:
        # Headers
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Bold/italic
        text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
        text = re.sub(r"_{1,3}(.*?)_{1,3}", r"\1", text)
        # Inline code
        text = re.sub(r"`([^`]+)`", r"\1", text)
        # Code blocks
        text = re.sub(r"```[\s\S]*?```", "", text)
        # Horizontal rules
        text = re.sub(r"^---+$", "", text, flags=re.MULTILINE)
        # Links: [text](url) -> text
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        # Images
        text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
        return text.strip()

    def _handle_citations(self, text: str) -> str:
        if self.config.strip_citations:
            # Remove [1], [^source], etc.
            text = re.sub(r"\[\^?[\w\-]+\]", "", text)
        else:
            # Try to make them speakable
            text = re.sub(r"\[(\d+)\]", r" (source \1) ", text)
            text = re.sub(r"\[\^([\w\-]+)\]", r" (according to \1) ", text)
        return text

    def _handle_urls(self, text: str) -> str:
        if self.config.strip_urls:
            text = re.sub(r"https?://\S+", "", text)
        else:
            # Spell out domain only
            def _simplify_url(m: re.Match) -> str:
                url = m.group(0)
                domain = re.search(r"https?://(www\.)?([\w.-]+)", url)
                return f"at {domain.group(2)}" if domain else ""
            text = re.sub(r"https?://\S+", _simplify_url, text)
        return text

    def _convert_lists(self, text: str) -> str:
        """Convert bullet/numbered lists into natural language."""
        lines = text.split("\n")
        result: list[str] = []
        list_items: list[str] = []

        for line in lines:
            stripped = line.strip()
            # Bullet or numbered list item
            list_match = re.match(r"^(?:[-*+]|\d+[.)]) (.+)$", stripped)
            if list_match:
                list_items.append(list_match.group(1).strip())
            else:
                if list_items:
                    result.append(self._join_list_items(list_items))
                    list_items = []
                if stripped:
                    result.append(stripped)

        if list_items:
            result.append(self._join_list_items(list_items))

        return " ".join(result)

    def _join_list_items(self, items: list[str]) -> str:
        ordinals = ["first", "second", "third", "fourth", "fifth", "sixth"]
        parts: list[str] = []
        for i, item in enumerate(items):
            if i < len(ordinals):
                parts.append(f"{ordinals[i]}, {item}")
            else:
                parts.append(item)
        if len(parts) <= 2:
            return " and ".join(parts) + "."
        return ", ".join(parts[:-1]) + f", and {parts[-1]}."

    def _truncate(self, text: str) -> str:
        words = text.split()
        if len(words) > self.config.max_response_words:
            truncated = " ".join(words[: self.config.max_response_words])
            truncated += ". I'll send the full details to your screen."
            return truncated
        return text

    def _chunk_sentences(self, text: str) -> list[str]:
        """Split text into sentence-level chunks for streaming TTS."""
        # Split on sentence-ending punctuation followed by space or end
        sentences = re.split(r"(?<=[.!?])\s+", text)
        # Filter out empty strings and whitespace-only
        return [s.strip() for s in sentences if s.strip()]
