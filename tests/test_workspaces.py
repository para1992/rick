from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from seedflow_cli.workspaces import Workspace, WorkspaceError, WorkspaceStore


class WorkspaceTests(unittest.TestCase):
    def test_workspace_loads_from_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "linkedin.json").write_text(
                json.dumps(
                    {
                        "contexts": {"spec": "docs/spec.md"},
                        "prompts": {"draft": {"template": "Write", "seed": False, "model": "high"}},
                        "workflows": {"article": "GEN(draft,1)>EDIT(strict)"},
                        "artifacts": [{"run": "runs/example"}],
                    }
                ),
                encoding="utf-8",
            )

            store = WorkspaceStore(root)
            loaded = store.load("linkedin")

            self.assertEqual(loaded.name, "linkedin")
            self.assertEqual(loaded.contexts, {"spec": "docs/spec.md"})
            self.assertEqual(loaded.prompts, {"draft": {"template": "Write", "seed": False, "model": "high"}})
            self.assertEqual(loaded.workflows, {"article": "GEN(draft,1)>EDIT(strict)"})
            self.assertEqual(loaded.artifacts, [{"run": "runs/example"}])

    def test_missing_workspace_loads_empty_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = WorkspaceStore(Path(directory))

            workspace = store.load("default")

            self.assertEqual(workspace.name, "default")
            self.assertEqual(workspace.contexts, {})
            self.assertEqual(workspace.prompts, {})

    def test_workspace_normalizes_prompt_shapes(self) -> None:
        workspace = Workspace.from_dict(
            "default",
            {
                "contexts": [],
                "prompts": {
                    "simple": "Write plainly",
                    "custom": {"template": "Write strictly", "seed": False, "model": "high"},
                    "bad": 123,
                },
                "workflows": [],
                "artifacts": {},
            },
        )

        self.assertEqual(workspace.contexts, {})
        self.assertEqual(workspace.workflows, {})
        self.assertEqual(workspace.artifacts, [])
        self.assertEqual(workspace.prompts["simple"], {"template": "Write plainly", "seed": True, "model": "medium"})
        self.assertEqual(workspace.prompts["custom"], {"template": "Write strictly", "seed": False, "model": "high"})
        self.assertNotIn("bad", workspace.prompts)

    def test_workspace_rejects_invalid_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = WorkspaceStore(Path(directory))

            with self.assertRaises(WorkspaceError):
                store.load("../bad")

    def test_store_loads_non_object_json_as_empty_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.mkdir(exist_ok=True)
            (root / "default.json").write_text(json.dumps(["not", "object"]), encoding="utf-8")
            store = WorkspaceStore(root)

            workspace = store.load("default")

            self.assertEqual(workspace.name, "default")
            self.assertEqual(workspace.contexts, {})


if __name__ == "__main__":
    unittest.main()
