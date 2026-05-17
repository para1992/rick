from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from seedflow_cli.cli import main


@contextlib.contextmanager
def chdir(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class CLITests(unittest.TestCase):
    def test_interactive_mode_starts_tui(self) -> None:
        with patch("seedflow_cli.tui.run_tui", return_value=0) as run_tui:
            code = main(["--interactive"])

        self.assertEqual(code, 0)
        run_tui.assert_called_once()

    def test_workflow_argument_is_required(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                main([])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("workflow is required", stderr.getvalue())

    def test_one_shot_cli_loads_context_and_prompt_aliases_from_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            (tmp_path / "docs").mkdir()
            (tmp_path / "docs" / "spec.md").write_text("Workspace context", encoding="utf-8")

            with chdir(tmp_path):
                workspace_dir = Path(".rick/workspaces")
                workspace_dir.mkdir(parents=True)
                (workspace_dir / "cli.json").write_text(
                    json.dumps(
                        {
                            "contexts": {"spec": "docs/spec.md"},
                            "prompts": {
                                "article": {
                                    "template": "Workspace prompt for {artifact}: {task}",
                                    "seed": True,
                                    "model": "medium",
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )

                stdout = io.StringIO()
                with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False), contextlib.redirect_stdout(stdout):
                    code = main(
                        [
                            'RESOLVE("Task","DoD")>CONTEXT(spec)>GEN(article,1)>OUTPUT_GLUE',
                            "--workspace",
                            "cli",
                            "--run-dir",
                            "runs/cli-workspace",
                        ]
                    )

                self.assertEqual(code, 0)

                run_data = json.loads(Path("runs/cli-workspace/run.json").read_text(encoding="utf-8"))
                self.assertIn('CONTEXT("docs/spec.md")', run_data["workflow_source"])

                prompts = [
                    event["payload"]["prompt"]
                    for event in run_data["events"]
                    if event["type"] == "step" and "prompt" in event["payload"]
                ]

                self.assertTrue(any("Workspace prompt for article: Task" in prompt for prompt in prompts))


if __name__ == "__main__":
    unittest.main()
