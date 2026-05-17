from __future__ import annotations

import json
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .llm import LLMClient
from .llm import model_for_tier
from .logger import JsonRunStore, MarkdownStepLogger
from .models import (
    Candidate,
    ContextBlock,
    ContextStep,
    DefineDodStep,
    EditStep,
    GenerateRelativeStep,
    GenerateStep,
    JudgeDecision,
    JudgeStep,
    MaterializedFile,
    MaterializeStep,
    OutputAiGlueStep,
    OutputGlueStep,
    ResolveStep,
    UnfoldStep,
    VerificationResult,
    VerifyStep,
    WorkflowProgram,
    WorkflowState,
)
from .prompts import (
    SSOT_DAG_SYSTEM_PROMPT,
    ai_glue_prompt,
    define_dod_prompt,
    direct_output_prompt,
    edit_prompt,
    explode_prompt,
    generate_candidate_prompt,
    judge_prompt,
    raw_glue,
)
from .security import (
    SecurityOptions,
    context_payload,
    secure_write_text,
    validate_context_path,
    validate_materialize_limits,
    validate_materialize_relative_path,
    validate_materialize_target,
)


class WorkflowBudgetExceeded(RuntimeError):
    pass


class CandidateValidationError(RuntimeError):
    pass


class WorkflowEngine:
    def __init__(
        self,
        llm: LLMClient,
        logger: MarkdownStepLogger,
        run_store: JsonRunStore | None = None,
        max_calls: int = 60,
        context_max_chars: int = 8000,
        status_callback: Callable[[str], None] | None = None,
        artifact_prompts: dict[str, Any] | None = None,
        security: SecurityOptions | None = None,
    ) -> None:
        self.llm = llm
        self.logger = logger
        self.run_store = run_store
        self.max_calls = max_calls
        self.context_max_chars = context_max_chars
        self.status_callback = status_callback
        self.artifact_prompts = artifact_prompts or {}
        self.security = security or SecurityOptions()
        self.calls_used = 0

    def run(self, program: WorkflowProgram) -> WorkflowState:
        state = WorkflowState()

        for step in program.steps:
            self._status(f"step: {step.__class__.__name__}")
            if isinstance(step, ResolveStep):
                self._resolve(state, step)
            elif isinstance(step, DefineDodStep):
                self._define_dod(state, step)
            elif isinstance(step, ContextStep):
                self._context(state, step)
            elif isinstance(step, GenerateStep):
                self._auto_select_random_if_needed(state, f"before GEN({step.artifact})")
                self._generate(state, step.artifact, step.candidates_count)
            elif isinstance(step, GenerateRelativeStep):
                self._auto_select_random_if_needed(state, f"before GEN_{step.position.upper()}({step.artifact})")
                self._generate_relative(state, step)
            elif isinstance(step, UnfoldStep):
                self._auto_select_random_if_needed(state, f"before UNFOLD({step.source_artifact})")
                self._unfold(state, step)
            elif isinstance(step, JudgeStep):
                self._judge(state, explicit=True)
            elif isinstance(step, OutputGlueStep):
                self._auto_select_random_if_needed(state, "before OUTPUT_GLUE")
                self._output_glue(state)
            elif isinstance(step, OutputAiGlueStep):
                self._auto_select_random_if_needed(state, "before OUTPUT_AI_GLUE")
                self._output_ai_glue(state, step)
            elif isinstance(step, EditStep):
                self._auto_select_random_if_needed(state, "before EDIT")
                self._edit(state, step)
            elif isinstance(step, MaterializeStep):
                self._auto_select_random_if_needed(state, "before MATERIALIZE")
                self._materialize(state, step)
            elif isinstance(step, VerifyStep):
                self._verify(state, step)

        state.call_count = self.calls_used

        if self.run_store is not None:
            self.run_store.final(_state_to_dict(state))

        return state

    def _resolve(self, state: WorkflowState, step: ResolveStep) -> None:
        state.task = step.task
        state.dod = step.dod
        state.stage = "RESOLVE"
        body = f"Task:\n\n```text\n{state.task}\n```\n\nDoD:\n\n```text\n{state.dod}\n```"
        self._log("RESOLVE", body, {"task": state.task, "dod": state.dod})

    def _context(self, state: WorkflowState, step: ContextStep) -> None:
        state.stage = "CONTEXT"

        if self.context_max_chars < 1:
            raise RuntimeError("context_max_chars must be >= 1.")

        path = validate_context_path(Path(step.file_path), Path.cwd(), self.security)
        content = path.read_text(encoding="utf-8")
        original_chars = len(content)
        included = content[: self.context_max_chars]
        truncated = original_chars > len(included)
        block = ContextBlock(
            file_path=str(path),
            content=included,
            original_chars=original_chars,
            included_chars=len(included),
            truncated=truncated,
        )
        state.contexts.append(block)

        payload = context_payload(
            file_path=block.file_path,
            content=block.content,
            original_chars=block.original_chars,
            included_chars=block.included_chars,
            truncated=block.truncated,
            mode=self.security.context_log_mode,
        )
        if self.security.context_log_mode != "off":
            self._log(
                "CONTEXT",
                "Loaded context file:\n\n```text\n"
                + str(path)
                + "\n```\n\nStats:\n\n```json\n"
                + json.dumps(
                    {
                        "original_chars": original_chars,
                        "included_chars": len(included),
                        "truncated": truncated,
                        "log_mode": self.security.context_log_mode,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n```",
                payload,
            )

    def _define_dod(self, state: WorkflowState, step: DefineDodStep) -> None:
        state.stage = "DEFINE_DOD"
        prompt = define_dod_prompt(state.task, state.dod, self._runtime_context(state))
        response = self._chat_json(
            "DEFINE_DOD",
            [
                {"role": "system", "content": "Return JSON only with a dod object. This is a hidden judging rubric, not user-facing content."},
                {"role": "user", "content": prompt},
            ],
            model=model_for_tier("medium"),
        )
        original_dod = state.dod
        state.dod = json.dumps(response.get("dod", response), ensure_ascii=False, indent=2)
        self._log(
            "DEFINE_DOD",
            "```json\n" + state.dod + "\n```",
            {
                "original_dod": original_dod,
                "generated_dod": response,
            },
        )

    def _generate(self, state: WorkflowState, artifact: str, candidates_count: int) -> None:
        stage = _stage_from_artifact(artifact)
        state.stage = stage
        accepted_context = [_candidate_to_context_dict(candidate) for candidate in state.accepted_candidates]

        if state.selected_candidate is not None and state.selected_candidate not in state.accepted_candidates:
            accepted_context.append(_candidate_to_context_dict(state.selected_candidate))

        candidates: list[Candidate] = []

        for index in range(1, candidates_count + 1):
            prompt = generate_candidate_prompt(
                artifact,
                state.task,
                state.dod,
                self._runtime_context(state),
                accepted_context,
                index,
                candidates_count,
                self._prompt_for_artifact(artifact),
            )
            response = self._chat_candidate_json(
                f"GEN({artifact}) candidate {index}",
                artifact,
                [
                    {"role": "system", "content": self._candidate_system_prompt(artifact)},
                    {"role": "user", "content": prompt},
                ],
                model=self._model_for_artifact(artifact),
            )
            candidate = _candidate_from_json(response.get("candidate", response), stage, index, prompt, self.calls_used)
            candidate.metadata["artifact"] = artifact
            candidates.append(candidate)
            self._log_candidate(stage, index, prompt, response, candidate)

        state.candidates = candidates
        state.selected_candidate = None

    def _generate_relative(self, state: WorkflowState, step: GenerateRelativeStep) -> None:
        stage = _stage_from_artifact(step.artifact)
        state.stage = stage
        accepted_context = [_candidate_to_context_dict(candidate) for candidate in state.accepted_candidates]
        current_document = state.raw_output.strip()
        scoped_document = _relative_document_scope(step.artifact, step.position, current_document)
        expansion_context = {
            "relative_position": step.position,
            "artifact": step.artifact,
            "current_document": scoped_document,
            "current_document_scope": _relative_document_scope_label(step.artifact, step.position),
            "current_document_total_chars": len(current_document),
            "accepted_context": accepted_context,
            "document_instruction": _relative_document_instruction(step.position),
        }
        candidates: list[Candidate] = []

        for index in range(1, step.candidates_count + 1):
            prompt = generate_candidate_prompt(
                step.artifact,
                state.task,
                state.dod,
                self._runtime_context(state),
                accepted_context,
                index,
                step.candidates_count,
                self._prompt_for_artifact(step.artifact),
                expansion_context,
            )
            response = self._chat_candidate_json(
                f"GEN_{step.position.upper()}({step.artifact}) candidate {index}",
                step.artifact,
                [
                    {"role": "system", "content": self._candidate_system_prompt(step.artifact)},
                    {"role": "user", "content": prompt},
                ],
                model=self._model_for_artifact(step.artifact),
            )
            candidate = _candidate_from_json(response.get("candidate", response), stage, index, prompt, self.calls_used)
            candidate.metadata["artifact"] = step.artifact
            candidate.metadata["relative_position"] = step.position
            candidate.metadata["relative_base_raw_output"] = current_document
            candidates.append(candidate)
            self._log_candidate(stage, index, prompt, response, candidate)

        state.candidates = candidates
        state.selected_candidate = None

    def _unfold(self, state: WorkflowState, step: UnfoldStep) -> None:
        state.stage = "UNFOLD_JUDGE" if step.judge else "UNFOLD"
        source = self._find_accepted_artifact(state, step.source_artifact)

        if source is None:
            raise RuntimeError(f"UNFOLD source artifact not found in accepted candidates: {step.source_artifact}")

        units = self._explode_units(state, step.source_artifact, source)
        selected_children: list[Candidate] = []

        for unit_index, unit in enumerate(units, start=1):
            state.candidates = self._generate_unfold_candidates(state, step, source, unit_index, units, selected_children)
            state.selected_candidate = None
            state.stage = _stage_from_artifact(step.child_artifact)

            if step.judge:
                self._judge(state, explicit=True)
            else:
                self._auto_select_random_if_needed(state, f"inside UNFOLD unit {unit_index}")

            if state.selected_candidate is not None:
                selected_children.append(state.selected_candidate)

        if selected_children:
            state.raw_output = "\n\n".join(_candidate_output(child) for child in selected_children if _candidate_output(child)).strip()
            self._log(
                "UNFOLD result",
                f"```markdown\n{state.raw_output}\n```",
                {
                    "source_artifact": step.source_artifact,
                    "child_artifact": step.child_artifact,
                    "units_count": len(units),
                    "selected_children": [_candidate_to_context_dict(candidate) for candidate in selected_children],
                },
            )

    def _find_accepted_artifact(self, state: WorkflowState, artifact: str) -> Candidate | None:
        stage = _stage_from_artifact(artifact)

        for candidate in reversed(state.accepted_candidates):
            if candidate.payload_type == artifact or candidate.payload_type.lower() == artifact.lower():
                return candidate
            if candidate.stage == stage:
                return candidate
            if str(candidate.metadata.get("artifact", "")).lower() == artifact.lower():
                return candidate

        if state.selected_candidate is not None:
            candidate = state.selected_candidate
            if candidate.payload_type == artifact or candidate.stage == stage:
                return candidate

        return None

    def _explode_units(self, state: WorkflowState, source_artifact: str, source: Candidate) -> list[dict[str, Any]]:
        structured_units = _structured_units_from_candidate(source)
        if structured_units:
            normalized = [_normalize_unit(unit, index) for index, unit in enumerate(structured_units, start=1)]
            self._log(
                "EXPLODE",
                "```json\n"
                + json.dumps(
                    {
                        "units": normalized,
                        "raw_response": {
                            "units": normalized,
                            "fallback_used": False,
                            "reason": "Extracted ordered units from selected candidate structured payload.",
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n```",
                {
                    "source_artifact": source_artifact,
                    "units": normalized,
                    "response": {
                        "units": normalized,
                        "fallback_used": False,
                        "reason": "Extracted ordered units from selected candidate structured payload.",
                    },
                    "selection_policy": "structured_payload",
                },
            )
            return normalized

        if _is_file_manifest_artifact(source_artifact):
            raise RuntimeError(
                "UNFOLD(file_manifest, ...) requires selected file_manifest candidate to provide "
                "payload.structure.data.files or payload.structure.files."
            )

        prompt = explode_prompt(source_artifact, state.task, state.dod, _candidate_to_context_dict(source))
        response = self._chat_json(
            f"EXPLODE({source_artifact})",
            [
                {
                    "role": "system",
                    "content": 'Return JSON only with units, fallback_used and reason. Example: {"units":[{"unit_id":"unit_1","title":"First unit","source_order":1,"content":"Exact source unit","constraints":[],"must_preserve":[]}],"fallback_used":false,"reason":"Extracted ordered units from the selected artifact."}',
                },
                {"role": "user", "content": prompt},
            ],
            model=model_for_tier("low"),
        )
        units = response.get("units", [])

        if not isinstance(units, list) or not units:
            units = [_fallback_unit(source)]

        normalized = [_normalize_unit(unit, index) for index, unit in enumerate(units, start=1)]
        self._log(
            "EXPLODE",
            "```json\n" + json.dumps({"units": normalized, "raw_response": response}, ensure_ascii=False, indent=2) + "\n```",
            {
                "source_artifact": source_artifact,
                "units": normalized,
                "response": response,
            },
        )
        return normalized

    def _generate_unfold_candidates(
        self,
        state: WorkflowState,
        step: UnfoldStep,
        source: Candidate,
        unit_index: int,
        units: list[dict[str, Any]],
        selected_children: list[Candidate],
    ) -> list[Candidate]:
        total_units = len(units)
        unit = units[unit_index - 1]
        previous_unit = units[unit_index - 2] if unit_index > 1 else None
        next_unit = units[unit_index] if unit_index < total_units else None
        accepted_context = [_candidate_to_context_dict(candidate) for candidate in state.accepted_candidates]
        previous_text_so_far = "\n\n".join(_candidate_output(child) for child in selected_children if _candidate_output(child)).strip()
        expansion_context = {
            "source_artifact": step.source_artifact,
            "child_artifact": step.child_artifact,
            "unit_index": unit_index,
            "total_units": total_units,
            "source_candidate": _candidate_to_context_dict(source),
            "selected_source_plan": _candidate_to_context_dict(source),
            "previous_selected_children": [_candidate_to_context_dict(child) for child in selected_children],
            "previous_text_so_far": previous_text_so_far,
            "previous_unit": previous_unit,
            "current_unit": unit,
            "next_unit": next_unit,
            "all_units_outline": [
                {
                    "unit_id": item.get("unit_id", f"unit_{index}"),
                    "source_order": item.get("source_order", index),
                    "title": item.get("title", f"Unit {index}"),
                }
                for index, item in enumerate(units, start=1)
            ],
            "placement_instruction": _placement_instruction(unit_index, total_units),
            "continuation_instruction": _continuation_instruction(unit_index, total_units),
        }
        stage = _stage_from_artifact(step.child_artifact)
        candidates: list[Candidate] = []

        for index in range(1, step.candidates_count + 1):
            prompt = generate_candidate_prompt(
                step.child_artifact,
                state.task,
                state.dod,
                self._runtime_context(state),
                accepted_context,
                index,
                step.candidates_count,
                self._prompt_for_artifact(step.child_artifact),
                expansion_context,
            )
            response = self._chat_candidate_json(
                f"UNFOLD({step.child_artifact}) unit {unit_index}/{total_units} candidate {index}",
                step.child_artifact,
                [
                    {"role": "system", "content": self._candidate_system_prompt(step.child_artifact)},
                    {"role": "user", "content": prompt},
                ],
                model=self._model_for_artifact(step.child_artifact),
            )
            candidate = _candidate_from_json(response.get("candidate", response), stage, index, prompt, self.calls_used)
            candidate.metadata["artifact"] = step.child_artifact
            candidate.metadata["unfold"] = {
                "source_artifact": step.source_artifact,
                "unit_index": unit_index,
                "total_units": total_units,
                "unit_id": unit.get("unit_id", f"unit_{unit_index}"),
                "source_order": unit.get("source_order", unit_index),
                "previous_unit_id": previous_unit.get("unit_id") if previous_unit else None,
                "next_unit_id": next_unit.get("unit_id") if next_unit else None,
                "expansion_context": expansion_context,
            }
            candidates.append(candidate)
            self._log_candidate(stage, index, prompt, response, candidate)

        return candidates

    def _prompt_for_artifact(self, artifact: str) -> dict[str, Any]:
        value = self.artifact_prompts.get(artifact) or self.artifact_prompts.get(artifact.lower()) or {}

        if isinstance(value, str):
            return {"template": value, "seed": True}

        if isinstance(value, dict):
            return {
                "template": str(value.get("template", "")),
                "seed": bool(value.get("seed", True)),
                "model": str(value.get("model", "medium")),
            }

        return {"template": "", "seed": True, "model": "medium"}

    def _model_for_artifact(self, artifact: str) -> str:
        return model_for_tier(self._prompt_for_artifact(artifact).get("model", "medium"))

    def _candidate_system_prompt(self, artifact: str) -> str:
        parts = [
            "Follow the user prompt. For candidate generation, the final answer must be valid JSON matching the requested schema. Do not use markdown fences."
        ]

        if self._prompt_for_artifact(artifact).get("seed", True):
            parts.append(SSOT_DAG_SYSTEM_PROMPT)

        return "\n\n".join(parts)

    def _auto_select_random_if_needed(self, state: WorkflowState, reason: str) -> None:
        if not state.candidates or state.selected_candidate is not None:
            return

        seed = secrets.token_hex(16)
        selected_index = int(seed, 16) % len(state.candidates)
        selected = state.candidates[selected_index]
        selected.accepted = True
        selected.judge_reason = f"JUDGE omitted; randomly selected by runtime policy {reason}."
        selected.metadata["selection_policy"] = "random"
        selected.metadata["selection_seed"] = seed
        selected.metadata["selection_reason"] = reason
        state.selected_candidate = selected
        state.accepted_candidates.append(selected)
        self._apply_relative_candidate_to_raw_output(state, selected)

        self._log(
            "AUTO SELECT RANDOM",
            "```json\n"
            + json.dumps(
                {
                    "selected_index": selected_index,
                    "selected_candidate_id": selected.id,
                    "selection_policy": "random",
                    "selection_seed": seed,
                    "reason": reason,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n```",
            {
                "selected_index": selected_index,
                "selected_candidate_id": selected.id,
                "selection_policy": "random",
                "selection_seed": seed,
                "reason": reason,
            },
        )

    def _judge(self, state: WorkflowState, explicit: bool) -> None:
        if not state.candidates:
            raise RuntimeError("JUDGE requires candidates from GEN, GEN_BEFORE, GEN_AFTER or UNFOLD.")

        prompt = judge_prompt(
            state.task,
            state.dod,
            state.stage or "UNKNOWN",
            [_candidate_to_judge_dict(candidate) for candidate in state.candidates],
            self._runtime_context(state),
        )
        response = self._chat_json(
            "JUDGE",
            [
                {
                    "role": "system",
                    "content": 'Return JSON only with selected_index, score and reason. Example: {"selected_index":0,"score":87,"reason":"Candidate 0 best satisfies the Definition of Done."}',
                },
                {"role": "user", "content": prompt},
            ],
            model=model_for_tier("medium"),
        )
        selected_index = int(response.get("selected_index", 0))

        if selected_index < 0 or selected_index >= len(state.candidates):
            selected_index = 0

        score = _optional_float(response.get("score"))
        reason = str(response.get("reason", ""))
        selected = state.candidates[selected_index]
        selected.accepted = True
        selected.score = score
        selected.judge_reason = reason
        state.selected_candidate = selected
        state.accepted_candidates.append(selected)
        self._apply_relative_candidate_to_raw_output(state, selected)
        state.judge_decisions.append(
            JudgeDecision(
                stage=state.stage or selected.stage,
                selected_index=selected_index,
                reason=reason,
                score=score,
                raw_response=response,
            )
        )

        title = "JUDGE" if explicit else "AUTO JUDGE"
        self._log(
            title,
            "```json\n" + json.dumps(response, ensure_ascii=False, indent=2) + "\n```",
            {
                "selected_index": selected_index,
                "selected_candidate_id": selected.id,
                "score": score,
                "reason": reason,
                "response": response,
            },
        )

    def _apply_relative_candidate_to_raw_output(self, state: WorkflowState, candidate: Candidate) -> None:
        position = str(candidate.metadata.get("relative_position", "")).lower()

        if position not in {"before", "after"}:
            return

        addition = _candidate_output(candidate).strip()

        if not addition:
            return

        current = state.raw_output.strip()

        if position == "before":
            state.raw_output = addition if not current else addition + "\n\n" + current
        else:
            state.raw_output = addition if not current else current + "\n\n" + addition

        self._log(
            f"GEN_{position.upper()} applied",
            f"```markdown\n{state.raw_output}\n```",
            {
                "relative_position": position,
                "candidate": _candidate_to_context_dict(candidate),
                "raw_output": state.raw_output,
            },
        )

    def _output_glue(self, state: WorkflowState) -> None:
        if state.raw_output:
            self._log("OUTPUT_GLUE", f"```markdown\n{state.raw_output}\n```", {"raw_output": state.raw_output})
            return

        if state.selected_candidate is None:
            if state.candidates:
                self._auto_select_random_if_needed(state, "before OUTPUT_GLUE")
            else:
                self._direct_output_candidate(state)

        if state.selected_candidate is None:
            raise RuntimeError("OUTPUT_GLUE requires a selected candidate.")

        state.raw_output = raw_glue(state.task, state.dod, state.selected_candidate.payload)
        self._log("OUTPUT_GLUE", f"```markdown\n{state.raw_output}\n```", {"raw_output": state.raw_output})

    def _output_ai_glue(self, state: WorkflowState, step: OutputAiGlueStep) -> None:
        if not state.raw_output:
            self._output_glue(state)

        accepted = [_candidate_to_edit_dict(candidate, state.raw_output) for candidate in state.accepted_candidates]
        prompt = ai_glue_prompt(step.glue_mode, state.raw_output, self._runtime_context(state), accepted)
        state.ai_output = self._chat_text(
            "OUTPUT_AI_GLUE",
            [
                {"role": "system", "content": "Return final markdown only."},
                {"role": "user", "content": prompt},
            ],
            model=model_for_tier("medium"),
        )
        self._log("OUTPUT_AI_GLUE prompt", f"```text\n{prompt}\n```", {"prompt": prompt})
        self._log("OUTPUT_AI_GLUE result", f"```markdown\n{state.ai_output}\n```", {"ai_output": state.ai_output})

    def _edit(self, state: WorkflowState, step: EditStep) -> None:
        if not state.raw_output:
            self._output_glue(state)

        accepted = [_candidate_to_edit_dict(candidate, state.raw_output) for candidate in state.accepted_candidates]
        prompt = edit_prompt(step.mode, state.raw_output, self._runtime_context(state), accepted)
        state.ai_output = self._chat_text(
            "EDIT",
            [
                {"role": "system", "content": "Return final markdown only."},
                {"role": "user", "content": prompt},
            ],
            model=model_for_tier("medium"),
        )
        self._log("EDIT prompt", f"```text\n{prompt}\n```", {"prompt": prompt, "mode": step.mode})
        self._log("EDIT result", f"```markdown\n{state.ai_output}\n```", {"ai_output": state.ai_output})

    def _materialize(self, state: WorkflowState, step: MaterializeStep) -> None:
        state.stage = "MATERIALIZE"
        target_root = Path(step.target_dir).expanduser()
        if not target_root.is_absolute():
            target_root = Path.cwd() / target_root
        target_root = validate_materialize_target(target_root, self.security)

        files = _candidate_files_from_state(state)
        if not files:
            raise RuntimeError(
                "MATERIALIZE requires accepted candidates with payload.files or payload.path/content."
            )

        total_bytes = 0
        for file_spec in files:
            path = str(file_spec["path"])
            content = str(file_spec["content"])
            validate_materialize_relative_path(_safe_relative_file_path(path), self.security)
            total_bytes += len(content.encode("utf-8"))

        validate_materialize_limits(len(files), total_bytes, self.security)

        written: list[MaterializedFile] = []
        target_root.mkdir(parents=True, exist_ok=True)

        for file_spec in files:
            relative_path = _safe_relative_file_path(file_spec["path"])
            destination = (target_root / relative_path).resolve()

            if not _is_relative_to(destination, target_root):
                raise RuntimeError(f"MATERIALIZE refused path outside target dir: {file_spec['path']}")

            if destination.exists() and not self.security.allow_materialize_overwrite:
                raise RuntimeError(
                    f"MATERIALIZE refused to overwrite existing file: {destination.relative_to(target_root)}. "
                    "Use --allow-materialize-overwrite for trusted workflows."
                )

            content = str(file_spec["content"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            secure_write_text(destination, content)
            written.append(
                MaterializedFile(
                    path=str(destination.relative_to(target_root)),
                    bytes_written=len(content.encode("utf-8")),
                    source_candidate_id=str(file_spec["source_candidate_id"]),
                )
            )

        state.materialized_root = str(target_root)
        state.materialized_files = written
        self._log(
            "MATERIALIZE",
            "```json\n"
            + json.dumps(
                {
                    "target_dir": state.materialized_root,
                    "files": [file.to_dict() for file in written],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n```",
            {
                "target_dir": state.materialized_root,
                "files": [file.to_dict() for file in written],
            },
        )

    def _verify(self, state: WorkflowState, step: VerifyStep) -> None:
        state.stage = "VERIFY"
        if not self.security.allow_verify:
            raise RuntimeError("VERIFY is disabled by default. Use --allow-verify for trusted workflows.")

        cwd = Path(state.materialized_root) if state.materialized_root else Path.cwd()
        started = time.monotonic()
        completed = subprocess.run(
            step.command,
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        result = VerificationResult(
            command=step.command,
            cwd=str(cwd),
            exit_code=completed.returncode,
            stdout=_truncate_command_output(completed.stdout),
            stderr=_truncate_command_output(completed.stderr),
            duration_seconds=round(time.monotonic() - started, 3),
        )
        state.verification_results.append(result)
        self._log(
            "VERIFY",
            "```json\n" + json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n```",
            result.to_dict(),
        )

        if result.exit_code != 0:
            raise RuntimeError(
                f"VERIFY failed with exit code {result.exit_code}: {step.command}\n"
                f"cwd: {cwd}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )

    def _direct_output_candidate(self, state: WorkflowState) -> None:
        state.stage = "OUTPUT"
        prompt = direct_output_prompt(state.task, state.dod, self._runtime_context(state))
        response = self._chat_candidate_json(
            "DIRECT output candidate",
            "output",
            [
                {"role": "system", "content": self._candidate_system_prompt("output")},
                {"role": "user", "content": prompt},
            ],
        )
        candidate = _candidate_from_json(response.get("candidate", response), "OUTPUT", 1, prompt, self.calls_used)
        candidate.accepted = True
        state.candidates = [candidate]
        state.selected_candidate = candidate
        state.accepted_candidates.append(candidate)
        self._log_candidate("OUTPUT", 1, prompt, response, candidate)

    def _runtime_context(self, state: WorkflowState) -> list[dict[str, Any]]:
        return [context.to_dict() for context in state.contexts]

    def _status(self, message: str) -> None:
        if self.status_callback is not None:
            self.status_callback(message)

    def _chat_json(self, purpose: str, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        self._consume_call(purpose)
        return self.llm.chat_json(messages, model=model)

    def _chat_candidate_json(self, purpose: str, artifact: str, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        self._consume_call(purpose)

        if self._prompt_for_artifact(artifact).get("seed", True):
            return self.llm.chat_seeded_json(messages, model=model)

        return self.llm.chat_json(messages, model=model)

    def _chat_text(self, purpose: str, messages: list[dict[str, str]], model: str | None = None) -> str:
        self._consume_call(purpose)
        return self.llm.chat_text(messages, model=model)

    def _consume_call(self, purpose: str) -> None:
        if self.max_calls < 1:
            raise WorkflowBudgetExceeded("max_calls must be >= 1.")

        next_call = self.calls_used + 1

        if next_call > self.max_calls:
            raise WorkflowBudgetExceeded(f"LLM call budget exceeded: {next_call}/{self.max_calls} for {purpose}.")

        self.calls_used = next_call
        self._status(f"llm call {self.calls_used}/{self.max_calls}: {purpose}")

        if self.run_store is not None:
            self.run_store.event(
                "llm_call",
                purpose,
                {
                    "call": self.calls_used,
                    "max_calls": self.max_calls,
                },
            )

    def _log(self, title: str, body: str, payload: dict[str, Any]) -> None:
        self._status(f"done: {title}")
        self.logger.log(title, body)

        if self.run_store is not None:
            self.run_store.event("step", title, payload)

    def _log_candidate(self, stage: str, index: int, prompt: str, response: dict[str, Any], candidate: Candidate) -> None:
        self._log(
            f"{stage} candidate {index}",
            "Prompt:\n\n```text\n"
            + prompt
            + "\n```\n\nCandidate:\n\n```json\n"
            + json.dumps(response, ensure_ascii=False, indent=2)
            + "\n```",
            {
                "stage": stage,
                "index": index,
                "prompt": prompt,
                "response": response,
                "candidate": candidate.to_dict(),
            },
        )


def _candidate_from_json(data: dict[str, Any], stage: str, index: int, prompt: str, call_index: int) -> Candidate:
    candidate_data = _validate_candidate_json(data, stage, index)
    seed = candidate_data["seed"]
    payload = candidate_data["payload"]
    candidate_id = f"{_slug(stage)}_{index}"

    return Candidate(
        id=candidate_id,
        stage=stage,
        title=candidate_data["title"],
        summary=candidate_data["summary"],
        payload_type=candidate_data["payload_type"],
        payload=payload,
        seed_random_string=seed["random_string"],
        seed_interpretation=seed["interpretation"],
        prompt=prompt,
        content=_content_from_payload(payload),
        metadata={
            "candidate_index": index,
            "llm_call": call_index,
        },
    )


def _validate_candidate_json(data: Any, stage: str, index: int) -> dict[str, Any]:
    location = f"{stage} candidate {index}"

    if not isinstance(data, dict):
        raise CandidateValidationError(f"{location}: candidate must be a JSON object.")

    errors: list[str] = []
    seed = data.get("seed")
    payload = data.get("payload")
    title = data.get("title")
    summary = data.get("summary")
    payload_type = data.get("payload_type")

    if not isinstance(seed, dict):
        errors.append("candidate.seed must be an object")
    else:
        if not isinstance(seed.get("random_string"), str) or not seed.get("random_string", "").strip():
            errors.append("candidate.seed.random_string must be a non-empty string")
        if not isinstance(seed.get("interpretation"), str) or not seed.get("interpretation", "").strip():
            errors.append("candidate.seed.interpretation must be a non-empty string")

    if not isinstance(title, str) or not title.strip():
        errors.append("candidate.title must be a non-empty string")

    if not isinstance(summary, str):
        errors.append("candidate.summary must be a string")

    if not isinstance(payload_type, str) or not payload_type.strip():
        errors.append("candidate.payload_type must be a non-empty string")

    if not isinstance(payload, dict):
        errors.append("candidate.payload must be an object")

    if errors:
        raise CandidateValidationError(f"{location}: invalid candidate JSON: " + "; ".join(errors) + ".")

    return {
        "seed": {
            "random_string": seed["random_string"].strip(),
            "interpretation": seed["interpretation"].strip(),
        },
        "title": title.strip(),
        "summary": summary,
        "payload_type": payload_type.strip(),
        "payload": payload,
    }


def _stage_from_artifact(artifact: str) -> str:
    stage = "".join(ch if ch.isalnum() else "_" for ch in artifact.strip()).strip("_")
    return stage.upper() if stage else "GEN"


def _slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip()).strip("_")
    return slug or "candidate"


def _candidate_to_dict(candidate: Candidate | None) -> dict[str, Any]:
    if candidate is None:
        return {}

    return candidate.to_dict()


def _candidate_to_context_dict(candidate: Candidate | None) -> dict[str, Any]:
    if candidate is None:
        return {}

    return {
        "id": candidate.id,
        "stage": candidate.stage,
        "title": candidate.title,
        "summary": candidate.summary,
        "payload_type": candidate.payload_type,
        "payload": candidate.payload,
        "content": candidate.content,
    }


def _candidate_to_judge_dict(candidate: Candidate | None) -> dict[str, Any]:
    if candidate is None:
        return {}

    return {
        "id": candidate.id,
        "stage": candidate.stage,
        "title": candidate.title,
        "summary": candidate.summary,
        "payload_type": candidate.payload_type,
        "payload": candidate.payload,
        "content": candidate.content,
    }


def _candidate_to_edit_dict(candidate: Candidate | None, raw_output: str) -> dict[str, Any]:
    if candidate is None:
        return {}

    if _candidate_is_already_in_raw_output(candidate, raw_output):
        return {
            "id": candidate.id,
            "stage": candidate.stage,
            "title": candidate.title,
            "summary": candidate.summary,
            "payload_type": candidate.payload_type,
            "payload_already_in_raw_output": True,
        }

    return _candidate_to_context_dict(candidate)


def _candidate_is_already_in_raw_output(candidate: Candidate, raw_output: str) -> bool:
    if not raw_output:
        return False

    content = _candidate_output(candidate).strip()
    return bool(content and content in raw_output)


def _candidate_output(candidate: Candidate) -> str:
    markdown = candidate.payload.get("markdown")

    if markdown is not None:
        return str(markdown)

    if candidate.content:
        return candidate.content

    return json.dumps(candidate.payload, ensure_ascii=False, indent=2)


def _candidate_files_from_state(state: WorkflowState) -> list[dict[str, str]]:
    files_by_path: dict[str, dict[str, str]] = {}

    for candidate in state.accepted_candidates:
        for file_spec in _files_from_payload(candidate.payload):
            path = str(file_spec.get("path", "")).strip()
            content = file_spec.get("content")

            if not path or not isinstance(content, str):
                continue

            files_by_path[path] = {
                "path": path,
                "content": content,
                "source_candidate_id": candidate.id,
            }

    return list(files_by_path.values())


def _files_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    files = payload.get("files")
    if isinstance(files, list):
        return [file for file in files if isinstance(file, dict)]

    if isinstance(payload.get("path"), str) and isinstance(payload.get("content"), str):
        return [{"path": payload["path"], "content": payload["content"]}]

    file_value = payload.get("file")
    if isinstance(file_value, dict):
        return [file_value]

    structure = payload.get("structure")
    if isinstance(structure, dict):
        data = _json_value_from_maybe_string(structure.get("data"))
        if isinstance(data, dict):
            structured_files = data.get("files")
            if isinstance(structured_files, list):
                return [file for file in structured_files if isinstance(file, dict)]

    return []


def _safe_relative_file_path(value: str) -> Path:
    path = Path(value)

    if path.is_absolute():
        raise RuntimeError(f"MATERIALIZE refused absolute file path: {value}")

    if not value.strip() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError(f"MATERIALIZE refused unsafe file path: {value}")

    return path


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False

    return True


def _truncate_command_output(value: str, limit: int = 12000) -> str:
    if len(value) <= limit:
        return value

    return value[:limit] + f"\n...[truncated {len(value) - limit} chars]"


def _fallback_unit(source: Candidate) -> dict[str, Any]:
    return {
        "unit_id": "unit_1",
        "title": source.title or "Whole artifact",
        "source_order": 1,
        "content": _candidate_output(source),
        "constraints": [],
        "must_preserve": ["Preserve the source artifact as a single unit."],
    }


def _structured_units_from_candidate(source: Candidate) -> list[dict[str, Any]]:
    sections = _structured_sections_from_payload(source.payload)

    if not sections:
        return []

    units: list[dict[str, Any]] = []

    for index, section in enumerate(sections, start=1):
        if not isinstance(section, dict):
            section = _file_section_from_string(section, index)

        if not isinstance(section, dict):
            continue

        title = str(section.get("title") or section.get("name") or section.get("path") or f"Unit {index}").strip()
        purpose = str(section.get("purpose") or "").strip()
        key_points = section.get("key_points") if isinstance(section.get("key_points"), list) else []
        constraints = section.get("constraints") if isinstance(section.get("constraints"), list) else []
        must_preserve = section.get("must_preserve") if isinstance(section.get("must_preserve"), list) else []
        content = _structured_section_content(title, purpose, key_points, section)

        units.append(
            {
                "unit_id": str(section.get("unit_id") or f"unit_{index}"),
                "title": title,
                "path": str(section.get("path") or ""),
                "source_order": int(section.get("source_order") or index),
                "content": content,
                "constraints": [str(item) for item in constraints],
                "must_preserve": [str(item) for item in must_preserve] or _section_must_preserve(title, purpose, key_points),
            }
        )

    return units


def _structured_sections_from_payload(payload: dict[str, Any]) -> list[Any]:
    structure = payload.get("structure")

    if isinstance(structure, dict):
        data = _json_value_from_maybe_string(structure.get("data"))

        if isinstance(data, dict):
            sections = data.get("sections")
            if isinstance(sections, list):
                return sections

            files = data.get("files")
            if isinstance(files, list):
                return files

        if isinstance(data, list):
            return data

        sections = structure.get("sections")
        if isinstance(sections, list):
            return sections

        files = structure.get("files")
        if isinstance(files, list):
            return files

    items = payload.get("items")
    if isinstance(items, list):
        return items

    files = payload.get("files")
    if isinstance(files, list):
        return files

    return []


def _file_section_from_string(value: Any, index: int) -> dict[str, Any] | None:
    path = str(value).strip()

    if not path or "/" not in path and "." not in path:
        return None

    return {
        "unit_id": f"file_{index}",
        "title": path,
        "path": path,
        "source_order": index,
        "purpose": f"Implement {path}",
        "must_preserve": [f"Write exactly this file path: {path}"],
    }


def _is_file_manifest_artifact(artifact: str) -> bool:
    return artifact.strip().lower().replace("-", "_").replace(" ", "_") in {
        "file_manifest",
        "files_manifest",
        "project_manifest",
    }


def _json_value_from_maybe_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    stripped = value.strip()
    if not stripped or stripped[0] not in "{[":
        return value

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _structured_section_content(title: str, purpose: str, key_points: list[Any], section: dict[str, Any]) -> str:
    lines = [f"Title: {title}"]

    path = str(section.get("path") or "").strip()
    if path:
        lines.append(f"Path: {path}")

    if purpose:
        lines.append(f"Purpose: {purpose}")

    if key_points:
        lines.append("Key points:")
        lines.extend(f"- {point}" for point in key_points)

    dependencies = section.get("dependencies")
    if isinstance(dependencies, list) and dependencies:
        lines.append("Dependencies:")
        lines.extend(f"- {item}" for item in dependencies)

    imports = section.get("imports")
    if isinstance(imports, list) and imports:
        lines.append("Imports:")
        lines.extend(f"- {item}" for item in imports)

    exports = section.get("exports")
    if isinstance(exports, list) and exports:
        lines.append("Exports:")
        lines.extend(f"- {item}" for item in exports)

    return "\n".join(str(line) for line in lines).strip()


def _section_must_preserve(title: str, purpose: str, key_points: list[Any]) -> list[str]:
    preserve = [f"Preserve section intent: {title}"]

    if purpose:
        preserve.append(f"Preserve purpose: {purpose}")

    preserve.extend(f"Preserve key point: {point}" for point in key_points)
    return preserve


def _normalize_unit(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "unit_id": f"unit_{index}",
            "title": f"Unit {index}",
            "source_order": index,
            "content": str(value),
            "constraints": [],
            "must_preserve": [],
        }

    return {
        "unit_id": str(value.get("unit_id") or f"unit_{index}"),
        "title": str(value.get("title") or value.get("path") or f"Unit {index}"),
        "path": str(value.get("path") or ""),
        "source_order": int(value.get("source_order") or index),
        "content": str(value.get("content") or ""),
        "constraints": value.get("constraints") if isinstance(value.get("constraints"), list) else [],
        "must_preserve": value.get("must_preserve") if isinstance(value.get("must_preserve"), list) else [],
    }


def _placement_instruction(unit_index: int, total_units: int) -> str:
    if total_units <= 1:
        return "Write this as the only child artifact. It must cover the whole source unit without pretending there are neighboring units."

    if unit_index == 1:
        return "Write this as the opening child artifact. Start strongly, set up the next unit, and do not pre-answer later units."

    if unit_index == total_units:
        return "Write this as the final child artifact. Build on previous units, avoid repeating them, and prepare a satisfying close."

    return "Write this as a middle child artifact. Bridge from previous_unit to next_unit, avoid repetition, and do not jump ahead."


def _continuation_instruction(unit_index: int, total_units: int) -> str:
    if unit_index <= 1:
        return (
            "This is the opening part of one continuous text. Start the article/post, establish the voice, "
            "and prepare the next unit without writing it yet."
        )

    if unit_index == total_units:
        return (
            "This is the final continuation of one continuous text. Read previous_text_so_far, continue from it naturally, "
            "avoid restating earlier arguments, and close the whole piece."
        )

    return (
        "This is a continuation of one continuous text. Read previous_text_so_far first, then write the next part as a natural continuation. "
        "Do not restart the article, do not summarize previous parts, and do not use a standalone section intro."
    )


def _relative_document_instruction(position: str) -> str:
    if position == "before":
        return (
            "Generate text that goes before current_document. It must open or frame the document naturally, "
            "lead into the existing first paragraph, and avoid summarizing the full document."
        )

    return (
        "Generate text that goes after current_document. It must continue from the existing last paragraph, "
        "close the document naturally, and avoid repeating previous arguments."
    )


def _relative_document_scope(artifact: str, position: str, document: str) -> str:
    key = artifact.strip().lower().replace("-", "_").replace(" ", "_")

    if not document:
        return ""

    if key in {"title", "headline", "hook_title"}:
        return document[:2500]

    if position == "before" or key in {"opening", "hook", "intro"}:
        return document[:4500]

    if position == "after" or key in {"ending", "cta", "final", "conclusion"}:
        return document[-4500:]

    return document[-6000:]


def _relative_document_scope_label(artifact: str, position: str) -> str:
    key = artifact.strip().lower().replace("-", "_").replace(" ", "_")

    if key in {"title", "headline", "hook_title"}:
        return "document_start_2500_chars"

    if position == "before" or key in {"opening", "hook", "intro"}:
        return "document_start_4500_chars"

    if position == "after" or key in {"ending", "cta", "final", "conclusion"}:
        return "document_end_4500_chars"

    return "document_end_6000_chars"


def _content_from_payload(payload: dict[str, Any]) -> str:
    if "markdown" in payload:
        return str(payload["markdown"])

    return json.dumps(payload, ensure_ascii=False, indent=2)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _state_to_dict(state: WorkflowState) -> dict[str, Any]:
    return {
        "task": state.task,
        "dod": state.dod,
        "stage": state.stage,
        "contexts": [context.to_dict() for context in state.contexts],
        "call_count": state.call_count,
        "candidates": [_candidate_to_dict(candidate) for candidate in state.candidates],
        "accepted_candidates": [_candidate_to_dict(candidate) for candidate in state.accepted_candidates],
        "judge_decisions": [
            {
                "stage": decision.stage,
                "selected_index": decision.selected_index,
                "reason": decision.reason,
                "score": decision.score,
                "raw_response": decision.raw_response,
            }
            for decision in state.judge_decisions
        ],
        "raw_output": state.raw_output,
        "ai_output": state.ai_output,
        "materialized_root": state.materialized_root,
        "materialized_files": [file.to_dict() for file in state.materialized_files],
        "verification_results": [result.to_dict() for result in state.verification_results],
    }
