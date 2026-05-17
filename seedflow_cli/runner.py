from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .context_aliases import ContextRegistry, parse_context_alias_option
from .engine import WorkflowEngine
from .llm import make_llm_client
from .logger import JsonRunStore, MarkdownStepLogger
from .parser import parse_program
from .preflight import validate_workflow_program
from .security import SecurityOptions
from .workspaces import WorkspaceStore


@dataclass(frozen=True)
class WorkflowRunOptions:
    workflow: str
    mode: str = ""
    run_dir: Path = Path("runs/latest")
    log_file: Path | None = None
    max_calls: int = 60
    context_max_chars: int = 8000
    context_aliases: list[str] = field(default_factory=list)
    workspace: str = ""
    status_callback: Callable[[str], None] | None = None
    security: SecurityOptions = field(default_factory=SecurityOptions)


def run_workflow(options: WorkflowRunOptions):
    workspace = WorkspaceStore().load(options.workspace) if options.workspace else None

    context_registry = ContextRegistry()
    if workspace is not None:
        context_registry.aliases.update(workspace.contexts)

    for value in options.context_aliases:
        name, path = parse_context_alias_option(value)
        context_registry.set(name, path)

    workflow_source = context_registry.resolve_source(options.workflow)
    program = parse_program(workflow_source)
    validate_workflow_program(program, workspace.prompts if workspace is not None else {}, require_prompt_aliases=False)

    log_path = options.log_file if options.log_file is not None else options.run_dir / "log.md"
    logger = MarkdownStepLogger(log_path if options.mode == "LOG_STEP" else None)
    run_store = JsonRunStore(options.run_dir / "run.json", workflow_source=workflow_source)
    engine = WorkflowEngine(
        make_llm_client(options.security),
        logger,
        run_store=run_store,
        max_calls=options.max_calls,
        context_max_chars=options.context_max_chars,
        status_callback=options.status_callback,
        artifact_prompts=workspace.prompts if workspace is not None else None,
        security=options.security,
    )
    return engine.run(program)
