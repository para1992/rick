from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rick_cli.context_aliases import ContextAliasError, ContextRegistry, parse_context_alias_option
from rick_cli.parser import parse_program
from rick_cli.preflight import PreflightError, validate_workflow_program


class PreflightAndContextTests(unittest.TestCase):
    def test_preflight_accepts_existing_context_file_and_prompt_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            context_path = tmp_path / "spec.md"
            context_path.write_text("context", encoding="utf-8")
            program = parse_program('RESOLVE("Task","DoD")>CONTEXT(spec.md)>GEN(article,1)')

            validate_workflow_program(program, {"article": {"template": "write"}}, cwd=tmp_path)

    def test_preflight_reports_missing_context_and_prompt_aliases(self) -> None:
        program = parse_program('RESOLVE("Task","DoD")>CONTEXT(missing.md)>GEN(article,1)')

        with self.assertRaises(PreflightError) as raised:
            validate_workflow_program(program, {}, cwd=Path("/tmp"))

        message = str(raised.exception)
        self.assertIn("CONTEXT path does not exist: missing.md", message)
        self.assertIn("GEN(article,1) has no prompt alias", message)

    def test_preflight_can_skip_prompt_alias_requirement_for_plain_cli(self) -> None:
        program = parse_program('RESOLVE("Task","DoD")>GEN(article,1)')

        validate_workflow_program(program, {}, require_prompt_aliases=False)

    def test_context_registry_replaces_aliases_and_escapes_paths(self) -> None:
        registry = ContextRegistry()
        registry.set("spec", 'docs/spec "quoted" > v2.md')

        source = 'RESOLVE("Task","DoD")>CONTEXT(spec)>CONTEXT(unknown)'

        self.assertEqual(
            registry.resolve_source(source),
            'RESOLVE("Task","DoD")>CONTEXT("docs/spec \\"quoted\\" > v2.md")>CONTEXT(unknown)',
        )

    def test_context_alias_option_validation(self) -> None:
        self.assertEqual(parse_context_alias_option("spec=docs/spec.md"), ("spec", "docs/spec.md"))

        registry = ContextRegistry()

        with self.assertRaises(ContextAliasError):
            parse_context_alias_option("missing_equals")

        with self.assertRaises(ContextAliasError):
            registry.set("bad alias", "docs/spec.md")

        with self.assertRaises(ContextAliasError):
            registry.set("spec", "")


if __name__ == "__main__":
    unittest.main()
