from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typing import Any

from rick_cli.engine import CandidateValidationError, WorkflowBudgetExceeded, WorkflowEngine
from rick_cli.llm import LLMClient, MockLLMClient
from rick_cli.logger import JsonRunStore, MarkdownStepLogger
from rick_cli.parser import parse_program
from rick_cli.security import SecurityOptions


class StaticJsonLLMClient(LLMClient):
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response

    def chat_seeded_json(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        return self.response

    def chat_json(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        return self.response

    def chat_text(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        return ""


class RoutingLLMClient(LLMClient):
    def __init__(self) -> None:
        self.seeded_calls = 0
        self.json_calls = 0

    def chat_seeded_json(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        self.seeded_calls += 1
        return _candidate_response("article", "# Seeded")

    def chat_json(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        self.json_calls += 1
        return _candidate_response("article", "# Plain")

    def chat_text(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        return ""


class StructuredUnfoldLLMClient(LLMClient):
    def __init__(self) -> None:
        self.explode_calls = 0
        self.judge_calls = 0
        self.seeded_calls = 0

    def chat_seeded_json(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        self.seeded_calls += 1
        prompt = messages[-1]["content"]

        if "Artifact to generate: plan" in prompt:
            return {
                "candidate": {
                    "seed": {"random_string": "<random_string>plan</random_string>", "interpretation": "seed note"},
                    "title": "Structured plan",
                    "summary": "",
                    "payload_type": "plan",
                    "payload": {
                        "artifact": "plan",
                        "structure": {
                            "type": "plan",
                            "data": {
                                "sections": [
                                    {
                                        "title": "Opening",
                                        "purpose": "Open the post",
                                        "key_points": ["State the topic"],
                                    },
                                    {
                                        "title": "Limits",
                                        "purpose": "Explain constraints",
                                        "key_points": ["Mention rate limits"],
                                    },
                                ]
                            },
                        },
                    },
                }
            }

        return _candidate_response("section_draft", f"Section {self.seeded_calls}")

    def chat_json(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        if "units" in messages[0]["content"]:
            self.explode_calls += 1
            raise AssertionError("EXPLODE should use structured payload without an LLM call")

        self.judge_calls += 1
        return {"selected_index": 0, "score": 90, "reason": "ok"}

    def chat_text(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        return ""


class StringManifestUnfoldLLMClient(LLMClient):
    def __init__(self) -> None:
        self.explode_calls = 0
        self.seeded_calls = 0

    def chat_seeded_json(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        self.seeded_calls += 1
        prompt = messages[-1]["content"]

        if "Artifact to generate: file_manifest" in prompt:
            return {
                "candidate": {
                    "seed": {"random_string": "<random_string>manifest</random_string>", "interpretation": "seed note"},
                    "title": "Manifest",
                    "summary": "",
                    "payload_type": "file_manifest",
                    "payload": {
                        "artifact": "file_manifest",
                        "structure": {
                            "type": "file_manifest",
                            "data": json.dumps(
                                {
                                    "files": [
                                        {"path": "index.html", "purpose": "entry"},
                                        {"path": "src/main.js", "purpose": "boot"},
                                    ]
                                }
                            ),
                        },
                    },
                }
            }

        path = ["index.html", "src/main.js"][min(self.seeded_calls - 2, 1)]
        return {
            "candidate": {
                "seed": {"random_string": "<random_string>file</random_string>", "interpretation": "seed note"},
                "title": path,
                "summary": "",
                "payload_type": "file_implementation",
                "payload": {"files": [{"path": path, "content": f"// {path}\n"}]},
            }
        }

    def chat_json(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        if "units" in messages[0]["content"]:
            self.explode_calls += 1
            raise AssertionError("EXPLODE should parse structure.data JSON strings without an LLM call")

        return {"selected_index": 0, "score": 90, "reason": "ok"}

    def chat_text(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        return ""


class StructureFilesStringManifestLLMClient(StringManifestUnfoldLLMClient):
    def chat_seeded_json(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, Any]:
        self.seeded_calls += 1
        prompt = messages[-1]["content"]

        if "Artifact to generate: file_manifest" in prompt:
            return {
                "candidate": {
                    "seed": {"random_string": "<random_string>manifest</random_string>", "interpretation": "seed note"},
                    "title": "Manifest",
                    "summary": "",
                    "payload_type": "file_manifest",
                    "payload": {
                        "artifact": "file_manifest",
                        "structure": {
                            "type": "file_manifest",
                            "data": "manifest text",
                            "files": ["index.html", "src/main.js"],
                        },
                    },
                }
            }

        path = ["index.html", "src/main.js"][min(self.seeded_calls - 2, 1)]
        return {
            "candidate": {
                "seed": {"random_string": "<random_string>file</random_string>", "interpretation": "seed note"},
                "title": path,
                "summary": "",
                "payload_type": "file_implementation",
                "payload": {"files": [{"path": path, "content": f"// {path}\n"}]},
            }
        }


def _candidate_response(payload_type: str, markdown: str) -> dict[str, Any]:
    return {
        "candidate": {
            "seed": {"random_string": "<random_string>x</random_string>", "interpretation": "seed note"},
            "title": "Candidate",
            "summary": "",
            "payload_type": payload_type,
            "payload": {"markdown": markdown},
        }
    }


class EngineTests(unittest.TestCase):
    def make_engine(
        self,
        tmp_path: Path,
        *,
        max_calls: int = 60,
        context_max_chars: int = 8000,
        log: bool = False,
        run_store: bool = False,
        security: SecurityOptions | None = None,
    ) -> WorkflowEngine:
        log_path = tmp_path / "log.md" if log else None
        store = JsonRunStore(tmp_path / "run.json", workflow_source="test") if run_store else None
        return WorkflowEngine(
            MockLLMClient(),
            MarkdownStepLogger(log_path),
            run_store=store,
            max_calls=max_calls,
            context_max_chars=context_max_chars,
            security=security,
        )

    def test_resolve_generate_judge_output_glue_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            engine = self.make_engine(tmp_path, log=True, run_store=True)
            program = parse_program('RESOLVE("Task","DoD")>GEN(plan,2)>JUDGE>OUTPUT_GLUE')

            state = engine.run(program)

            self.assertEqual(state.task, "Task")
            self.assertEqual(state.dod, "DoD")
            self.assertEqual(state.call_count, 3)
            self.assertEqual(len(state.accepted_candidates), 1)
            self.assertEqual(len(state.judge_decisions), 1)
            self.assertIn("# Task", state.raw_output)
            self.assertIn("## 1. Hook", state.raw_output)

            log_text = (tmp_path / "log.md").read_text(encoding="utf-8")
            self.assertIn("## RESOLVE", log_text)
            self.assertIn("## JUDGE", log_text)
            self.assertIn("## OUTPUT_GLUE", log_text)

            run_data = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
            self.assertIsNotNone(run_data["finished_at"])
            self.assertEqual(run_data["final_state"]["call_count"], 3)
            self.assertTrue(run_data["events"])

    def test_context_step_loads_and_truncates_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            context_path = tmp_path / "context.md"
            context_path.write_text("abcdef", encoding="utf-8")
            engine = self.make_engine(
                tmp_path,
                context_max_chars=3,
                security=SecurityOptions(allow_context_outside_cwd=True),
            )
            program = parse_program(f'RESOLVE("Task","DoD")>CONTEXT("{context_path}")>OUTPUT_GLUE')

            state = engine.run(program)

            self.assertEqual(len(state.contexts), 1)
            self.assertEqual(state.contexts[0].content, "abc")
            self.assertEqual(state.contexts[0].original_chars, 6)
            self.assertEqual(state.contexts[0].included_chars, 3)
            self.assertTrue(state.contexts[0].truncated)
            self.assertIn("# Mock output", state.raw_output)

    def test_budget_guard_stops_before_extra_llm_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            engine = self.make_engine(tmp_path, max_calls=2)
            program = parse_program('RESOLVE("Task","DoD")>GEN(plan,2)>JUDGE')

            with self.assertRaisesRegex(WorkflowBudgetExceeded, "3/2 for JUDGE"):
                engine.run(program)

    def test_omitted_judge_uses_runtime_random_selection_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            engine = self.make_engine(tmp_path, security=SecurityOptions(allow_context_outside_cwd=True))
            program = parse_program('RESOLVE("Task","DoD")>GEN(plan,2)>GEN(draft,1)>OUTPUT_GLUE')

            with patch("rick_cli.engine.secrets.token_hex", return_value="0" * 31 + "1"):
                state = engine.run(program)

            self.assertGreaterEqual(len(state.accepted_candidates), 2)
            first_selected = state.accepted_candidates[0]
            self.assertEqual(first_selected.metadata["selection_policy"], "random")
            self.assertEqual(first_selected.metadata["selection_reason"], "before GEN(draft)")
            self.assertIn("randomly selected", first_selected.judge_reason or "")

    def test_edit_runs_after_raw_glue_and_sets_ai_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            engine = self.make_engine(tmp_path, security=SecurityOptions(allow_context_outside_cwd=True))
            program = parse_program('RESOLVE("Task","DoD")>GEN(draft,1)>JUDGE>EDIT(strict)')

            state = engine.run(program)

            self.assertEqual(state.call_count, 3)
            self.assertIn("# Mock draft", state.raw_output)
            self.assertEqual(state.ai_output, state.raw_output)

    def test_invalid_candidate_json_fails_with_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory():
            engine = WorkflowEngine(
                StaticJsonLLMClient(
                    {
                        "candidate": {
                            "seed": {"random_string": "", "interpretation": "seed note"},
                            "title": "Broken",
                            "summary": "Missing payload type and payload",
                        }
                    }
                ),
                MarkdownStepLogger(None),
            )
            program = parse_program('RESOLVE("Task","DoD")>GEN(article,1)>OUTPUT_GLUE')

            with self.assertRaisesRegex(
                CandidateValidationError,
                "ARTICLE candidate 1: invalid candidate JSON: .*seed.random_string.*payload_type.*payload",
            ):
                engine.run(program)

    def test_candidate_json_may_be_returned_without_top_level_candidate_wrapper(self) -> None:
        with tempfile.TemporaryDirectory():
            engine = WorkflowEngine(
                StaticJsonLLMClient(
                    {
                        "seed": {"random_string": "<random_string>x</random_string>", "interpretation": "seed note"},
                        "title": "Direct candidate",
                        "summary": "",
                        "payload_type": "article",
                        "payload": {"markdown": "# Direct"},
                    }
                ),
                MarkdownStepLogger(None),
            )
            program = parse_program('RESOLVE("Task","DoD")>GEN(article,1)>OUTPUT_GLUE')

            state = engine.run(program)

            self.assertEqual(state.raw_output, "# Direct")

    def test_seed_enabled_generation_uses_seeded_json_transport(self) -> None:
        with tempfile.TemporaryDirectory():
            llm = RoutingLLMClient()
            engine = WorkflowEngine(llm, MarkdownStepLogger(None))
            program = parse_program('RESOLVE("Task","DoD")>GEN(article,1)>OUTPUT_GLUE')

            state = engine.run(program)

            self.assertEqual(llm.seeded_calls, 1)
            self.assertEqual(llm.json_calls, 0)
            self.assertEqual(state.raw_output, "# Seeded")

    def test_seed_disabled_prompt_alias_uses_strict_json_transport(self) -> None:
        with tempfile.TemporaryDirectory():
            llm = RoutingLLMClient()
            engine = WorkflowEngine(
                llm,
                MarkdownStepLogger(None),
                artifact_prompts={"article": {"template": "Write article", "seed": False}},
            )
            program = parse_program('RESOLVE("Task","DoD")>GEN(article,1)>OUTPUT_GLUE')

            state = engine.run(program)

            self.assertEqual(llm.seeded_calls, 0)
            self.assertEqual(llm.json_calls, 1)
            self.assertEqual(state.raw_output, "# Plain")

    def test_unfold_uses_structured_plan_sections_without_explode_llm_call(self) -> None:
        with tempfile.TemporaryDirectory():
            llm = StructuredUnfoldLLMClient()
            engine = WorkflowEngine(llm, MarkdownStepLogger(None))
            program = parse_program('RESOLVE("Task","DoD")>GEN(plan,1)>JUDGE>UNFOLD(plan,section_draft,1)>OUTPUT_GLUE')

            state = engine.run(program)

            self.assertEqual(llm.explode_calls, 0)
            self.assertEqual(llm.judge_calls, 1)
            self.assertEqual(llm.seeded_calls, 3)
            self.assertEqual(len(state.accepted_candidates), 3)
            self.assertEqual(state.raw_output, "Section 2\n\nSection 3")

    def test_unfold_parses_file_manifest_structure_data_json_string(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            llm = StringManifestUnfoldLLMClient()
            engine = WorkflowEngine(
                llm,
                MarkdownStepLogger(None),
                security=SecurityOptions(allow_materialize_outside_runs=True),
            )
            program = parse_program(
                f'RESOLVE("Task","DoD")>GEN(file_manifest,1)>UNFOLD(file_manifest,file_implementation,1)>MATERIALIZE("{tmp_path}")'
            )

            state = engine.run(program)

            self.assertEqual(llm.explode_calls, 0)
            self.assertTrue((tmp_path / "index.html").exists())
            self.assertTrue((tmp_path / "src/main.js").exists())
            self.assertEqual([file.path for file in state.materialized_files], ["index.html", "src/main.js"])

    def test_unfold_parses_file_manifest_structure_files_string_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            llm = StructureFilesStringManifestLLMClient()
            engine = WorkflowEngine(
                llm,
                MarkdownStepLogger(None),
                security=SecurityOptions(allow_materialize_outside_runs=True),
            )
            program = parse_program(
                f'RESOLVE("Task","DoD")>GEN(file_manifest,1)>UNFOLD(file_manifest,file_implementation,1)>MATERIALIZE("{tmp_path}")'
            )

            state = engine.run(program)

            self.assertEqual(llm.explode_calls, 0)
            self.assertEqual([file.path for file in state.materialized_files], ["index.html", "src/main.js"])

    def test_materialize_writes_payload_files_and_verify_runs_in_target_dir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            target = tmp_path / "generated"
            engine = WorkflowEngine(
                StaticJsonLLMClient(
                    {
                        "candidate": {
                            "seed": {"random_string": "<random_string>x</random_string>", "interpretation": "seed note"},
                            "title": "File",
                            "summary": "",
                            "payload_type": "file_implementation",
                            "payload": {
                                "files": [
                                    {
                                        "path": "src/main.js",
                                        "content": "const answer = 42;\nconsole.log(answer);\n",
                                    }
                                ]
                            },
                        }
                    }
                ),
                MarkdownStepLogger(None),
                security=SecurityOptions(allow_materialize_outside_runs=True, allow_verify=True),
            )
            program = parse_program(
                f'RESOLVE("Task","DoD")>GEN(file_implementation,1)>MATERIALIZE("{target}")>VERIFY("test -f src/main.js")'
            )

            state = engine.run(program)

            self.assertEqual((target / "src/main.js").read_text(encoding="utf-8"), "const answer = 42;\nconsole.log(answer);\n")
            self.assertEqual(state.materialized_root, str(target.resolve()))
            self.assertEqual(state.materialized_files[0].path, "src/main.js")
            self.assertEqual(state.verification_results[0].exit_code, 0)
            self.assertEqual(state.verification_results[0].cwd, str(target.resolve()))

    def test_materialize_rejects_unsafe_file_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            engine = WorkflowEngine(
                StaticJsonLLMClient(
                    {
                        "candidate": {
                            "seed": {"random_string": "<random_string>x</random_string>", "interpretation": "seed note"},
                            "title": "File",
                            "summary": "",
                            "payload_type": "file_implementation",
                            "payload": {"files": [{"path": "../escape.js", "content": "bad"}]},
                        }
                    }
                ),
                MarkdownStepLogger(None),
                security=SecurityOptions(allow_materialize_outside_runs=True),
            )
            program = parse_program(
                f'RESOLVE("Task","DoD")>GEN(file_implementation,1)>MATERIALIZE("{tmp_path / "generated"}")'
            )

            with self.assertRaisesRegex(RuntimeError, "unsafe file path"):
                engine.run(program)

    def test_verify_failure_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            engine = self.make_engine(tmp_path, security=SecurityOptions(allow_verify=True))
            program = parse_program('RESOLVE("Task","DoD")>VERIFY("exit 7")')

            with self.assertRaisesRegex(RuntimeError, "VERIFY failed with exit code 7"):
                engine.run(program)

    def test_context_refuses_sensitive_paths_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            secret = tmp_path / ".env"
            secret.write_text("OPENROUTER_API_KEY=secret", encoding="utf-8")
            engine = self.make_engine(tmp_path, security=SecurityOptions(allow_context_outside_cwd=True))
            program = parse_program(f'RESOLVE("Task","DoD")>CONTEXT("{secret}")>OUTPUT_GLUE')

            with self.assertRaisesRegex(RuntimeError, "sensitive path"):
                engine.run(program)

    def test_context_logs_metadata_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            context_path = tmp_path / "context.md"
            context_path.write_text("private context", encoding="utf-8")
            engine = self.make_engine(
                tmp_path,
                run_store=True,
                security=SecurityOptions(allow_context_outside_cwd=True),
            )
            program = parse_program(f'RESOLVE("Task","DoD")>CONTEXT("{context_path}")>OUTPUT_GLUE')

            engine.run(program)

            run_data = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
            payload = next(event["payload"] for event in run_data["events"] if event["title"] == "CONTEXT")
            self.assertNotIn("content", payload)
            self.assertTrue(payload["content_redacted"])

    def test_materialize_requires_runs_target_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            engine = WorkflowEngine(
                StaticJsonLLMClient(
                    {
                        "candidate": {
                            "seed": {"random_string": "<random_string>x</random_string>", "interpretation": "seed note"},
                            "title": "File",
                            "summary": "",
                            "payload_type": "file_implementation",
                            "payload": {"path": "src/main.js", "content": "console.log(1);\n"},
                        }
                    }
                ),
                MarkdownStepLogger(None),
            )
            program = parse_program(
                f'RESOLVE("Task","DoD")>GEN(file_implementation,1)>MATERIALIZE("{tmp_path / "generated"}")'
            )

            with self.assertRaisesRegex(RuntimeError, "under runs"):
                engine.run(program)

    def test_materialize_refuses_dotfiles_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            target = Path.cwd() / "runs" / f"security-test-{Path(directory).name}"
            engine = WorkflowEngine(
                StaticJsonLLMClient(
                    {
                        "candidate": {
                            "seed": {"random_string": "<random_string>x</random_string>", "interpretation": "seed note"},
                            "title": "File",
                            "summary": "",
                            "payload_type": "file_implementation",
                            "payload": {"path": ".env", "content": "secret"},
                        }
                    }
                ),
                MarkdownStepLogger(None),
            )
            program = parse_program(f'RESOLVE("Task","DoD")>GEN(file_implementation,1)>MATERIALIZE("{target}")')

            with self.assertRaisesRegex(RuntimeError, "sensitive or hidden"):
                engine.run(program)

    def test_verify_is_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            engine = self.make_engine(tmp_path)
            program = parse_program('RESOLVE("Task","DoD")>VERIFY("true")')

            with self.assertRaisesRegex(RuntimeError, "VERIFY is disabled"):
                engine.run(program)


if __name__ == "__main__":
    unittest.main()
