from __future__ import annotations

import hashlib
from pydantic import BaseModel, Field


class Job(BaseModel):
    """
    Normalized job record used across sources, DB insertion, and scoring.

    v1 philosophy: keep it small, stable, and easy to extend.
    """
    source: str = Field(..., description="Where we got the job from (local_json, rss, etc.)")
    url: str
    company: str
    title: str
    location: str = "unknown"
    posted_date: str | None = None
    description: str = ""

    def fingerprint(self) -> str:
        """
        Deduplication key.

        Why: job boards often repost/duplicate roles; we want a stable UNIQUE key in SQLite.
        We include URL to avoid collisions between similar postings at different links.
        """
        key = f"{self.company}|{self.title}|{self.location}|{self.url}".lower().strip()
        return hashlib.sha256(key.encode("utf-8")).hexdigest()