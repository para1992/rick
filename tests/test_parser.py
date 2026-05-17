from __future__ import annotations

import unittest

from rick_cli.models import (
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
)
from rick_cli.parser import ParseError, parse_program


class ParserTests(unittest.TestCase):
    def test_splits_steps_only_outside_quoted_strings(self) -> None:
        program = parse_program(
            'RESOLVE("A > B and \\"quoted > text\\"","DoD > ok")'
            '>CONTEXT("docs/spec > v2.md")'
            '>GEN_AFTER("section > tail",2)'
            '>EDIT("strict > mode")'
        )

        self.assertIsInstance(program.steps[0], ResolveStep)
        self.assertEqual(program.steps[0].task, 'A > B and "quoted > text"')
        self.assertEqual(program.steps[0].dod, "DoD > ok")

        self.assertIsInstance(program.steps[1], ContextStep)
        self.assertEqual(program.steps[1].file_path, "docs/spec > v2.md")

        self.assertIsInstance(program.steps[2], GenerateRelativeStep)
        self.assertEqual(program.steps[2].artifact, "section > tail")
        self.assertEqual(program.steps[2].position, "after")
        self.assertEqual(program.steps[2].candidates_count, 2)

        self.assertIsInstance(program.steps[3], EditStep)
        self.assertEqual(program.steps[3].mode, "strict > mode")

    def test_auto_dod_hint_inserts_define_dod_step(self) -> None:
        program = parse_program('RESOLVE("Task","auto")>GEN(plan,1)')

        self.assertIsInstance(program.steps[0], ResolveStep)
        self.assertIsInstance(program.steps[1], DefineDodStep)
        self.assertIsInstance(program.steps[2], GenerateStep)
        self.assertIsInstance(program.steps[-1], OutputGlueStep)

    def test_generate_steps_parse(self) -> None:
        program = parse_program('RESOLVE("Task","DoD")>GEN(angle,1)>JUDGE>GEN(plan,2)>GEN(draft,3)')
        generate_steps = [step for step in program.steps if isinstance(step, GenerateStep)]

        self.assertEqual([step.artifact for step in generate_steps], ["angle", "plan", "draft"])
        self.assertEqual([step.candidates_count for step in generate_steps], [1, 2, 3])
        self.assertTrue(any(isinstance(step, JudgeStep) for step in program.steps))
        self.assertIsInstance(program.steps[-1], OutputGlueStep)

    def test_custom_relative_unfold_and_ai_glue_steps_parse(self) -> None:
        program = parse_program(
            'RESOLVE("Task","DoD")'
            '>GEN(outline,1)>JUDGE'
            '>UNFOLD_JUDGE(outline,section_draft,2)'
            '>GEN_BEFORE(intro,1)'
            '>OUTPUT_AI_GLUE(strict)'
        )

        self.assertIsInstance(program.steps[1], GenerateStep)
        self.assertEqual(program.steps[1].artifact, "outline")

        unfold = next(step for step in program.steps if isinstance(step, UnfoldStep))
        self.assertEqual(unfold.source_artifact, "outline")
        self.assertEqual(unfold.child_artifact, "section_draft")
        self.assertEqual(unfold.candidates_count, 2)
        self.assertTrue(unfold.judge)

        relative = next(step for step in program.steps if isinstance(step, GenerateRelativeStep))
        self.assertEqual(relative.artifact, "intro")
        self.assertEqual(relative.position, "before")

        self.assertIsInstance(program.steps[-1], OutputAiGlueStep)

    def test_materialize_and_verify_steps_parse_as_terminal_runtime_steps(self) -> None:
        program = parse_program(
            'RESOLVE("Task","DoD")'
            '>GEN(file_manifest,1)>JUDGE'
            '>UNFOLD(file_manifest,file_implementation,1)'
            '>MATERIALIZE("examples/generated app")'
            '>VERIFY("node --check src/main.js")'
        )

        materialize = next(step for step in program.steps if isinstance(step, MaterializeStep))
        verify = next(step for step in program.steps if isinstance(step, VerifyStep))

        self.assertEqual(materialize.target_dir, "examples/generated app")
        self.assertEqual(verify.command, "node --check src/main.js")
        self.assertIsInstance(program.steps[-1], VerifyStep)

    def test_parse_errors_are_raised_for_invalid_workflows(self) -> None:
        cases = [
            "",
            'PLAN(1)>RESOLVE("Task","DoD")',
            'RESOLVE("Task","DoD")>PLAN(0)',
            'RESOLVE("Task","DoD")>UNKNOWN',
            'RESOLVE("unterminated","DoD)>PLAN(1)',
            'RESOLVE("Task","DoD")>VERIFY(node --check src/main.js)',
        ]

        for source in cases:
            with self.subTest(source=source):
                with self.assertRaises(ParseError):
                    parse_program(source)

    def test_removed_shortcut_steps_are_invalid(self) -> None:
        for source in [
            'RESOLVE("Task","DoD")>ANGLE(1)',
            'RESOLVE("Task","DoD")>PLAN(1)',
            'RESOLVE("Task","DoD")>DRAFT(1)',
        ]:
            with self.subTest(source=source):
                with self.assertRaises(ParseError):
                    parse_program(source)


if __name__ == "__main__":
    unittest.main()
