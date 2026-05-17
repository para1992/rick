from __future__ import annotations

import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import AnyFormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea

from .rick import colored_rick_panel_fragments, scene_key_for
from .runner import WorkflowRunOptions, run_workflow
from .security import SecurityOptions


MAX_EVENTS = 220
MAX_OUTPUT_CHARS = 8000
DEFAULT_INTERACTIVE_RUN_ROOT = Path("runs/interactive")
DOG_FRAME_SECONDS = 0.28
STEP_RE = re.compile(
    r'(?P<string>"(?:[^"\\]|\\.)*")'
    r"|(?P<step>\b(?:RESOLVE|CONTEXT|GEN_BEFORE|GEN_AFTER|GEN|UNFOLD_JUDGE|UNFOLD|JUDGE|OUTPUT_AI_GLUE|OUTPUT_GLUE|EDIT|MATERIALIZE|VERIFY)\b)"
    r"|(?P<number>\b\d+\b)"
    r"|(?P<command>/[a-zA-Z][a-zA-Z0-9_-]*)"
    r"|(?P<op>[>(),>])"
)


@dataclass(frozen=True)
class TuiEvent:
    kind: str
    text: str
    stamp: str


def run_tui(args: Any) -> int:
    return RickTui(args).run()


class RickTui:
    def __init__(self, args: Any) -> None:
        self.args = args
        self._lock = threading.RLock()
        self._events: list[TuiEvent] = []
        self._stage = "MODEL"
        self._busy = False
        self._counter = 0
        self._started_at = time.monotonic()
        self._app: Application | None = None

        self._chat_control = FormattedTextControl(self._chat_fragments, focusable=False)
        self.input = TextArea(
            height=3,
            prompt=[("class:prompt", "> ")],
            multiline=False,
            accept_handler=self._accept_input,
            lexer=WorkflowLexer(),
        )

        self._append(
            "system",
            "Rick TUI ready. Type a workflow DSL expression and press Enter. Use /help for commands.",
        )

    def run(self) -> int:
        key_bindings = KeyBindings()

        @key_bindings.add("c-c")
        @key_bindings.add("c-q")
        def _(event) -> None:
            event.app.exit(result=0)

        @key_bindings.add("f2")
        def _(event) -> None:
            self._clear_events()

        root = HSplit(
            [
                Window(FormattedTextControl(self._header_fragments), height=1),
                VSplit(
                    [
                        Frame(
                            Window(
                                self._chat_control,
                                wrap_lines=True,
                                always_hide_cursor=True,
                            ),
                            title="context",
                        ),
                        Window(width=1, char=" "),
                        Frame(
                            Window(
                                FormattedTextControl(self._dog_fragments),
                                width=D(min=40, preferred=54, max=54),
                                dont_extend_width=True,
                            ),
                            title="rick",
                        ),
                    ]
                ),
                Frame(self.input, title="workflow"),
                Window(FormattedTextControl(self._footer_fragments), height=1),
            ]
        )

        self._app = Application(
            layout=Layout(root, focused_element=self.input),
            key_bindings=key_bindings,
            full_screen=True,
            mouse_support=True,
            style=_style(),
            refresh_interval=0.25,
        )
        return int(self._app.run() or 0)

    def _accept_input(self, buffer) -> bool:
        source = buffer.text.strip()
        buffer.reset()

        if not source:
            return True

        command = source.lower()
        if command in {"/exit", "/quit", "/q"}:
            if self._app is not None:
                self._app.exit(result=0)
            return True

        if command == "/clear":
            self._clear_events()
            return True

        if command == "/help":
            self._append(
                "system",
                "Commands: /help, /clear, /exit. Enter a workflow like RESOLVE(\"Task\",\"DoD\")>GEN(plan,3)>JUDGE>EDIT(strict).",
            )
            return True

        if self._busy:
            self._append("error", "A workflow is already running. Wait for it to finish before starting another one.")
            return True

        self._counter += 1
        self._append("user", source)
        thread = threading.Thread(target=self._run_workflow, args=(source, self._counter), daemon=True)
        thread.start()
        return True

    def _run_workflow(self, source: str, counter: int) -> None:
        self._set_busy(True)
        run_dir = interactive_run_dir(Path(self.args.run_dir), counter)
        self._append("system", f"run dir: {run_dir}")

        try:
            state = run_workflow(
                WorkflowRunOptions(
                    workflow=source,
                    mode=self.args.mode,
                    run_dir=run_dir,
                    log_file=Path(self.args.log_file) if self.args.log_file else None,
                    max_calls=self.args.max_calls,
                    context_max_chars=self.args.context_max_chars,
                    context_aliases=list(self.args.context_alias),
                    workspace=self.args.workspace,
                    status_callback=self._workflow_status,
                    security=_security_options_from_args(self.args),
                )
            )
        except Exception as exc:  # noqa: BLE001 - surface workflow failures inside the TUI.
            self._stage = "ERROR"
            self._append("error", f"{type(exc).__name__}: {exc}")
            return
        finally:
            self._set_busy(False)

        output = state.ai_output or state.raw_output or "(no output)"
        self._stage = "DONE"
        self._append("assistant", _truncate_block(output, MAX_OUTPUT_CHARS))
        self._append("system", "done")

    def _workflow_status(self, message: str) -> None:
        self._stage = scene_key_for(message)
        self._append("status", message)

    def _set_busy(self, value: bool) -> None:
        with self._lock:
            self._busy = value
        self._invalidate()

    def _append(self, kind: str, text: str) -> None:
        with self._lock:
            self._events.append(TuiEvent(kind=kind, text=text, stamp=datetime.now().strftime("%H:%M:%S")))
            self._events = self._events[-MAX_EVENTS:]

        self._invalidate()

    def _clear_events(self) -> None:
        with self._lock:
            self._events = []
            self._stage = "MODEL"

        self._invalidate()

    def _chat_fragments(self) -> AnyFormattedText:
        with self._lock:
            events = list(self._events)

        fragments: list[tuple[str, str]] = []

        for event in events:
            fragments.extend(_event_fragments(event))
            fragments.append(("", "\n"))

        return fragments

    def _header_fragments(self) -> AnyFormattedText:
        with self._lock:
            status = "running" if self._busy else "idle"
            stage = self._stage

        workspace = f" workspace={self.args.workspace}" if self.args.workspace else ""
        return [
            ("class:header", " Rick "),
            ("class:muted", f"stage={stage} status={status}{workspace}"),
        ]

    def _footer_fragments(self) -> AnyFormattedText:
        return [
            ("class:footer", " Enter: run workflow  "),
            ("class:muted", "/help /clear /exit  F2 clear  Ctrl-Q exit"),
        ]

    def _dog_fragments(self) -> AnyFormattedText:
        rows = max(10, shutil.get_terminal_size((120, 40)).lines - 8)
        frame_index = int((time.monotonic() - self._started_at) / DOG_FRAME_SECONDS)
        return colored_rick_panel_fragments(self._stage, rows=rows, frame_index=frame_index, width=52)

    def _invalidate(self) -> None:
        if self._app is not None:
            self._app.invalidate()


def interactive_run_dir(base: Path, counter: int) -> Path:
    if _same_path(base, Path("runs/latest")):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return DEFAULT_INTERACTIVE_RUN_ROOT / f"{stamp}-{counter:02d}"

    return base if counter == 1 else base / f"{counter:02d}"


class WorkflowLexer(Lexer):
    def lex_document(self, document: Document):
        lines = document.lines

        def get_line(lineno: int) -> list[tuple[str, str]]:
            return _syntax_fragments(lines[lineno])

        return get_line


def _event_fragments(event: TuiEvent) -> list[tuple[str, str]]:
    label = {
        "user": "you",
        "assistant": "rick",
        "status": "run",
        "error": "error",
        "system": "system",
    }.get(event.kind, event.kind)
    style = {
        "user": "class:event.user",
        "assistant": "class:event.assistant",
        "status": f"class:stage.{scene_key_for(event.text).lower()}",
        "error": "class:event.error",
        "system": "class:event.system",
    }.get(event.kind, "class:event.system")
    fragments: list[tuple[str, str]] = [
        ("class:event.time", event.stamp),
        ("", " "),
        (style, f"{label}> "),
    ]

    if event.kind in {"user", "status"}:
        fragments.extend(_syntax_fragments(event.text))
    else:
        fragments.append((style, event.text))

    fragments.append(("", "\n"))
    return fragments


def _syntax_fragments(line: str) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = []
    cursor = 0

    for match in STEP_RE.finditer(line):
        if match.start() > cursor:
            fragments.append(("", line[cursor : match.start()]))

        token = match.group(0)
        kind = match.lastgroup or ""
        fragments.append((_syntax_style(kind, token), token))
        cursor = match.end()

    if cursor < len(line):
        fragments.append(("", line[cursor:]))

    return fragments


def _syntax_style(kind: str, token: str) -> str:
    if kind == "string":
        return "class:syntax.string"
    if kind == "number":
        return "class:syntax.number"
    if kind == "command":
        return "class:syntax.command"
    if kind == "op":
        return "class:syntax.op"
    if kind == "step":
        return f"class:step.{token.lower()}"
    return ""


def _same_path(left: Path, right: Path) -> bool:
    return os.fspath(left) == os.fspath(right)


def _truncate_block(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value

    return value[:limit].rstrip() + f"\n\n[truncated to {limit} chars]"


def _style() -> Style:
    return Style.from_dict(
        {
            "header": "bold #7dd3fc",
            "footer": "#94a3b8",
            "muted": "#64748b",
            "prompt": "bold #7dd3fc",
            "event.time": "#64748b",
            "event.user": "bold #7dd3fc",
            "event.assistant": "#dcfce7",
            "event.status": "#cbd5e1",
            "event.error": "bold #f87171",
            "event.system": "#94a3b8",
            "syntax.string": "#86efac",
            "syntax.number": "#fde68a",
            "syntax.command": "bold #7dd3fc",
            "syntax.op": "#f472b6",
            "step.resolve": "bold #38bdf8",
            "step.context": "bold #818cf8",
            "step.gen": "bold #22d3ee",
            "step.gen_before": "bold #67e8f9",
            "step.gen_after": "bold #67e8f9",
            "step.unfold": "bold #c084fc",
            "step.unfold_judge": "bold #c084fc",
            "step.judge": "bold #facc15",
            "step.output_glue": "bold #34d399",
            "step.output_ai_glue": "bold #34d399",
            "step.edit": "bold #4ade80",
            "step.materialize": "bold #fb923c",
            "step.verify": "bold #f97316",
            "stage.resolve": "#38bdf8",
            "stage.define_dod": "#38bdf8",
            "stage.context": "#818cf8",
            "stage.gen": "#22d3ee",
            "stage.gen_before": "#67e8f9",
            "stage.gen_after": "#67e8f9",
            "stage.unfold": "#c084fc",
            "stage.judge": "#facc15",
            "stage.random": "#facc15",
            "stage.model": "#f472b6",
            "stage.glue": "#34d399",
            "stage.ai_glue": "#34d399",
            "stage.edit": "#4ade80",
            "stage.done": "#4ade80",
            "stage.error": "bold #f87171",
            "dog": "#f8fafc",
            "dog.border": "#64748b",
            "dog.prop": "#e2e8f0",
            "frame.border": "#334155",
            "frame.label": "#7dd3fc",
        }
    )


def _security_options_from_args(args: Any) -> SecurityOptions:
    return SecurityOptions(
        allow_context_outside_cwd=args.allow_context_outside_cwd,
        context_log_mode=args.context_log_mode,
        allow_custom_base_url=args.allow_custom_base_url,
        allow_verify=args.allow_verify,
        allow_materialize_outside_runs=args.allow_materialize_outside_runs,
        allow_materialize_dotfiles=args.allow_materialize_dotfiles,
        allow_materialize_overwrite=args.allow_materialize_overwrite,
    )
