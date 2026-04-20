"""Historical persona type definitions — aligned with CanadaGPT persona system."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class HistoricalPersona:
    """A historical Canadian figure embodied by the Gordie appliance."""

    # Identity
    slug: str                    # "laurier", "pearson", "douglas"
    name: str                    # "Sir Wilfrid Laurier"
    title: str                   # "Prime Minister of Canada"
    birth_year: int
    death_year: int
    active_years: str            # "1896–1911" (period they are most known for)
    party: str
    riding: str                  # Their most notable riding

    # Time horizon — persona only "knows" up to this date
    knowledge_cutoff: str        # ISO date: "1919-02-17" (death date)
    era_description: str         # "the early 20th century, the age of Confederation's expansion"

    # Portrait
    portrait_idle: str           # Path to idle portrait image
    portrait_speaking: list[str] = field(default_factory=list)  # Speaking animation frames
    portrait_listening: list[str] = field(default_factory=list)
    portrait_thinking: list[str] = field(default_factory=list)

    # Voice
    voice_name: str = "Alnilam"  # Google Chirp3 HD voice (fallback)
    resemble_voice_uuid: str = ""  # Resemble AI cloned voice UUID (preferred if set)
    speaking_rate: float = 0.95  # Slightly slower for gravitas

    # Prompt components
    identity_prompt: str = ""    # Who they are, how they speak
    biographical_context: str = ""  # Key facts about their life and career
    hansard_context: str = ""    # Notable positions from Hansard (populated at runtime)
    time_horizon_prompt: str = ""  # Instructions for temporal enforcement
    newspaper_mode_prompt: str = ""  # How they handle modern topics

    # CanadaGPT persona system alignment
    persona_slug: str = ""       # For CanadaGPT personas table
    tool_domains: list[str] = field(default_factory=lambda: ["parliamentary"])
    graph_domains: list[str] = field(default_factory=lambda: ["parliamentary"])
    embedding_namespace: str = ""  # For Tier 3 scoped retrieval

    # Suggested questions
    suggested_questions: list[str] = field(default_factory=list)

    # Activation
    activation_phrases: list[str] = field(default_factory=list)
