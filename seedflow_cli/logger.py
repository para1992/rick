from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MarkdownStepLogger:
    def __init__(self, path: Path | None) -> None:
        self.path = path

        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                f"# SeedFlow run\n\nStarted: {datetime.now(timezone.utc).isoformat()}\n\n",
                encoding="utf-8",
            )
            _chmod_private(self.path)

    def log(self, title: str, body: str) -> None:
        if self.path is None:
            return

        with self.path.open("a", encoding="utf-8") as file:
            file.write(f"## {title}\n\n")
            file.write(body.strip())
            file.write("\n\n")


class JsonRunStore:
    def __init__(self, path: Path | None, workflow_source: str = "") -> None:
        self.path = path
        self.data: dict[str, Any] = {
            "workflow_source": workflow_source,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "events": [],
            "final_state": None,
        }

        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write()

    def event(self, event_type: str, title: str, payload: dict[str, Any]) -> None:
        if self.path is None:
            return

        self.data["events"].append(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "type": event_type,
                "title": title,
                "payload": payload,
            }
        )
        self._write()

    def final(self, payload: dict[str, Any]) -> None:
        if self.path is None:
            return

        self.data["finished_at"] = datetime.now(timezone.utc).isoformat()
        self.data["final_state"] = payload
        self._write()

    def _write(self) -> None:
        if self.path is None:
            return

        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        _chmod_private(self.path)


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
