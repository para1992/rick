from __future__ import annotations

import argparse
import os
from json import JSONDecodeError
from pathlib import Path

from .context_aliases import ContextAliasError
from .engine import WorkflowBudgetExceeded
from .env import load_dotenv
from .llm import LLMError
from .parser import ParseError
from .preflight import PreflightError
from .rick import RickAnimator, demo_rick_animation
from .runner import WorkflowRunOptions, run_workflow
from .security import SecurityOptions
from .workspaces import WorkspaceError


def main(argv: list[str] | None = None) -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(prog="rick")
    parser.add_argument("workflow", nargs="?", help='Example: RESOLVE("TASK","DOD")>CONTEXT(docs/spec.md)>GEN(angle,3)>JUDGE>GEN(plan,3)>JUDGE>GEN(draft,3)>JUDGE>EDIT(strict)')
    parser.add_argument("--interactive", "-i", action="store_true", help="Open the full-screen Rick TUI")
    parser.add_argument("--rick-demo", action="store_true", help="Run local Rick animation demo without LLM calls")
    parser.add_argument("--status", action="store_true", help="Print realtime step and LLM-call statuses in one-shot mode")
    parser.add_argument("--mode", default="", help="Supported: LOG_STEP")
    parser.add_argument("--run-dir", default="runs/latest", help="Directory for run.json and default log.md")
    parser.add_argument("--log-file", default="", help="Markdown log path for --mode LOG_STEP. Default: <run-dir>/log.md")
    parser.add_argument(
        "--max-calls",
        type=int,
        default=int(os.getenv("RICK_MAX_CALLS", "60")),
        help="Maximum LLM calls allowed for this run",
    )
    parser.add_argument("--context-max-chars", type=int, default=8000, help="Maximum characters included from each CONTEXT(file) step")
    parser.add_argument("--context-log-mode", choices=["full", "metadata", "off"], default="metadata", help="How much CONTEXT content is written to run logs")
    parser.add_argument("--context-alias", action="append", default=[], help="Register context alias for this run. Example: --context-alias spec=docs/spec.md")
    parser.add_argument("--workspace", default="", help="Load context and prompt aliases from .rick/workspaces/<name>.json for one-shot CLI runs")
    parser.add_argument("--allow-context-outside-cwd", action="store_true", help="Allow CONTEXT paths outside the current directory")
    parser.add_argument("--allow-custom-base-url", action="store_true", help="Allow custom OPENROUTER_BASE_URL")
    parser.add_argument("--allow-verify", action="store_true", help="Allow VERIFY shell commands")
    parser.add_argument("--allow-materialize-outside-runs", action="store_true", help="Allow MATERIALIZE targets outside runs/")
    parser.add_argument("--allow-materialize-dotfiles", action="store_true", help="Allow MATERIALIZE to write dotfiles or sensitive-looking paths")
    parser.add_argument("--allow-materialize-overwrite", action="store_true", help="Allow MATERIALIZE to overwrite existing files")
    args = parser.parse_args(argv)

    if args.rick_demo:
        demo_rick_animation()
        return 0

    if args.interactive:
        from .tui import run_tui

        return run_tui(args)

    if not args.workflow:
        parser.error("workflow is required")

    run_dir = Path(args.run_dir)
    animator = RickAnimator(enabled=args.status)

    try:
        state = run_workflow(
            WorkflowRunOptions(
                workflow=args.workflow,
                mode=args.mode,
                run_dir=run_dir,
                log_file=Path(args.log_file) if args.log_file else None,
                max_calls=args.max_calls,
                context_max_chars=args.context_max_chars,
                context_aliases=args.context_alias,
                workspace=args.workspace,
                status_callback=animator.start if args.status else None,
                security=_security_options_from_args(args),
            )
        )
    except (WorkspaceError, ContextAliasError, ParseError, OSError, ValueError) as exc:
        parser.error(str(exc))
    except PreflightError as exc:
        parser.exit(2, f"preflight error:\n{exc}\n")
    except WorkflowBudgetExceeded as exc:
        parser.exit(2, f"error: {exc}\n")
    except FileNotFoundError as exc:
        parser.exit(2, f"error: context file not found: {exc.filename}\n")
    except PermissionError as exc:
        parser.exit(2, f"error: context file is not readable: {exc.filename}\n")
    except UnicodeDecodeError as exc:
        parser.exit(2, f"error: context file is not valid UTF-8: {exc}\n")
    except LLMError as exc:
        parser.exit(2, f"error: {exc}\n")
    except JSONDecodeError as exc:
        parser.exit(2, f"error: failed to decode JSON: {exc}\n")
    except RuntimeError as exc:
        parser.exit(2, f"error: {exc}\n")

    if state.ai_output:
        animator.stop("done")
        print(state.ai_output)
    else:
        animator.stop("done")
        print(state.raw_output)

    return 0


def _security_options_from_args(args) -> SecurityOptions:
    return SecurityOptions(
        allow_context_outside_cwd=args.allow_context_outside_cwd,
        context_log_mode=args.context_log_mode,
        allow_custom_base_url=args.allow_custom_base_url,
        allow_verify=args.allow_verify,
        allow_materialize_outside_runs=args.allow_materialize_outside_runs,
        allow_materialize_dotfiles=args.allow_materialize_dotfiles,
        allow_materialize_overwrite=args.allow_materialize_overwrite,
    )
