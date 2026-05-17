from __future__ import annotations

import re
from dataclasses import dataclass, field


class ContextAliasError(ValueError):
    pass


CONTEXT_CALL_RE = re.compile(r'CONTEXT\((?:"((?:[^"\\]|\\.)*)"|([^)]*))\)')
ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")


@dataclass
class ContextRegistry:
    aliases: dict[str, str] = field(default_factory=dict)

    def set(self, name: str, path: str) -> None:
        name = name.strip()
        path = path.strip()

        if not ALIAS_RE.fullmatch(name):
            raise ContextAliasError("Context alias must match [A-Za-z_][A-Za-z0-9_-]*.")

        if not path:
            raise ContextAliasError("Context path must not be empty.")

        self.aliases[name] = path

    def resolve_source(self, source: str) -> str:
        def replace(match: re.Match[str]) -> str:
            quoted = match.group(1)
            raw = quoted if quoted is not None else match.group(2) or ""
            value = _unescape(raw.strip())

            if value not in self.aliases:
                return match.group(0)

            return f'CONTEXT("{_escape(self.aliases[value])}")'

        return CONTEXT_CALL_RE.sub(replace, source)

def parse_context_alias_option(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise ContextAliasError("Use --context-alias name=path.")

    name, path = value.split("=", 1)
    return name.strip(), path.strip()


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', r"\"")


def _unescape(value: str) -> str:
    return value.replace(r"\"", '"').replace(r"\\", "\\")
