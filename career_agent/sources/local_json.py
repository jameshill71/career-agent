from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from ..models import Job


def load_jobs(path: Path) -> Iterable[Job]:
    """
    Load jobs from a local JSON file (v1 dev source).
    Expected format: a list[dict] with keys like url/company/title/location/posted_date/description.
    """
    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, list):
        raise ValueError("sample_jobs.json must contain a JSON list of job objects")

    for item in data:
        yield Job(
            source=item.get("source", "local_json"),
            url=item["url"],
            company=item["company"],
            title=item["title"],
            location=item.get("location", "unknown"),
            posted_date=item.get("posted_date"),
            description=item.get("description", ""),
        )