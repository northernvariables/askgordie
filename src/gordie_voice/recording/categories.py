"""Opinion recording categories — topics users can choose to speak about."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    prompt: str  # Shown to user before recording to frame their thoughts
    icon: str    # Emoji or short symbol for display
    challenge_questions: tuple[str, ...] = ()  # Gordie Challenge mode questions


@dataclass(frozen=True)
class ChallengeQuestion:
    """A specific question Gordie asks in Challenge mode."""
    category_id: str
    question: str
    spoken_question: str  # TTS-friendly version


CATEGORIES: list[Category] = [
    Category(
        id="healthcare",
        label="Healthcare",
        prompt="What do you think about the state of healthcare in Canada?",
        icon="🏥",
    ),
    Category(
        id="housing",
        label="Housing",
        prompt="What are your thoughts on housing affordability in Canada?",
        icon="🏠",
    ),
    Category(
        id="economy",
        label="Economy & Jobs",
        prompt="How do you feel about the Canadian economy and job market?",
        icon="💼",
    ),
    Category(
        id="environment",
        label="Environment",
        prompt="What should Canada be doing about climate and the environment?",
        icon="🌿",
    ),
    Category(
        id="education",
        label="Education",
        prompt="What changes would you like to see in Canadian education?",
        icon="📚",
    ),
    Category(
        id="indigenous",
        label="Indigenous Issues",
        prompt="What are your thoughts on reconciliation and Indigenous rights?",
        icon="🪶",
    ),
    Category(
        id="immigration",
        label="Immigration",
        prompt="What do you think about Canada's immigration policies?",
        icon="🛂",
    ),
    Category(
        id="democracy",
        label="Democracy & Governance",
        prompt="How do you feel about the state of Canadian democracy?",
        icon="🗳️",
    ),
    Category(
        id="technology",
        label="Technology & AI",
        prompt="What role should technology and AI play in Canada's future?",
        icon="🤖",
    ),
    Category(
        id="freeform",
        label="Something Else",
        prompt="Tell us what's on your mind — any topic, any perspective.",
        icon="💬",
    ),
]

CATEGORIES_BY_ID = {c.id: c for c in CATEGORIES}

# Gordie Challenge questions — Gordie asks, you answer, Gordie fact-checks
CHALLENGE_QUESTIONS: list[ChallengeQuestion] = [
    ChallengeQuestion("healthcare", "How many Canadians don't have a family doctor?", "How many Canadians don't have a family doctor?"),
    ChallengeQuestion("healthcare", "How does Canada's healthcare spending compare to other G7 countries?", "How does Canada's healthcare spending compare to other G7 countries?"),
    ChallengeQuestion("housing", "What is the average home price in Canada right now?", "What is the average home price in Canada right now?"),
    ChallengeQuestion("housing", "How many homes does Canada need to build by 2030 to close the gap?", "How many homes does Canada need to build by 2030 to close the gap?"),
    ChallengeQuestion("economy", "What is Canada's current unemployment rate?", "What is Canada's current unemployment rate?"),
    ChallengeQuestion("economy", "What percentage of Canada's GDP comes from natural resources?", "What percentage of Canada's GDP comes from natural resources?"),
    ChallengeQuestion("environment", "By how much has Canada reduced its greenhouse gas emissions since 2005?", "By how much has Canada reduced its greenhouse gas emissions since 2005?"),
    ChallengeQuestion("education", "What percentage of Canadians have a post-secondary degree?", "What percentage of Canadians have a post-secondary degree?"),
    ChallengeQuestion("immigration", "How many permanent residents does Canada admit per year?", "How many permanent residents does Canada admit per year?"),
    ChallengeQuestion("democracy", "What was the voter turnout in the last federal election?", "What was the voter turnout in the last federal election?"),
    ChallengeQuestion("democracy", "How many seats are in the House of Commons?", "How many seats are in the House of Commons?"),
    ChallengeQuestion("indigenous", "How many First Nations are recognized in Canada?", "How many First Nations are recognized in Canada?"),
    ChallengeQuestion("technology", "What percentage of rural Canadians have access to high-speed internet?", "What percentage of rural Canadians have access to high-speed internet?"),
]

CHALLENGES_BY_CATEGORY: dict[str, list[ChallengeQuestion]] = {}
for _q in CHALLENGE_QUESTIONS:
    CHALLENGES_BY_CATEGORY.setdefault(_q.category_id, []).append(_q)
