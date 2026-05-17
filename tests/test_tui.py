from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from rick_cli.rick import colored_rick_panel_fragments
from rick_cli.tui import RickTui, TuiEvent, _event_fragments, _syntax_fragments, interactive_run_dir


class TuiTests(unittest.TestCase):
    def test_default_interactive_run_dir_uses_numbered_timestamped_directory(self) -> None:
        run_dir = interactive_run_dir(Path("runs/latest"), 2)

        self.assertEqual(run_dir.parent, Path("runs/interactive"))
        self.assertTrue(run_dir.name.endswith("-02"))

    def test_custom_interactive_run_dir_is_stable_for_first_run_and_numbered_after_that(self) -> None:
        self.assertEqual(interactive_run_dir(Path("runs/tui"), 1), Path("runs/tui"))
        self.assertEqual(interactive_run_dir(Path("runs/tui"), 2), Path("runs/tui/02"))

    def test_tui_dog_panel_uses_color_fragments(self) -> None:
        fragments = colored_rick_panel_fragments("GEN", rows=30, width=52)

        self.assertTrue(any("fg:#" in style for style, _ in fragments))
        self.assertIn("RICK / GEN", "".join(text for _, text in fragments))

    def test_workflow_syntax_fragments_style_steps_strings_numbers_and_operators(self) -> None:
        fragments = _syntax_fragments('RESOLVE("Task","DoD")>GEN(plan,3)>JUDGE')
        styles = [style for style, _ in fragments]

        self.assertIn("class:step.resolve", styles)
        self.assertIn("class:step.gen", styles)
        self.assertIn("class:step.judge", styles)
        self.assertIn("class:syntax.string", styles)
        self.assertIn("class:syntax.number", styles)
        self.assertIn("class:syntax.op", styles)

    def test_status_event_fragments_use_stage_style(self) -> None:
        fragments = _event_fragments(TuiEvent(kind="status", text="llm call 1/3: GEN(plan)", stamp="12:00:00"))

        self.assertTrue(any(style == "class:stage.plan" for style, _ in fragments))

    def test_chat_scroll_stops_following_tail_until_scrolled_back_down(self) -> None:
        tui = RickTui(SimpleNamespace())
        for index in range(30):
            tui._append("status", f"event {index}")

        tail_position = tui._chat_cursor_position()
        self.assertEqual(tail_position.y, tui._chat_line_count_unlocked() - 1)

        tui._scroll_chat(-12)
        scrolled_position = tui._chat_cursor_position()
        self.assertLess(scrolled_position.y, tail_position.y)

        tui._append("status", "new event")
        self.assertEqual(tui._chat_cursor_position().y, scrolled_position.y)

        tui._scroll_chat(10_000)
        self.assertEqual(tui._chat_cursor_position().y, tui._chat_line_count_unlocked() - 1)


if __name__ == "__main__":
    unittest.main()
