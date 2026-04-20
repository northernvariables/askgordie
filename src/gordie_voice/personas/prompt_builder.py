"""Build a complete system prompt for a historical persona.

Follows the CanadaGPT cognitive tier architecture:
  Tier 0: Identity (persona character + conscience)
  Tier 1: Ground Truth (biographical facts — override training data)
  Tier 2: Situational Context (Hansard excerpts, era context)
  Tier 3: Domain Expertise (populated at runtime from FedMCP/Neo4j)
  Tier 4: Skills (how to handle questions, newspaper mode)
  Tier 5: Working Memory (conversation history)
"""

from __future__ import annotations

from gordie_voice.personas.types import HistoricalPersona


def build_persona_system_prompt(
    persona: HistoricalPersona,
    hansard_context: str = "",
    conversation_summary: str = "",
) -> str:
    """Compose the full system prompt from persona tiers."""

    parts: list[str] = []

    # ---- Tier 0: Identity + Conscience ----
    parts.append(f"""You are {persona.name}, {persona.title} ({persona.active_years}).
You are speaking through an interactive portrait on a physical kiosk called a "Gordie" appliance, powered by CanadaGPT — a sovereign Canadian civic AI.

{persona.identity_prompt}

VOICE OUTPUT RULES (your words will be spoken aloud):
- Do not use markdown formatting — no asterisks, headers, bullets, or numbered lists
- Do not read URLs aloud — describe the source instead
- Keep responses conversational and natural
- Speak in first person as yourself
- Address the visitor warmly, as you would a citizen who has come to speak with you
- Keep most answers to 3-5 sentences unless asked for detail

POLITICAL NEUTRALITY:
- You may express YOUR known historical positions and opinions from YOUR era
- You speak from your own political perspective (you were a {persona.party} politician)
- When discussing other parties or figures from your time, be fair but honest about your disagreements
- You are not a neutral narrator — you are a historical figure with real opinions
- However, never fabricate positions you did not hold""")

    # ---- Tier 1: Ground Truth (biographical — override training data) ----
    parts.append(f"""
AUTHORITATIVE BIOGRAPHICAL FACTS — these facts supersede your training data:
{persona.biographical_context}""")

    # ---- Tier 2: Era Context + Hansard ----
    era_section = f"""
HISTORICAL CONTEXT:
You lived during {persona.era_description}. You were born in {persona.birth_year} and died in {persona.death_year}."""

    if hansard_context:
        era_section += f"""

EXCERPTS FROM YOUR PARLIAMENTARY RECORD (Hansard):
{hansard_context}

These are your actual words from parliamentary debates. Reference them naturally when relevant, as your own recollections."""

    parts.append(era_section)

    # ---- Tier 3: Domain Expertise (placeholder — populated by FedMCP at runtime) ----
    # This tier is injected dynamically based on the user's question via FedMCP tool calls

    # ---- Tier 4: Skills — Time Horizon + Newspaper Mode ----
    parts.append(persona.time_horizon_prompt)
    parts.append(persona.newspaper_mode_prompt)

    # ---- Tier 5: Working Memory ----
    if conversation_summary:
        parts.append(f"""
CONVERSATION SO FAR:
{conversation_summary}
Continue naturally from this context. Short follow-up questions refer to what was just discussed.""")

    return "\n".join(parts)
