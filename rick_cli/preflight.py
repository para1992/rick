from __future__ import annotations

from pathlib import Path

from .models import ContextStep, GenerateRelativeStep, GenerateStep, UnfoldStep, WorkflowProgram


class PreflightError(ValueError):
    pass


def validate_workflow_program(
    program: WorkflowProgram,
    prompt_aliases: dict,
    cwd: Path | None = None,
    require_prompt_aliases: bool = True,
) -> None:
    cwd = cwd or Path.cwd()
    errors: list[str] = []

    for step in program.steps:
        if isinstance(step, ContextStep):
            path = Path(step.file_path).expanduser()
            resolved = path if path.is_absolute() else cwd / path

            if not resolved.exists():
                errors.append(f"CONTEXT path does not exist: {step.file_path}")
            elif not resolved.is_file():
                errors.append(f"CONTEXT path is not a file: {step.file_path}")

        if require_prompt_aliases and isinstance(step, GenerateStep):
            if not _has_prompt_alias(prompt_aliases, step.artifact):
                errors.append(f"GEN({step.artifact},{step.candidates_count}) has no prompt alias in current workspace")

        if require_prompt_aliases and isinstance(step, GenerateRelativeStep):
            if not _has_prompt_alias(prompt_aliases, step.artifact):
                errors.append(
                    f"GEN_{step.position.upper()}({step.artifact},{step.candidates_count}) has no prompt alias in current workspace"
                )

        if require_prompt_aliases and isinstance(step, UnfoldStep):
            if not _has_prompt_alias(prompt_aliases, step.child_artifact):
                errors.append(
                    f"UNFOLD child artifact {step.child_artifact} has no prompt alias in current workspace"
                )

    if errors:
        raise PreflightError("\n".join(errors))


def _has_prompt_alias(prompt_aliases: dict, artifact: str) -> bool:
    return artifact in prompt_aliases or artifact.lower() in prompt_aliases
