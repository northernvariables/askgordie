"""Fact-checker for opinion recordings.

After a user records their opinion, this module:
1. Extracts the transcript (already done by STT)
2. Splits transcript into individual claims
3. Sends each claim to CanadaGPT for verification
4. Returns structured results with verdicts, sources, and corrections

Uses CanadaGPT as the fact-checking authority — it has access to Hansard,
bills, committee testimony, StatsCan data, etc.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx
import structlog

if TYPE_CHECKING:
    from gordie_voice.config import Settings

log = structlog.get_logger()


@dataclass
class ClaimVerdict:
    claim: str
    verdict: str          # "true", "mostly_true", "mixed", "mostly_false", "false", "unverifiable"
    confidence: float     # 0.0 - 1.0
    explanation: str
    correction: str       # Empty if claim is true
    sources: list[dict] = field(default_factory=list)  # [{"title": "...", "url": "..."}]


@dataclass
class FactCheckResult:
    transcript: str
    claims: list[ClaimVerdict]
    summary: str          # One-paragraph overall assessment
    checked_at: str       # ISO timestamp

    @property
    def claim_count(self) -> int:
        return len(self.claims)

    @property
    def accuracy_score(self) -> float:
        """0.0 to 1.0 — weighted average of claim verdicts."""
        if not self.claims:
            return 0.0
        verdict_scores = {
            "true": 1.0, "mostly_true": 0.8, "mixed": 0.5,
            "mostly_false": 0.2, "false": 0.0, "unverifiable": 0.5,
        }
        total = sum(verdict_scores.get(c.verdict, 0.5) for c in self.claims)
        return total / len(self.claims)

    @property
    def verdict_label(self) -> str:
        """Map accuracy score to a fun Gordie verdict on the Baloney-to-Brilliance scale."""
        score = self.accuracy_score
        if score >= 0.9:
            return "Brilliance"
        elif score >= 0.75:
            return "Sharp"
        elif score >= 0.6:
            return "Fair Point"
        elif score >= 0.45:
            return "Shaky Ground"
        elif score >= 0.3:
            return "Mostly Malarkey"
        else:
            return "Full Baloney"

    @property
    def verdict_emoji(self) -> str:
        score = self.accuracy_score
        if score >= 0.9:
            return "🏆"
        elif score >= 0.75:
            return "🎯"
        elif score >= 0.6:
            return "🤔"
        elif score >= 0.45:
            return "😬"
        elif score >= 0.3:
            return "🧐"
        else:
            return "🌭"

    def to_dict(self) -> dict:
        return {
            "transcript": self.transcript,
            "claims": [
                {
                    "claim": c.claim,
                    "verdict": c.verdict,
                    "confidence": c.confidence,
                    "explanation": c.explanation,
                    "correction": c.correction,
                    "sources": c.sources,
                }
                for c in self.claims
            ],
            "summary": self.summary,
            "accuracy_score": round(self.accuracy_score, 2),
            "claim_count": self.claim_count,
            "checked_at": self.checked_at,
            "verdict_label": self.verdict_label,
            "verdict_emoji": self.verdict_emoji,
        }


CLAIM_EXTRACTION_PROMPT = """You are a claim extractor. Given a transcript of someone's spoken opinion, extract every factual claim they make. Ignore pure opinions, feelings, and rhetorical questions. Only extract statements that can be verified as true or false.

Return a JSON array of strings, each being one claim. If there are no verifiable claims, return an empty array.

Transcript:
{transcript}

Return ONLY a JSON array, no other text."""


FACT_CHECK_PROMPT = """You are a Canadian fact-checker with access to authoritative sources including Hansard, parliamentary records, Statistics Canada, Elections Canada, and federal legislation.

Fact-check the following claim. Respond with a JSON object:
{{
    "verdict": "true" | "mostly_true" | "mixed" | "mostly_false" | "false" | "unverifiable",
    "confidence": 0.0-1.0,
    "explanation": "Brief explanation of why this verdict was reached",
    "correction": "If the claim is wrong, provide the correct information. Empty string if claim is true.",
    "sources": [{{"title": "Source name", "url": "https://..."}}]
}}

Claim: {claim}

Context category: {category}

Return ONLY the JSON object, no other text."""


SUMMARY_PROMPT = """Given these fact-check results for a recorded opinion, write a brief 2-3 sentence summary of the overall accuracy. Be fair, respectful, and constructive. If the person was mostly right, say so. If they had misconceptions, gently note the key corrections.

Results:
{results_json}

Return only the summary paragraph, no other text."""


class FactChecker:
    """Checks factual claims in opinion transcripts against CanadaGPT."""

    def __init__(self, settings: Settings) -> None:
        self._api_url = settings.canadagpt_api_url
        self._api_key = settings.canadagpt_api_key
        self._timeout = settings.canadagpt.timeout_s
        self._client = httpx.Client(
            timeout=self._timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )
        log.info("fact_checker_ready")

    def check(self, transcript: str, category: str = "") -> FactCheckResult:
        """Full fact-check pipeline: extract claims → verify each → summarize."""
        from datetime import datetime, timezone

        log.info("fact_check_start", transcript_len=len(transcript))

        # 1. Extract claims
        claims = self._extract_claims(transcript)
        log.info("claims_extracted", count=len(claims))

        if not claims:
            return FactCheckResult(
                transcript=transcript,
                claims=[],
                summary="No verifiable factual claims were found in this opinion. "
                        "The statement appears to be primarily opinion-based.",
                checked_at=datetime.now(timezone.utc).isoformat(),
            )

        # 2. Verify each claim
        verdicts: list[ClaimVerdict] = []
        for claim in claims:
            verdict = self._verify_claim(claim, category)
            verdicts.append(verdict)
            log.info("claim_verified", claim=claim[:50], verdict=verdict.verdict)

        # 3. Generate summary
        summary = self._generate_summary(verdicts)

        result = FactCheckResult(
            transcript=transcript,
            claims=verdicts,
            summary=summary,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )
        log.info("fact_check_complete", claims=len(verdicts), accuracy=round(result.accuracy_score, 2))
        return result

    def _query_canadagpt(self, prompt: str) -> str:
        """Send a prompt to CanadaGPT and return the response text."""
        try:
            response = self._client.post(
                self._api_url,
                json={"query": prompt},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", data.get("answer", str(data)))
        except Exception:
            log.exception("canadagpt_query_failed")
            return ""

    def _extract_claims(self, transcript: str) -> list[str]:
        """Use CanadaGPT to extract verifiable claims from the transcript."""
        prompt = CLAIM_EXTRACTION_PROMPT.format(transcript=transcript)
        response = self._query_canadagpt(prompt)

        try:
            # Try to parse JSON array from response
            response = response.strip()
            # Handle markdown code blocks
            if "```" in response:
                match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", response, re.DOTALL)
                if match:
                    response = match.group(1)

            claims = json.loads(response)
            if isinstance(claims, list):
                return [str(c).strip() for c in claims if c]
        except (json.JSONDecodeError, TypeError):
            log.warning("claim_extraction_parse_failed", response=response[:200])

        # Fallback: split on sentences and filter obvious opinions
        sentences = re.split(r"(?<=[.!?])\s+", transcript)
        opinion_markers = ["i think", "i feel", "i believe", "in my opinion", "i hope", "i wish"]
        return [
            s.strip() for s in sentences
            if s.strip() and not any(m in s.lower() for m in opinion_markers)
        ][:10]  # Cap at 10 claims

    def _verify_claim(self, claim: str, category: str) -> ClaimVerdict:
        """Verify a single claim against CanadaGPT."""
        prompt = FACT_CHECK_PROMPT.format(claim=claim, category=category)
        response = self._query_canadagpt(prompt)

        try:
            response = response.strip()
            if "```" in response:
                match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL)
                if match:
                    response = match.group(1)

            data = json.loads(response)
            return ClaimVerdict(
                claim=claim,
                verdict=data.get("verdict", "unverifiable"),
                confidence=float(data.get("confidence", 0.5)),
                explanation=data.get("explanation", ""),
                correction=data.get("correction", ""),
                sources=data.get("sources", []),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            log.warning("claim_verify_parse_failed", claim=claim[:50])
            return ClaimVerdict(
                claim=claim,
                verdict="unverifiable",
                confidence=0.0,
                explanation="Unable to verify this claim at this time.",
                correction="",
                sources=[],
            )

    def _generate_summary(self, verdicts: list[ClaimVerdict]) -> str:
        """Generate a human-friendly summary of the fact-check results."""
        results_json = json.dumps([
            {"claim": v.claim, "verdict": v.verdict, "correction": v.correction}
            for v in verdicts
        ], indent=2)

        prompt = SUMMARY_PROMPT.format(results_json=results_json)
        summary = self._query_canadagpt(prompt)
        return summary.strip() if summary else "Fact-check results are shown below."
