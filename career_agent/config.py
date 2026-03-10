from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_DB = Path.home() / ".career_agent" / "career_agent.db"
DEFAULT_CONFIG = Path("config.json")
OPENAI_MODEL = "gpt-5"


def default_config() -> dict[str, Any]:
    return {
        "database": {
            "path": str(DEFAULT_DB),
        },
        "profile": {
            "preferred_keywords": {
                "python": 12,
                "linux": 12,
                "cli": 10,
                "fastapi": 10,
                "sql": 8,
                "sqlite": 6,
                "api": 6,
                "rest": 6,
                "pytest": 5,
                "bash": 5,
                "docker": 5,
                "aws": 6,
                "c": 4,
            },
            "negative_keywords": {
                "react": 10,
                "angular": 8,
                "vue": 6,
                "typescript": 8,
                "sales": 12,
                "commission": 12,
            },
        },
        "sources": [
            {
                "type": "local_json",
                "path": "data/sample_jobs.json",
            }
        ],
    }


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    path = config_path or DEFAULT_CONFIG

    if not path.exists():
        return default_config()

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_db_path(config: dict[str, Any]) -> Path:
    raw_path = config.get("database", {}).get("path", str(DEFAULT_DB))
    return Path(raw_path).expanduser()