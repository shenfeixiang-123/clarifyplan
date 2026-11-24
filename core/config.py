"""Settings, read from environment variables and an optional .env file.

Settings are read at call time (not import time) so tests can change them.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader, so python-dotenv is not a dependency.
    Values already set in the real environment win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    model: str
    base_url: str
    extra_body: dict
    logs_dir: Path
    max_questions: int
    frozen_date: str | None


def get_settings() -> Settings:
    extra = os.getenv("DEEPSEEK_EXTRA_BODY", "").strip()
    try:
        extra_body = json.loads(extra) if extra else {}
    except json.JSONDecodeError:
        extra_body = {}
    return Settings(
        api_key=os.getenv("DEEPSEEK_API_KEY") or None,
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip(),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
        extra_body=extra_body,
        logs_dir=Path(os.getenv("LOGS_DIR", ROOT / "logs")),
        max_questions=int(os.getenv("MAX_QUESTIONS", "5")),
        frozen_date=os.getenv("FROZEN_DATE") or None,
    )


def today() -> date:
    """The date the system tells the model is 'today'.

    The model cannot know the date (Lecture 08), so the system supplies it.
    FROZEN_DATE (optional) fixes it for testing.
    """
    s = get_settings()
    return date.fromisoformat(s.frozen_date) if s.frozen_date else date.today()
