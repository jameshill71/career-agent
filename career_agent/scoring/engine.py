from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re


@dataclass(frozen=True)
class ScoreResult:
    score: int
    reasons: list[str]
    matched_keywords: list[str]
    missing_keywords: list[str]
    resume_emphasis: list[str]
    model: str = "heuristic-v1"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _contains_keyword(text: str, keyword: str) -> bool:
    """
    Return True if keyword appears as a standalone word or token.

    Why:
    - avoids false positives like matching 'c' inside 'experience'
    - still matches terms like 'python', 'sql', 'docker', etc.
    """
    pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
    return re.search(pattern, text) is not None


def score_heuristic(
    job_text: str,
    keyword_weights: dict[str, int],
    negative_keywords: dict[str, int],
) -> ScoreResult:
    """
    Score a job description using configurable keyword weights.
    """
    text = _normalize(job_text)

    matched = [k for k in keyword_weights if _contains_keyword(text, k)]
    missing = [k for k in keyword_weights if not _contains_keyword(text, k)]

    base = 25
    match_points = sum(keyword_weights[k] for k in matched)
    penalty_points = sum(
        negative_keywords[k]
        for k in negative_keywords
        if _contains_keyword(text, k)
    )

    score = base + match_points - penalty_points

    # Combo bonuses help distinguish job "shape"
    if "python" in matched and ("fastapi" in matched or "api" in matched or "rest" in matched):
        score += 4
    if "linux" in matched and ("cli" in matched or "bash" in matched):
        score += 3
    if "sql" in matched and ("api" in matched or "fastapi" in matched):
        score += 2

    score = max(0, min(100, score))

    reasons: list[str] = []
    if matched:
        reasons.append(
            "Matched: " + ", ".join(
                sorted(matched, key=lambda k: keyword_weights[k], reverse=True)[:8]
            )
        )

    penalties_matched = [k for k in negative_keywords if _contains_keyword(text, k)]
    if penalties_matched:
        reasons.append("Penalties: " + ", ".join(penalties_matched))

    resume_emphasis: list[str] = []
    if "fastapi" in matched or "api" in matched or "rest" in matched:
        resume_emphasis.append("Emphasize FastAPI/REST service work and API design.")
    if "linux" in matched or "cli" in matched or "bash" in matched:
        resume_emphasis.append("Highlight Linux-first tooling, CLI utilities, and automation.")
    if "sql" in matched or "sqlite" in matched:
        resume_emphasis.append("Call out SQL/SQLite experience and data handling.")

    if not resume_emphasis:
        resume_emphasis.append(
            "Emphasize Python tooling, maintainable design, and defensive input handling."
        )

    return ScoreResult(
        score=score,
        reasons=reasons or ["Heuristic score based on weighted keyword overlap."],
        matched_keywords=matched,
        missing_keywords=missing[:12],
        resume_emphasis=resume_emphasis,
    )


def score_llm(payload: dict[str, Any]) -> ScoreResult:
    raise NotImplementedError("LLM scoring not wired yet.")