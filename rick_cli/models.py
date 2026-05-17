from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ResolveStep:
    task: str
    dod: str


@dataclass(frozen=True)
class ContextStep:
    file_path: str


@dataclass(frozen=True)
class DefineDodStep:
    candidates_count: int = 1


@dataclass(frozen=True)
class GenerateStep:
    artifact: str
    candidates_count: int


@dataclass(frozen=True)
class GenerateRelativeStep:
    artifact: str
    candidates_count: int
    position: str


@dataclass(frozen=True)
class UnfoldStep:
    source_artifact: str
    child_artifact: str
    candidates_count: int
    judge: bool


@dataclass(frozen=True)
class JudgeStep:
    pass


@dataclass(frozen=True)
class EditStep:
    mode: str


@dataclass(frozen=True)
class MaterializeStep:
    target_dir: str


@dataclass(frozen=True)
class VerifyStep:
    command: str


@dataclass(frozen=True)
class OutputGlueStep:
    pass


@dataclass(frozen=True)
class OutputAiGlueStep:
    glue_mode: str


WorkflowStep = (
    ResolveStep
    | DefineDodStep
    | ContextStep
    | GenerateStep
    | GenerateRelativeStep
    | UnfoldStep
    | JudgeStep
    | EditStep
    | MaterializeStep
    | VerifyStep
    | OutputGlueStep
    | OutputAiGlueStep
)


@dataclass(frozen=True)
class WorkflowProgram:
    steps: list[WorkflowStep]


@dataclass
class ContextBlock:
    file_path: str
    content: str
    original_chars: int
    included_chars: int
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "content": self.content,
            "original_chars": self.original_chars,
            "included_chars": self.included_chars,
            "truncated": self.truncated,
        }


@dataclass
class Candidate:
    id: str
    stage: str
    title: str
    summary: str
    payload_type: str
    payload: dict[str, Any]
    seed_random_string: str
    seed_interpretation: str
    prompt: str = ""
    content: str = ""
    score: float | None = None
    judge_reason: str | None = None
    accepted: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stage": self.stage,
            "title": self.title,
            "summary": self.summary,
            "payload_type": self.payload_type,
            "payload": self.payload,
            "content": self.content,
            "seed": {
                "random_string": self.seed_random_string,
                "interpretation": self.seed_interpretation,
            },
            "score": self.score,
            "judge_reason": self.judge_reason,
            "accepted": self.accepted,
            "metadata": self.metadata,
        }


@dataclass
class JudgeDecision:
    stage: str
    selected_index: int
    reason: str
    score: float | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class MaterializedFile:
    path: str
    bytes_written: int
    source_candidate_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "bytes_written": self.bytes_written,
            "source_candidate_id": self.source_candidate_id,
        }


@dataclass
class VerificationResult:
    command: str
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class WorkflowState:
    task: str = ""
    dod: str = ""
    stage: str = ""
    contexts: list[ContextBlock] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    accepted_candidates: list[Candidate] = field(default_factory=list)
    selected_candidate: Candidate | None = None
    judge_decisions: list[JudgeDecision] = field(default_factory=list)
    raw_output: str = ""
    ai_output: str = ""
    call_count: int = 0
    step_log: list[str] = field(default_factory=list)
    materialized_root: str = ""
    materialized_files: list[MaterializedFile] = field(default_factory=list)
    verification_results: list[VerificationResult] = field(default_factory=list)
