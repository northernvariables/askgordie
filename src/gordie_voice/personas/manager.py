"""Persona manager — handles selection, portrait state, and prompt composition.

The active persona is admin-configurable per device. The manager:
1. Loads the persona definition
2. Builds the system prompt (with optional Hansard context from FedMCP)
3. Provides portrait image paths for the display
4. Manages persona-specific voice settings
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from gordie_voice.personas.definitions import ALL_PERSONAS, DEFAULT_PERSONA
from gordie_voice.personas.prompt_builder import build_persona_system_prompt
from gordie_voice.personas.types import HistoricalPersona

if TYPE_CHECKING:
    from gordie_voice.config import Settings

log = structlog.get_logger()


class PersonaManager:
    """Manages the active historical persona for this device."""

    def __init__(self, settings: Settings) -> None:
        self._device_id = settings.device_id
        # Admin-configurable: which persona this device portrays
        # Loaded from config, overridable by device registry config_override
        persona_slug = getattr(settings, 'active_persona', None) or DEFAULT_PERSONA
        self._persona = ALL_PERSONAS.get(persona_slug)
        if not self._persona:
            log.warning("persona_not_found", slug=persona_slug, fallback=DEFAULT_PERSONA)
            self._persona = ALL_PERSONAS[DEFAULT_PERSONA]

        self._hansard_context = ""
        self._conversation_history: list[dict] = []
        log.info("persona_loaded", name=self._persona.name, slug=self._persona.slug)

    @property
    def persona(self) -> HistoricalPersona:
        return self._persona

    @property
    def name(self) -> str:
        return self._persona.name

    @property
    def slug(self) -> str:
        return self._persona.slug

    def switch_persona(self, slug: str) -> bool:
        """Switch to a different persona. Returns True on success."""
        persona = ALL_PERSONAS.get(slug)
        if not persona:
            log.warning("persona_switch_failed", slug=slug)
            return False
        self._persona = persona
        self._hansard_context = ""
        self._conversation_history.clear()
        log.info("persona_switched", name=persona.name, slug=slug)
        return True

    def set_hansard_context(self, context: str) -> None:
        """Set Hansard excerpts retrieved from FedMCP for this persona."""
        self._hansard_context = context

    def build_system_prompt(self) -> str:
        """Build the complete system prompt for the current persona."""
        conversation_summary = self._build_conversation_summary()
        return build_persona_system_prompt(
            persona=self._persona,
            hansard_context=self._hansard_context,
            conversation_summary=conversation_summary,
        )

    def add_to_history(self, role: str, content: str) -> None:
        """Track conversation history for working memory (Tier 5)."""
        self._conversation_history.append({"role": role, "content": content})
        # Keep last 10 exchanges
        if len(self._conversation_history) > 20:
            self._conversation_history = self._conversation_history[-20:]

    def clear_history(self) -> None:
        """Clear conversation history (new visitor)."""
        self._conversation_history.clear()

    def _build_conversation_summary(self) -> str:
        """Summarize recent conversation for Tier 5 working memory."""
        if not self._conversation_history:
            return ""
        recent = self._conversation_history[-6:]  # Last 3 exchanges
        parts = []
        for msg in recent:
            role = "Visitor" if msg["role"] == "user" else self._persona.name
            text = msg["content"][:150]
            parts.append(f"{role}: {text}")
        return "\n".join(parts)

    # ---- Portrait helpers ----

    def get_portrait_for_state(self, state: str) -> str | list[str]:
        """Get portrait image path(s) for the current display state."""
        p = self._persona
        if state == "speaking" and p.portrait_speaking:
            return p.portrait_speaking
        elif state == "listening" and p.portrait_listening:
            return p.portrait_listening
        elif state in ("querying", "transcribing") and p.portrait_thinking:
            return p.portrait_thinking
        return p.portrait_idle

    def get_display_info(self) -> dict:
        """Get persona info for the display persona server."""
        return {
            "slug": self._persona.slug,
            "name": self._persona.name,
            "title": self._persona.title,
            "party": self._persona.party,
            "active_years": self._persona.active_years,
            "era_description": self._persona.era_description,
            "portrait_idle": self._persona.portrait_idle,
            "portrait_speaking": self._persona.portrait_speaking,
            "portrait_listening": self._persona.portrait_listening,
            "portrait_thinking": self._persona.portrait_thinking,
            "suggested_questions": self._persona.suggested_questions,
            "voice_name": self._persona.voice_name,
            "speaking_rate": self._persona.speaking_rate,
        }
