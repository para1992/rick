from __future__ import annotations

import re

from .models import (
    ContextStep,
    DefineDodStep,
    EditStep,
    GenerateRelativeStep,
    GenerateStep,
    JudgeStep,
    MaterializeStep,
    OutputAiGlueStep,
    OutputGlueStep,
    ResolveStep,
    UnfoldStep,
    VerifyStep,
    WorkflowProgram,
    WorkflowStep,
)


class ParseError(ValueError):
    pass


def parse_program(source: str) -> WorkflowProgram:
    parts = _split_workflow_steps(source)

    if not parts:
        raise ParseError("Workflow expression is empty.")

    steps: list[WorkflowStep] = []

    for index, part in enumerate(parts):
        if part.startswith("RESOLVE("):
            if index != 0:
                raise ParseError("RESOLVE must be the first step.")
            steps.append(_parse_resolve(part))
            continue

        if part.startswith("CONTEXT("):
            steps.append(_parse_context(part))
            continue

        if part.startswith("GEN("):
            steps.append(_parse_gen(part))
            continue

        if part.startswith("GEN_BEFORE("):
            step = _parse_gen_relative(part, "GEN_BEFORE", "before")
            steps.append(step)
            continue

        if part.startswith("GEN_AFTER("):
            step = _parse_gen_relative(part, "GEN_AFTER", "after")
            steps.append(step)
            continue

        if part.startswith("UNFOLD_JUDGE("):
            steps.append(_parse_unfold(part, "UNFOLD_JUDGE", judge=True))
            continue

        if part.startswith("UNFOLD("):
            steps.append(_parse_unfold(part, "UNFOLD", judge=False))
            continue

        if part == "JUDGE":
            steps.append(JudgeStep())
            continue

        if part.startswith("EDIT("):
            steps.append(EditStep(mode=_parse_mode(part, "EDIT")))
            continue

        if part.startswith("MATERIALIZE("):
            steps.append(MaterializeStep(target_dir=_parse_path_arg(part, "MATERIALIZE")))
            continue

        if part.startswith("VERIFY("):
            steps.append(VerifyStep(command=_parse_quoted_arg(part, "VERIFY")))
            continue

        if part == "OUTPUT_GLUE":
            steps.append(OutputGlueStep())
            continue

        if part.startswith("OUTPUT_AI_GLUE("):
            steps.append(OutputAiGlueStep(glue_mode=_parse_mode(part, "OUTPUT_AI_GLUE")))
            continue

        raise ParseError(f"Unknown step: {part}")

    if not isinstance(steps[0], ResolveStep):
        raise ParseError("Workflow must start with RESOLVE(\"TASK\",\"DOD\").")

    if _is_auto_dod_hint(steps[0].dod):
        steps.insert(1, DefineDodStep())

    if not isinstance(steps[-1], OutputGlueStep | OutputAiGlueStep | EditStep | MaterializeStep | VerifyStep):
        steps.append(OutputGlueStep())

    return WorkflowProgram(steps=steps)


def _split_workflow_steps(source: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    in_string = False
    escaped = False

    for char in source.strip():
        current.append(char)

        if escaped:
            escaped = False
            continue

        if in_string and char == "\\":
            escaped = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if char == ">" and not in_string:
            current.pop()
            part = "".join(current).strip()

            if part:
                parts.append(part)

            current = []

    if escaped:
        raise ParseError("Workflow expression ends with an unfinished escape sequence.")

    if in_string:
        raise ParseError("Workflow expression has an unterminated quoted string.")

    final_part = "".join(current).strip()

    if final_part:
        parts.append(final_part)

    return parts


def _parse_resolve(part: str) -> ResolveStep:
    match = re.fullmatch(r'RESOLVE\("((?:[^"\\]|\\.)*)","((?:[^"\\]|\\.)*)"\)', part)

    if not match:
        raise ParseError('Invalid RESOLVE syntax. Use RESOLVE("TASK","DOD").')

    return ResolveStep(task=_unescape(match.group(1)), dod=_unescape(match.group(2)))


def _parse_context(part: str) -> ContextStep:
    match = re.fullmatch(r'CONTEXT\((?:"((?:[^"\\]|\\.)*)"|([^)]*))\)', part)

    if not match:
        raise ParseError('Invalid CONTEXT syntax. Use CONTEXT("docs/spec.md") or CONTEXT(docs/spec.md).')

    file_path = _unescape((match.group(1) or match.group(2) or "").strip())

    if not file_path:
        raise ParseError("CONTEXT file path must not be empty.")

    return ContextStep(file_path=file_path)


def _parse_path_arg(part: str, name: str) -> str:
    match = re.fullmatch(rf'{name}\((?:"((?:[^"\\]|\\.)*)"|([^)]*))\)', part)

    if not match:
        raise ParseError(f'Invalid {name} syntax. Use {name}("path/to/dir") or {name}(path/to/dir).')

    value = _unescape((match.group(1) or match.group(2) or "").strip())

    if not value:
        raise ParseError(f"{name} path must not be empty.")

    return value


def _parse_quoted_arg(part: str, name: str) -> str:
    match = re.fullmatch(rf'{name}\("((?:[^"\\]|\\.)*)"\)', part)

    if not match:
        raise ParseError(f'Invalid {name} syntax. Use {name}("command").')

    value = _unescape(match.group(1)).strip()

    if not value:
        raise ParseError(f"{name} command must not be empty.")

    return value


def _parse_gen(part: str) -> GenerateStep:
    match = re.fullmatch(r'GEN\(\s*(?:"((?:[^"\\]|\\.)*)"|([a-zA-Z0-9_.\-]+))\s*,\s*(\d+)\s*\)', part)

    if not match:
        raise ParseError('Invalid GEN syntax. Use GEN(artifact,3) or GEN("artifact name",3).')

    artifact = _unescape(match.group(1) or match.group(2) or "").strip()
    count = int(match.group(3))

    if not artifact:
        raise ParseError("GEN artifact must not be empty.")

    if count < 1:
        raise ParseError("GEN candidate count must be >= 1.")

    return GenerateStep(artifact=artifact, candidates_count=count)


def _parse_gen_relative(part: str, name: str, position: str) -> GenerateRelativeStep:
    match = re.fullmatch(rf'{name}\(\s*(?:"((?:[^"\\]|\\.)*)"|([a-zA-Z0-9_.\-]+))\s*,\s*(\d+)\s*\)', part)

    if not match:
        raise ParseError(f'Invalid {name} syntax. Use {name}(artifact,3) or {name}("artifact name",3).')

    artifact = _unescape(match.group(1) or match.group(2) or "").strip()
    count = int(match.group(3))

    if not artifact:
        raise ParseError(f"{name} artifact must not be empty.")

    if count < 1:
        raise ParseError(f"{name} candidate count must be >= 1.")

    return GenerateRelativeStep(artifact=artifact, candidates_count=count, position=position)


def _parse_unfold(part: str, name: str, judge: bool) -> UnfoldStep:
    atom = r'(?:"((?:[^"\\]|\\.)*)"|([a-zA-Z0-9_.\-]+))'
    match = re.fullmatch(rf'{name}\(\s*{atom}\s*,\s*{atom}\s*,\s*(\d+)\s*\)', part)

    if not match:
        raise ParseError(f'Invalid {name} syntax. Use {name}(source_artifact,child_artifact,3).')

    source_artifact = _unescape(match.group(1) or match.group(2) or "").strip()
    child_artifact = _unescape(match.group(3) or match.group(4) or "").strip()
    count = int(match.group(5))

    if not source_artifact:
        raise ParseError(f"{name} source artifact must not be empty.")

    if not child_artifact:
        raise ParseError(f"{name} child artifact must not be empty.")

    if count < 1:
        raise ParseError(f"{name} candidate count must be >= 1.")

    return UnfoldStep(source_artifact=source_artifact, child_artifact=child_artifact, candidates_count=count, judge=judge)


def _parse_mode(part: str, name: str) -> str:
    match = re.fullmatch(rf'{name}\((?:"((?:[^"\\]|\\.)*)"|([a-zA-Z0-9_\-]+))\)', part)

    if not match:
        raise ParseError(f"Invalid {name} syntax. Use {name}(strict) or {name}(\"strict mode\").")

    return _unescape(match.group(1) or match.group(2) or "")


def _unescape(value: str) -> str:
    return value.replace(r"\"", '"').replace(r"\\", "\\")


def _is_auto_dod_hint(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {"", "auto", "__auto_dod__"}
