from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class WorkspaceError(ValueError):
    pass


@dataclass
class Workspace:
    name: str
    contexts: dict[str, str] = field(default_factory=dict)
    prompts: dict[str, dict[str, Any]] = field(default_factory=dict)
    workflows: dict[str, str] = field(default_factory=dict)
    artifacts: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> Workspace:
        contexts = data.get("contexts", {})
        prompts = data.get("prompts", {})
        workflows = data.get("workflows", {})
        artifacts = data.get("artifacts", [])

        return cls(
            name=name,
            contexts=contexts if isinstance(contexts, dict) else {},
            prompts=_normalize_prompts(prompts),
            workflows=workflows if isinstance(workflows, dict) else {},
            artifacts=artifacts if isinstance(artifacts, list) else [],
        )

class WorkspaceStore:
    def __init__(self, root: Path | str = ".rick/workspaces") -> None:
        self.root = Path(root)

    def load(self, name: str) -> Workspace:
        self._validate_name(name)
        path = self._path(name)

        if not path.exists():
            return Workspace(name=name)

        data = json.loads(path.read_text(encoding="utf-8"))
        return Workspace.from_dict(name, data if isinstance(data, dict) else {})

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def _validate_name(self, name: str) -> None:
        if not name or not re.fullmatch(r"[A-Za-z0-9._-]+", name):
            raise WorkspaceError("Workspace name must contain only letters, digits, dots, dashes and underscores.")


def _normalize_prompts(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, dict[str, Any]] = {}

    for name, prompt in value.items():
        if isinstance(prompt, str):
            normalized[str(name)] = {"template": prompt, "seed": True, "model": "medium"}
            continue

        if isinstance(prompt, dict):
            template = str(prompt.get("template", ""))
            seed = bool(prompt.get("seed", True))
            model = str(prompt.get("model", "medium"))
            normalized[str(name)] = {"template": template, "seed": seed, "model": model}

    return normalized
