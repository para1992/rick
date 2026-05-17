from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
CONTEXT_LOG_MODES = {"full", "metadata", "off"}
SECRET_NAME_RE = re.compile(r"(?i)(^|[_\-.])(secret|token|api[_\-.]?key|password|passwd|private[_\-.]?key|credential)s?($|[_\-.])")
SENSITIVE_PATH_PARTS = {".env", ".git", ".ssh", ".aws", ".gcp", ".azure"}
DENIED_MATERIALIZE_NAMES = {".env", ".gitignore", ".python-version"}
DENIED_MATERIALIZE_PARTS = {".git", ".ssh", ".aws", ".gcp", ".azure", "__pycache__"}


@dataclass(frozen=True)
class SecurityOptions:
    allow_context_outside_cwd: bool = False
    context_log_mode: str = "metadata"
    allow_custom_base_url: bool = False
    allow_verify: bool = False
    allow_materialize_outside_runs: bool = False
    allow_materialize_dotfiles: bool = False
    allow_materialize_overwrite: bool = False
    max_materialize_files: int = 80
    max_materialize_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        if self.context_log_mode not in CONTEXT_LOG_MODES:
            raise ValueError(f"context_log_mode must be one of: {', '.join(sorted(CONTEXT_LOG_MODES))}.")


def validate_openrouter_base_url(base_url: str, security: SecurityOptions) -> str:
    normalized = base_url.rstrip("/")
    if normalized != DEFAULT_OPENROUTER_BASE_URL and not security.allow_custom_base_url:
        raise RuntimeError(
            "Custom OPENROUTER_BASE_URL is blocked by default because it receives the API key. "
            "Use --allow-custom-base-url only for a trusted endpoint."
        )
    return normalized


def validate_context_path(path: Path, cwd: Path, security: SecurityOptions) -> Path:
    resolved = path.expanduser().resolve()
    cwd = cwd.resolve()

    if not security.allow_context_outside_cwd and not _is_relative_to(resolved, cwd):
        raise RuntimeError(f"CONTEXT refused path outside current directory: {path}")

    lowered_parts = {part.lower() for part in resolved.parts}
    name = resolved.name.lower()
    if name in SENSITIVE_PATH_PARTS or lowered_parts & SENSITIVE_PATH_PARTS or SECRET_NAME_RE.search(resolved.name):
        raise RuntimeError(f"CONTEXT refused sensitive path: {path}")

    return resolved


def context_payload(file_path: str, content: str, original_chars: int, included_chars: int, truncated: bool, mode: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "file_path": file_path,
        "original_chars": original_chars,
        "included_chars": included_chars,
        "truncated": truncated,
        "log_mode": mode,
    }

    if mode == "full":
        payload["content"] = content
    elif mode == "metadata":
        payload["content_redacted"] = True

    return payload


def validate_materialize_target(target_root: Path, security: SecurityOptions) -> Path:
    resolved = target_root.expanduser().resolve()
    runs_root = (Path.cwd() / "runs").resolve()

    if not security.allow_materialize_outside_runs and not _is_relative_to(resolved, runs_root):
        raise RuntimeError(
            f"MATERIALIZE target must be under runs/ by default: {target_root}. "
            "Use --allow-materialize-outside-runs for trusted workflows."
        )

    return resolved


def validate_materialize_relative_path(relative_path: Path, security: SecurityOptions) -> None:
    lowered_parts = [part.lower() for part in relative_path.parts]

    if not security.allow_materialize_dotfiles:
        for part in lowered_parts:
            if part.startswith(".") or part in DENIED_MATERIALIZE_NAMES or part in DENIED_MATERIALIZE_PARTS or SECRET_NAME_RE.search(part):
                raise RuntimeError(f"MATERIALIZE refused sensitive or hidden file path: {relative_path}")


def validate_materialize_limits(files_count: int, total_bytes: int, security: SecurityOptions) -> None:
    if files_count > security.max_materialize_files:
        raise RuntimeError(f"MATERIALIZE refused {files_count} files; limit is {security.max_materialize_files}.")

    if total_bytes > security.max_materialize_bytes:
        raise RuntimeError(f"MATERIALIZE refused {total_bytes} bytes; limit is {security.max_materialize_bytes}.")


def secure_write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
