from __future__ import annotations

import unittest

from seedflow_cli.llm import _dod_schema
from seedflow_cli.prompts import ai_glue_prompt, define_dod_prompt, generate_candidate_prompt, judge_prompt


class PromptTests(unittest.TestCase):
    def test_define_dod_prompt_tracks_output_language(self) -> None:
        prompt = define_dod_prompt("Write a short story in Spanish", "auto", [])
        schema = _dod_schema()

        self.assertIn("output_language", prompt)
        self.assertIn("Infer the final output language", prompt)
        self.assertIn("output_language", schema["properties"]["dod"]["required"])

    def test_generation_judge_and_glue_preserve_language_contract(self) -> None:
        generation = generate_candidate_prompt("story", "Write a short story in Spanish", "{}", [], [], 1, 1)
        judge = judge_prompt("Write a short story in Spanish", "{}", "STORY", [], [])
        glue = ai_glue_prompt("story", "raw source text", [], [])

        self.assertIn("Language contract", generation)
        self.assertIn("task's primary language", generation)
        self.assertIn("language fit", judge)
        self.assertIn("output language", glue)

    def test_non_plan_generation_uses_deliverable_contract(self) -> None:
        prompt = generate_candidate_prompt("section_draft", "Write artifact", "{}", [], [], 1, 1)

        self.assertIn("generate the artifact itself", prompt)
        self.assertIn("not commentary about the artifact", prompt)
        self.assertIn("directly usable by downstream glue", prompt)
        self.assertIn("Avoid scaffold language", prompt)

    def test_unfold_generation_uses_child_artifact_contract(self) -> None:
        prompt = generate_candidate_prompt(
            "section_draft",
            "Write artifact",
            "{}",
            [],
            [],
            1,
            1,
            expansion_context={
                "current_unit": {"title": "Unit", "content": "Purpose: explain"},
                "previous_text_so_far": "Already written",
            },
        )

        self.assertIn("UNFOLD child artifact contract", prompt)
        self.assertIn("actual finished child artifact", prompt)
        self.assertIn("Do not summarize current_unit", prompt)
        self.assertIn("directly usable in the final assembled artifact", prompt)

    def test_plan_generation_keeps_planning_contract(self) -> None:
        prompt = generate_candidate_prompt("plan", "Write artifact", "{}", [], [], 1, 1)

        self.assertIn("this artifact is planning material", prompt)
        self.assertNotIn("generate the artifact itself, not commentary", prompt)

    def test_glue_prompt_is_final_assembly_not_summary(self) -> None:
        prompt = ai_glue_prompt("strict", "raw", [], [])

        self.assertIn("final assembly pass", prompt)
        self.assertIn("Do not summarize selected candidates", prompt)
        self.assertIn("Preserve the intended deliverable type", prompt)
        self.assertIn("Remove scaffold language", prompt)

    def test_assemble_mode_preserves_length_without_summary(self) -> None:
        prompt = ai_glue_prompt("assemble", "x" * 1000, [], [])

        self.assertIn("Mode-specific rules for assemble", prompt)
        self.assertIn("Preserve nearly all non-duplicate source content", prompt)
        self.assertIn("Do not shorten for concision", prompt)
        self.assertIn("90-115% of raw glued output length (1000 characters)", prompt)
        self.assertIn("do not return the raw glued output unchanged", prompt)
        self.assertIn("Normalize transitions", prompt)
        self.assertIn("minimal necessary assembly edits", prompt)
        self.assertIn("Remove only exact or near-exact duplicate passages", prompt)

    def test_file_manifest_and_implementation_prompts_use_materialize_contracts(self) -> None:
        manifest = generate_candidate_prompt("file_manifest", "Build app", "{}", [], [], 1, 1)
        implementation = generate_candidate_prompt(
            "file_implementation",
            "Build app",
            "{}",
            [],
            [],
            1,
            1,
            expansion_context={"current_unit": {"path": "src/main.js"}},
        )

        self.assertIn("machine-readable file manifest", manifest)
        self.assertIn("candidate.payload.structure.data.files", manifest)
        self.assertIn("Do not write file contents", manifest)
        self.assertIn("complete writable file artifact", implementation)
        self.assertIn("candidate.payload.files", implementation)
        self.assertIn("MATERIALIZE and VERIFY", implementation)


if __name__ == "__main__":
    unittest.main()
