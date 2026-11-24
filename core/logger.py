"""Interaction log: one JSON line per event, one file per session.

These logs are the raw data for the Phase 3 comparison of Condition A and B
(answer time, what was left out, what was corrected). Logs stay local:
logs/ is in .gitignore. Never log the API key.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


class SessionLogger:
    def __init__(self, session_id: str, logs_dir: Path | None, enabled: bool = True):
        self.session_id = session_id
        self.events: list[dict] = []
        self.path = None
        if enabled and logs_dir is not None:
            logs_dir.mkdir(parents=True, exist_ok=True)
            self.path = logs_dir / f"session-{session_id}.jsonl"

    def log(self, event: str, **fields) -> None:
        record = {"t": round(time.time(), 3), "session": self.session_id, "event": event, **fields}
        self.events.append(record)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
