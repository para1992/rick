from __future__ import annotations

import shutil
import sys
import time
import textwrap
from dataclasses import dataclass
from datetime import datetime
from typing import Any

try:
    from rich import box
    from rich.align import Align
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError:  # pragma: no cover - optional terminal UI dependency
    box = None  # type: ignore[assignment]
    Align = None  # type: ignore[assignment]
    Console = None  # type: ignore[assignment]
    Group = None  # type: ignore[assignment]
    Live = None  # type: ignore[assignment]
    Panel = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]
    Text = None  # type: ignore[assignment]

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - optional renderer dependency
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]


MIN_COLUMNS_FOR_UI = 88
MIN_ROWS_FOR_UI = 24
DOG_WIDTH = 52
DOG_INNER_WIDTH = DOG_WIDTH - 2
DOG_PANEL_WIDTH = 56
MIN_CHAT_WIDTH = 42
LIVE_VERTICAL_MARGIN = 1
FRAME_DELAY_SECONDS = 0.28
HISTORY_LIMIT = 80
FULL_SCENE_ROWS = 21
COMPACT_SCENE_ROWS = 14
DOG_IMAGE_WIDTH = 44
DOG_IMAGE_HEIGHT = 28


@dataclass(frozen=True)
class SceneSpec:
    title: str
    action: str
    prop: tuple[str, ...]
    mood: str = "normal"


SCENE_SPECS: dict[str, SceneSpec] = {
    "RESOLVE": SceneSpec(
        title="RESOLVE",
        action="sniffs the task",
        prop=(
            "      .----------------------.",
            "      | task        dod      |",
            "      | sniff -> scope       |",
            "      '----------------------'",
        ),
    ),
    "DEFINE_DOD": SceneSpec(
        title="DEFINE_DOD",
        action="writes the rubric",
        prop=(
            "      .----------------------.",
            "      | hidden rubric        |",
            "      | [x] audience         |",
            "      | [x] quality bar      |",
            "      '----------------------'",
        ),
        mood="focused",
    ),
    "CONTEXT": SceneSpec(
        title="CONTEXT",
        action="reads context",
        prop=(
            "          .------------.",
            "        .-| docs/spec  |",
            "        | | research   |",
            "        '-| context    |",
            "          '------------'",
        ),
    ),
    "GEN": SceneSpec(
        title="GEN",
        action="spins up candidates",
        prop=(
            "      .----.  .----.  .----.",
            "      | c1 |  | c2 |  | c3 |",
            "      '----'  '----'  '----'",
            "             candidate pool",
        ),
    ),
    "GEN_BEFORE": SceneSpec(
        title="GEN_BEFORE",
        action="opens a new lead-in",
        prop=(
            "      .--------.  .----------.",
            "      | before |->| document |",
            "      '--------'  '----------'",
            "          prepend candidate",
        ),
    ),
    "GEN_AFTER": SceneSpec(
        title="GEN_AFTER",
        action="extends the tail",
        prop=(
            "      .----------.  .-------.",
            "      | document |->| after |",
            "      '----------'  '-------'",
            "           append candidate",
        ),
    ),
    "UNFOLD": SceneSpec(
        title="UNFOLD",
        action="splits the outline",
        prop=(
            "       outline",
            "          |",
            "      .---+---+---.",
            "      u1      u2  u3",
            "      each unit gets a draft",
        ),
        mood="focused",
    ),
    "ANGLE": SceneSpec(
        title="ANGLE",
        action="tilts his head",
        prop=(
            "             ?",
            "         .-' angle '-.",
            "         | conflict  |",
            "         | promise   |",
            "         '-----------'",
        ),
        mood="curious",
    ),
    "PLAN": SceneSpec(
        title="PLAN",
        action="draws a paw-map",
        prop=(
            "      .----------------------.",
            "      | 1. hook              |",
            "      | 2. mechanism         |",
            "      | 3. payoff        /   |",
            "      '------------------/---'",
        ),
        mood="focused",
    ),
    "DRAFT": SceneSpec(
        title="DRAFT",
        action="types the draft",
        prop=(
            "      .----------------------.",
            "      | click  clack  click  |",
            "      |      keyboard        |",
            "      '----------------------'",
        ),
    ),
    "JUDGE": SceneSpec(
        title="JUDGE",
        action="holds the gavel",
        prop=(
            "             ____",
            "          __/____\\__",
            "             gavel",
            "        score / reason / pick",
        ),
        mood="stern",
    ),
    "MODEL": SceneSpec(
        title="MODEL",
        action="runs to the model",
        prop=(
            "      >>> request",
            "      ... waiting tokens ...",
            "      <<< response",
        ),
        mood="alert",
    ),
    "GLUE": SceneSpec(
        title="GLUE",
        action="glues accepted pieces",
        prop=(
            "      seam A === seam B",
            "            glue press",
            "      one continuous artifact",
        ),
    ),
    "AI_GLUE": SceneSpec(
        title="AI_GLUE",
        action="smooths the seams",
        prop=(
            "      raw pieces -> editor pass",
            "      .----------------------.",
            "      | one voice, no seams  |",
            "      '----------------------'",
        ),
        mood="focused",
    ),
    "EDIT": SceneSpec(
        title="EDIT",
        action="polishes the artifact",
        prop=(
            "      .----------------------.",
            "      | remove filler        |",
            "      | preserve decisions   |",
            "      '----------------------'",
        ),
        mood="focused",
    ),
    "RANDOM": SceneSpec(
        title="AUTO_PICK",
        action="picks a fallback candidate",
        prop=(
            "          \\ | /",
            "           \\|/",
            "        random but logged",
            "           /|\\",
        ),
        mood="curious",
    ),
    "DONE": SceneSpec(
        title="DONE",
        action="wags",
        prop=(
            "           \\   /",
            "            \\ /",
            "      .----------------.",
            "      | artifact ready |",
            "      '----------------'",
        ),
        mood="happy",
    ),
    "ERROR": SceneSpec(
        title="ERROR",
        action="freezes on the stacktrace",
        prop=(
            "      .----------------------.",
            "      | something is off     |",
            "      | check log + run.json |",
            "      '----------------------'",
        ),
        mood="worried",
    ),
}


PIXEL_COLORS = {
    "W": "#f7ead7",
    "T": "#c98c54",
    "R": "#2f8f7f",
    "K": "#141414",
    "P": "#d98aa5",
}

PIXEL_SPRITES = {
    "RUN0": (
        "....................................",
        ".........................TT.........",
        "........................TWWT........",
        ".......................TWWWWT.......",
        "......................TWWTWWT.......",
        ".....................TWWWWWWT.......",
        ".................TTT.TWWWWWWWT......",
        "................TWWTTWWWWWWWWWK.....",
        "....TT.........TWWWWWWWWWWKWWWWK....",
        "...TWWT....TTTTWWWWWWWWWWWWWWWK.....",
        "..TWWWWTTTTWWWWWWWWWWWWWWWWWWT......",
        ".TWWWWWWWWWWWWWWWWWWWWWWWWTT........",
        "TWWWWWWWWWWWWWWWWWWWWWWTTT.........",
        ".TWWWWWWWWWWWWWWWWWWTTT............",
        "..TTWWWWWWWWWWWWWWTT...............",
        "....TTTWWWWWWWWTTT.................",
        ".......TTTTRRRRTT..................",
        "..........TWWT....TWWT.............",
        ".........TWWT......TWWT............",
        "........TWWT........TWWT...........",
        "........TTT.........TTT............",
        "....................................",
    ),
    "RUN1": (
        "....................................",
        ".........................TT.........",
        "........................TWWT........",
        ".......................TWWWWT.......",
        "......................TWWTWWT.......",
        ".....................TWWWWWWT.......",
        "...............TTT...TWWWWWWWT......",
        "..............TWWWT.TWWWWWWWWWK.....",
        ".....TT......TWWWWWWWWWWWKWWWWK.....",
        "...TTWWTTTTTTWWWWWWWWWWWWWWWWK......",
        "..TWWWWWWWWWWWWWWWWWWWWWWWWWT.......",
        ".TWWWWWWWWWWWWWWWWWWWWWWTTT........",
        "..TWWWWWWWWWWWWWWWWWWTTT...........",
        "...TTWWWWWWWWWWWWWWTT..............",
        ".....TTTWWWWWWWWTTT................",
        "........TTTTRRRTT..................",
        ".........TWWT......TWWT............",
        "........TWWT........TWWT...........",
        ".......TWWT.........TWWT...........",
        ".......TTT..........TTT............",
        "....................................",
        "....................................",
    ),
    "SIT": (
        "....................................",
        ".........................TT.........",
        "........................TWWT........",
        ".......................TWWWWT.......",
        "......................TWWTWWT.......",
        ".....................TWWWWWWT.......",
        "..................TT.TWWWWWWWT......",
        ".................TWWTTWWWWWWWWK.....",
        "...............TTWWWWWWWWKWWWWK.....",
        "..........TTTTTWWWWWWWWWWWWWWK......",
        ".......TTTWWWWWWWWWWWWWWWWWWT.......",
        ".....TTWWWWWWWWWWWWWWWWWWTT........",
        "...TTWWWWWWWWWWWWWWWWTTTT..........",
        "..TWWWWWWWWWWWWWWTTTT..............",
        "..TWWWWWWWWWWWWTT..................",
        "...TTTTWWWWTTTT....................",
        "......TTRRRTT......................",
        ".......TWWT........................",
        "......TWWWWT.......................",
        ".....TWWTTWWT......................",
        ".....TTT..TTT......................",
        "....................................",
    ),
    "DOWN": (
        "....................................",
        "....................................",
        ".........................TT.........",
        "........................TWWT........",
        ".......................TWWWWT.......",
        ".................TTTTTTWWWWWWTK.....",
        ".............TTTTWWWWWWWWKWWWK......",
        "......TTTTTTTWWWWWWWWWWWWWWWT.......",
        "...TTTWWWWWWWWWWWWWWWWWWTTT.........",
        "..TWWWWWWWWWWWWWWWWTTTT............",
        "...TTTTTWWWRRRTTTT................",
        "........TWWT....TWWT...............",
        "........TTT.....TTT................",
        "....................................",
    ),
}


SPRITE_ROWS_FOR_COMPACT = (0, 2, 4, 6, 8, 10, 12, 15, 17, 19)


def _build_frames(compact: bool = False) -> dict[str, list[list[str]]]:
    return {
        key: [_build_scene(key, frame_index, compact=compact) for frame_index in range(4)]
        for key in SCENE_SPECS
    }


def _build_scene(stage: str, frame_index: int, compact: bool = False) -> list[str]:
    spec = SCENE_SPECS.get(stage, SCENE_SPECS["MODEL"])
    rows = COMPACT_SCENE_ROWS if compact else FULL_SCENE_ROWS
    body = _compact_body(spec, frame_index) if compact else _full_body(spec, frame_index)
    prop_rows = max(0, rows - len(body))
    scene = body + _prop_lines(spec.prop, prop_rows)
    return _normalize_scene(scene, rows)


def _full_body(spec: SceneSpec, frame_index: int) -> list[str]:
    return _plain_sprite_lines(spec.title, frame_index, compact=False)


def _compact_body(spec: SceneSpec, frame_index: int) -> list[str]:
    return _plain_sprite_lines(spec.title, frame_index, compact=True)


def _plain_sprite_lines(stage: str, frame_index: int, compact: bool) -> list[str]:
    color_rows = _dog_color_rows(stage, frame_index, compact=compact)
    if color_rows is not None:
        return _plain_color_lines(color_rows)

    matrix = _sprite_matrix(stage, frame_index, compact=compact)
    lines: list[str] = []

    for top, bottom in _row_pairs(matrix):
        rendered = "".join(_plain_half_pixel(top[index], bottom[index]) for index in range(len(top)))
        lines.append(rendered.center(DOG_INNER_WIDTH).rstrip())

    lines.append("")
    return lines


def _plain_color_lines(rows: tuple[tuple[str | None, ...], ...]) -> list[str]:
    lines: list[str] = []

    for top, bottom in _color_row_pairs(rows):
        rendered = "".join(_plain_half_color(top[index], bottom[index]) for index in range(len(top)))
        lines.append(rendered.center(DOG_INNER_WIDTH).rstrip())

    lines.append("")
    return lines


def colored_rick_panel_fragments(
    stage_or_message: str,
    rows: int = 30,
    frame_index: int = 0,
    width: int = DOG_WIDTH,
) -> list[tuple[str, str]]:
    stage = scene_key_for(stage_or_message)
    rows = max(5, rows)
    width = max(18, width)
    inner = width - 2
    compact = rows < 30
    available_scene_rows = max(0, rows - 4)
    scene_lines = _colored_scene_fragments(stage, frame_index, compact, inner)[:available_scene_rows]
    fragments: list[tuple[str, str]] = []

    _append_line_fragments(fragments, [("class:dog.border", "+" + "-" * inner + "+")])
    _append_line_fragments(fragments, [("class:dog.border", "|" + _center(f"RICK / {stage}", inner) + "|")])
    _append_line_fragments(fragments, [("class:dog.border", "+" + "-" * inner + "+")])

    for line in scene_lines:
        fragments.append(("class:dog.border", "|"))
        fragments.extend(line)
        fragments.append(("class:dog.border", "|\n"))

    while _fragment_line_count(fragments) < rows - 1:
        _append_line_fragments(fragments, [("class:dog.border", "|" + " " * inner + "|")])

    fragments.append(("class:dog.border", "+" + "-" * inner + "+"))
    return fragments


def _colored_scene_fragments(stage: str, frame_index: int, compact: bool, inner: int) -> list[list[tuple[str, str]]]:
    spec = SCENE_SPECS.get(stage, SCENE_SPECS["MODEL"])
    rows = COMPACT_SCENE_ROWS if compact else FULL_SCENE_ROWS
    body = _colored_sprite_fragments(stage, frame_index, compact, inner)
    prop_rows = max(0, rows - len(body))
    prop = [[("class:dog.prop", _fit(line, inner))] for line in _prop_lines(spec.prop, prop_rows)]
    scene = body + prop

    while len(scene) < rows:
        scene.append([("", " " * inner)])

    return scene[:rows]


def _colored_sprite_fragments(stage: str, frame_index: int, compact: bool, inner: int) -> list[list[tuple[str, str]]]:
    color_rows = _dog_color_rows(stage, frame_index, compact=compact)

    if color_rows is not None:
        lines = [_color_pair_fragments(top, bottom) for top, bottom in _color_row_pairs(color_rows)]
    else:
        lines = [_sprite_pair_fragments(top, bottom) for top, bottom in _row_pairs(_sprite_matrix(stage, frame_index, compact=compact))]

    centered = [_center_fragments(line, inner) for line in lines]
    centered.append([("", " " * inner)])
    return centered


def _color_pair_fragments(top: tuple[str | None, ...], bottom: tuple[str | None, ...]) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = []

    for index in range(len(top)):
        char, style = _prompt_half_color(top[index], bottom[index])
        fragments.append((style, char))

    return fragments


def _sprite_pair_fragments(top: str, bottom: str) -> list[tuple[str, str]]:
    fragments: list[tuple[str, str]] = []

    for index in range(len(top)):
        char, style = _prompt_half_pixel(top[index], bottom[index])
        fragments.append((style, char))

    return fragments


def _prompt_half_color(top: str | None, bottom: str | None) -> tuple[str, str]:
    if top and bottom:
        if top == bottom:
            return "█", f"fg:{top}"
        return "▀", f"fg:{top} bg:{bottom}"
    if top:
        return "▀", f"fg:{top}"
    if bottom:
        return "▄", f"fg:{bottom}"
    return " ", ""


def _prompt_half_pixel(top: str, bottom: str) -> tuple[str, str]:
    top_color = PIXEL_COLORS.get(top)
    bottom_color = PIXEL_COLORS.get(bottom)

    if top_color and bottom_color:
        if top_color == bottom_color:
            return "█", f"fg:{top_color}"
        return "▀", f"fg:{top_color} bg:{bottom_color}"
    if top_color:
        return "▀", f"fg:{top_color}"
    if bottom_color:
        return "▄", f"fg:{bottom_color}"
    return " ", ""


def _center_fragments(fragments: list[tuple[str, str]], width: int) -> list[tuple[str, str]]:
    text_width = sum(len(text) for _, text in fragments)

    if text_width > width:
        return _trim_fragments(fragments, width)

    left = (width - text_width) // 2
    right = width - text_width - left
    return [("", " " * left)] + fragments + [("", " " * right)]


def _trim_fragments(fragments: list[tuple[str, str]], width: int) -> list[tuple[str, str]]:
    trimmed: list[tuple[str, str]] = []
    remaining = width

    for style, text in fragments:
        if remaining <= 0:
            break

        chunk = text[:remaining]
        trimmed.append((style, chunk))
        remaining -= len(chunk)

    if remaining > 0:
        trimmed.append(("", " " * remaining))

    return trimmed


def _append_line_fragments(target: list[tuple[str, str]], fragments: list[tuple[str, str]]) -> None:
    target.extend(fragments)
    target.append(("", "\n"))


def _fragment_line_count(fragments: list[tuple[str, str]]) -> int:
    return sum(text.count("\n") for _, text in fragments)


def _dog_color_rows(stage: str, frame_index: int, compact: bool = False) -> tuple[tuple[str | None, ...], ...] | None:
    if Image is None or ImageDraw is None:
        return None

    image = _draw_dog_image(stage, frame_index)

    if compact:
        image = image.resize((36, 20), Image.Resampling.NEAREST)

    pixels = image.load()
    rows: list[tuple[str | None, ...]] = []

    for y in range(image.height):
        row: list[str | None] = []
        for x in range(image.width):
            red, green, blue, alpha = pixels[x, y]
            row.append(None if alpha < 16 else f"#{red:02x}{green:02x}{blue:02x}")
        rows.append(tuple(row))

    return tuple(rows)


def _draw_dog_image(stage: str, frame_index: int) -> Any:
    image = Image.new("RGBA", (DOG_IMAGE_WIDTH, DOG_IMAGE_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    key = _sprite_key(stage, frame_index)
    phase = frame_index % 2
    y_offset = 3 if key == "DOWN" else 0
    cream = (247, 234, 215, 255)
    tan = (201, 140, 84, 255)
    tan_dark = (126, 80, 45, 255)
    dark = (20, 20, 20, 255)
    pink = (219, 138, 165, 255)
    collar = (47, 143, 127, 255)
    shadow = (94, 63, 42, 180)
    palette = {
        "cream": cream,
        "tan": tan,
        "tan_dark": tan_dark,
        "dark": dark,
        "pink": pink,
        "collar": collar,
        "shadow": shadow,
        "paper": (235, 242, 255, 255),
        "paper_dark": (84, 116, 160, 255),
        "yellow": (247, 210, 92, 255),
        "red": (209, 78, 78, 255),
        "green": (73, 166, 111, 255),
        "blue": (89, 156, 230, 255),
        "purple": (164, 108, 222, 255),
        "metal": (190, 196, 205, 255),
    }

    # Tail, legs and body are drawn first so the head and ears stay crisp.
    if key == "DOWN":
        draw.line([(10, 17), (4, 15), (7, 12)], fill=tan_dark, width=3)
    elif phase:
        draw.line([(10, 15), (3, 11), (7, 8)], fill=tan_dark, width=3)
    else:
        draw.line([(10, 15), (3, 13), (6, 9)], fill=tan_dark, width=3)

    draw.ellipse((8, 13 + y_offset, 30, 23 + y_offset), fill=tan, outline=tan_dark, width=1)
    draw.ellipse((13, 15 + y_offset, 29, 23 + y_offset), fill=cream)
    draw.line((27, 16 + y_offset, 30, 17 + y_offset), fill=collar, width=2)

    if key == "SIT":
        _draw_leg(draw, (14, 21 + y_offset), (13, 26), cream, tan_dark)
        _draw_leg(draw, (23, 21 + y_offset), (25, 26), cream, tan_dark)
        draw.ellipse((12, 24, 17, 27), fill=cream, outline=tan_dark)
        draw.ellipse((23, 24, 28, 27), fill=cream, outline=tan_dark)
    elif key == "DOWN":
        _draw_leg(draw, (14, 22 + y_offset), (12, 26), cream, tan_dark)
        _draw_leg(draw, (25, 22 + y_offset), (28, 26), cream, tan_dark)
    elif phase:
        _draw_leg(draw, (14, 21 + y_offset), (9, 26), cream, tan_dark)
        _draw_leg(draw, (25, 21 + y_offset), (31, 25), cream, tan_dark)
    else:
        _draw_leg(draw, (14, 21 + y_offset), (16, 26), cream, tan_dark)
        _draw_leg(draw, (25, 21 + y_offset), (23, 26), cream, tan_dark)

    head_y = 7 + min(y_offset, 2)
    draw.polygon([(28, head_y + 4), (25, head_y - 7), (33, head_y + 2)], fill=tan, outline=tan_dark)
    draw.polygon([(34, head_y + 4), (39, head_y - 6), (40, head_y + 6)], fill=tan, outline=tan_dark)
    draw.polygon([(29, head_y + 2), (27, head_y - 3), (32, head_y + 2)], fill=pink)
    draw.polygon([(35, head_y + 3), (38, head_y - 2), (38, head_y + 4)], fill=pink)
    draw.ellipse((25, head_y, 39, head_y + 13), fill=cream, outline=tan_dark, width=1)
    draw.ellipse((34, head_y + 5, 43, head_y + 11), fill=cream, outline=tan_dark, width=1)
    draw.ellipse((33, head_y + 4, 35, head_y + 6), fill=dark)
    draw.ellipse((41, head_y + 7, 44, head_y + 10), fill=dark)
    draw.arc((35, head_y + 8, 42, head_y + 14), 20, 135, fill=shadow, width=1)

    if key == "ERROR":
        draw.line((31, head_y + 5, 35, head_y + 5), fill=dark, width=1)
    if key == "DONE":
        draw.arc((32, head_y + 3, 36, head_y + 7), 0, 180, fill=dark, width=1)

    _draw_stage_action(draw, stage, frame_index, key, palette)

    return image


def _draw_leg(draw: Any, start: tuple[int, int], end: tuple[int, int], fill: tuple[int, int, int, int], outline: tuple[int, int, int, int]) -> None:
    draw.line([start, end], fill=outline, width=4)
    draw.line([start, end], fill=fill, width=2)
    foot_x, foot_y = end
    draw.ellipse((foot_x - 2, foot_y - 1, foot_x + 3, foot_y + 2), fill=fill, outline=outline)


def _draw_stage_action(draw: Any, stage: str, frame_index: int, pose: str, palette: dict[str, tuple[int, int, int, int]]) -> None:
    phase = frame_index % 4

    if stage == "RESOLVE":
        _draw_sniff(draw, phase, palette)
        _draw_magnifier(draw, 4, 18, palette)
        return

    if stage == "DEFINE_DOD":
        _draw_clipboard(draw, 3, 5, palette, checks=2 + phase % 2)
        _draw_pencil(draw, 17, 17 + phase % 2, palette)
        return

    if stage == "CONTEXT":
        _draw_doc_stack(draw, 3, 5, palette)
        _draw_read_lines(draw, phase, palette)
        return

    if stage == "GEN":
        for index, x in enumerate((3, 9, 15), start=1):
            _draw_candidate_card(draw, x, 4 + ((phase + index) % 2), palette, selected=False)
        _draw_speed_lines(draw, phase, palette)
        return

    if stage == "GEN_BEFORE":
        _draw_document(draw, 3, 7, palette)
        _draw_arrow(draw, 13, 11, 23, 11, palette["blue"])
        _draw_candidate_card(draw, 2, 2 + phase % 2, palette, selected=True)
        return

    if stage == "GEN_AFTER":
        _draw_document(draw, 3, 5, palette)
        _draw_arrow(draw, 13, 9, 23, 9, palette["green"])
        _draw_candidate_card(draw, 24, 3 + phase % 2, palette, selected=True)
        return

    if stage == "UNFOLD":
        _draw_tree(draw, phase, palette)
        return

    if stage == "ANGLE":
        draw.text((5, 2 + phase % 2), "?", fill=palette["yellow"])
        draw.text((10, 4), "?", fill=palette["yellow"])
        _draw_sparkle(draw, 15, 5, palette["yellow"])
        return

    if stage == "PLAN":
        _draw_map(draw, 3, 4, palette, phase)
        return

    if stage == "DRAFT":
        _draw_keyboard(draw, 4, 22, palette, phase)
        _draw_typing_paw(draw, 25 + phase % 2, 21, palette)
        return

    if stage == "JUDGE":
        _draw_gavel(draw, 28, 18 + phase % 2, palette)
        _draw_score_card(draw, 4, 5, palette)
        return

    if stage == "MODEL":
        _draw_speed_lines(draw, phase, palette)
        draw.text((2 + phase % 2, 4), ">>>", fill=palette["blue"])
        draw.text((3, 8), "...", fill=palette["paper_dark"])
        return

    if stage == "GLUE":
        _draw_seams(draw, 3, 6, palette, phase)
        _draw_glue_tube(draw, 26, 19, palette)
        return

    if stage == "AI_GLUE":
        _draw_wand(draw, 7, 8, palette)
        _draw_sparkle(draw, 16, 5 + phase % 2, palette["yellow"])
        _draw_sparkle(draw, 21, 10, palette["blue"])
        return

    if stage == "EDIT":
        _draw_edit_card(draw, 4, 5, palette, phase)
        _draw_comb(draw, 24, 21, palette)
        return

    if stage == "RANDOM":
        _draw_dice(draw, 5, 6 + phase % 2, palette)
        _draw_sparkle(draw, 15, 4, palette["purple"])
        return

    if stage == "DONE":
        for x, y, color in ((5, 4, "yellow"), (12, 7, "green"), (20, 3, "blue"), (30, 5, "red")):
            _draw_confetti(draw, x + phase % 2, y, palette[color])
        return

    if stage == "ERROR":
        draw.rectangle((3, 4, 10, 13), fill=palette["red"], outline=palette["dark"])
        draw.line((6, 6, 6, 10), fill=palette["paper"], width=2)
        draw.point((6, 12), fill=palette["paper"])


def _draw_sniff(draw: Any, phase: int, palette: dict[str, tuple[int, int, int, int]]) -> None:
    color = palette["paper_dark"]
    draw.arc((38 + phase % 2, 12, 49, 17), 185, 310, fill=color, width=1)
    draw.arc((40, 8 + phase % 2, 52, 16), 185, 300, fill=color, width=1)


def _draw_magnifier(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]]) -> None:
    draw.ellipse((x, y, x + 6, y + 6), outline=palette["blue"], width=2)
    draw.line((x + 5, y + 5, x + 10, y + 10), fill=palette["blue"], width=2)


def _draw_clipboard(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]], checks: int) -> None:
    draw.rounded_rectangle((x, y, x + 12, y + 16), radius=2, fill=palette["paper"], outline=palette["paper_dark"])
    draw.rectangle((x + 4, y - 1, x + 8, y + 2), fill=palette["metal"], outline=palette["dark"])
    for index in range(3):
        yy = y + 5 + index * 4
        draw.line((x + 5, yy, x + 10, yy), fill=palette["paper_dark"])
        if index < checks:
            draw.line((x + 2, yy, x + 3, yy + 1), fill=palette["green"], width=1)
            draw.line((x + 3, yy + 1, x + 5, yy - 2), fill=palette["green"], width=1)


def _draw_pencil(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]]) -> None:
    draw.line((x, y, x + 8, y - 5), fill=palette["yellow"], width=3)
    draw.line((x + 7, y - 5, x + 9, y - 6), fill=palette["dark"], width=2)


def _draw_doc_stack(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]]) -> None:
    _draw_document(draw, x + 3, y + 3, palette)
    _draw_document(draw, x, y, palette)


def _draw_document(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]]) -> None:
    draw.rectangle((x, y, x + 10, y + 13), fill=palette["paper"], outline=palette["paper_dark"])
    draw.polygon([(x + 7, y), (x + 10, y + 3), (x + 7, y + 3)], fill=palette["metal"])
    for offset in (5, 8, 11):
        draw.line((x + 2, y + offset, x + 8, y + offset), fill=palette["paper_dark"])


def _draw_read_lines(draw: Any, phase: int, palette: dict[str, tuple[int, int, int, int]]) -> None:
    x = 16 + phase % 2
    draw.line((x, 9, x + 5, 8), fill=palette["paper_dark"])
    draw.line((x, 12, x + 5, 12), fill=palette["paper_dark"])


def _draw_candidate_card(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]], selected: bool) -> None:
    fill = palette["yellow"] if selected else palette["paper"]
    draw.rounded_rectangle((x, y, x + 7, y + 9), radius=1, fill=fill, outline=palette["paper_dark"])
    draw.line((x + 2, y + 3, x + 5, y + 3), fill=palette["dark"])
    draw.line((x + 2, y + 6, x + 5, y + 6), fill=palette["dark"])


def _draw_speed_lines(draw: Any, phase: int, palette: dict[str, tuple[int, int, int, int]]) -> None:
    offset = phase % 3
    for y in (7, 11, 15):
        draw.line((1, y + offset, 8, y + offset), fill=palette["paper_dark"])
        draw.line((3, y + 2 + offset, 10, y + 2 + offset), fill=palette["paper_dark"])


def _draw_arrow(draw: Any, x1: int, y1: int, x2: int, y2: int, color: tuple[int, int, int, int]) -> None:
    draw.line((x1, y1, x2, y2), fill=color, width=2)
    draw.polygon([(x2, y2), (x2 - 3, y2 - 2), (x2 - 3, y2 + 2)], fill=color)


def _draw_tree(draw: Any, phase: int, palette: dict[str, tuple[int, int, int, int]]) -> None:
    root = (9, 4)
    children = [(4, 13), (9, 15), (14, 13)]
    draw.rectangle((root[0] - 3, root[1], root[0] + 3, root[1] + 4), fill=palette["paper"], outline=palette["paper_dark"])
    for index, child in enumerate(children):
        color = palette["green"] if index <= phase % 3 else palette["paper_dark"]
        draw.line((root[0], root[1] + 4, child[0], child[1]), fill=color)
        draw.rectangle((child[0] - 2, child[1], child[0] + 2, child[1] + 3), fill=palette["paper"], outline=color)


def _draw_sparkle(draw: Any, x: int, y: int, color: tuple[int, int, int, int]) -> None:
    draw.line((x, y - 2, x, y + 2), fill=color)
    draw.line((x - 2, y, x + 2, y), fill=color)


def _draw_map(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]], phase: int) -> None:
    draw.rectangle((x, y, x + 16, y + 13), fill=palette["paper"], outline=palette["paper_dark"])
    points = [(x + 3, y + 10), (x + 6, y + 6), (x + 10, y + 8), (x + 14, y + 3)]
    for index in range(min(len(points) - 1, 1 + phase % 4)):
        draw.line((points[index], points[index + 1]), fill=palette["blue"], width=2)
    for point in points:
        draw.ellipse((point[0] - 1, point[1] - 1, point[0] + 1, point[1] + 1), fill=palette["red"])


def _draw_keyboard(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]], phase: int) -> None:
    draw.rounded_rectangle((x, y, x + 22, y + 5), radius=1, fill=palette["dark"], outline=palette["metal"])
    for index in range(8):
        key_color = palette["green"] if index == phase % 8 else palette["metal"]
        draw.rectangle((x + 2 + index * 2, y + 2, x + 3 + index * 2, y + 3), fill=key_color)


def _draw_typing_paw(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]]) -> None:
    draw.ellipse((x, y, x + 4, y + 3), fill=palette["cream"], outline=palette["tan_dark"])


def _draw_gavel(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]]) -> None:
    draw.line((x, y, x + 9, y - 8), fill=palette["tan_dark"], width=3)
    draw.rounded_rectangle((x + 7, y - 12, x + 17, y - 8), radius=1, fill=palette["tan"], outline=palette["tan_dark"])
    draw.rectangle((x + 1, y + 1, x + 12, y + 3), fill=palette["tan_dark"])


def _draw_score_card(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]]) -> None:
    draw.rectangle((x, y, x + 12, y + 9), fill=palette["paper"], outline=palette["paper_dark"])
    draw.text((x + 2, y + 1), "87", fill=palette["dark"])
    draw.line((x + 2, y + 7, x + 10, y + 7), fill=palette["green"])


def _draw_seams(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]], phase: int) -> None:
    draw.rectangle((x, y, x + 8, y + 6), fill=palette["paper"], outline=palette["paper_dark"])
    draw.rectangle((x + 15, y, x + 23, y + 6), fill=palette["paper"], outline=palette["paper_dark"])
    draw.line((x + 8, y + 3, x + 15, y + 3), fill=palette["green"], width=2 + phase % 2)


def _draw_glue_tube(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]]) -> None:
    draw.rounded_rectangle((x, y, x + 10, y + 4), radius=1, fill=palette["blue"], outline=palette["dark"])
    draw.polygon([(x + 10, y + 1), (x + 14, y + 2), (x + 10, y + 3)], fill=palette["paper"])


def _draw_wand(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]]) -> None:
    draw.line((x, y + 8, x + 10, y), fill=palette["purple"], width=2)
    _draw_sparkle(draw, x + 11, y, palette["yellow"])


def _draw_edit_card(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]], phase: int) -> None:
    draw.rounded_rectangle((x, y, x + 17, y + 14), radius=2, fill=palette["paper"], outline=palette["paper_dark"])
    draw.line((x + 3, y + 4, x + 13, y + 4), fill=palette["paper_dark"], width=1)
    draw.line((x + 3, y + 8, x + 10, y + 8), fill=palette["paper_dark"], width=1)
    draw.line((x + 3, y + 12, x + 12, y + 12), fill=palette["paper_dark"], width=1)
    draw.line((x + 12, y + 9, x + 15, y + 12), fill=palette["green"], width=2)
    draw.line((x + 15, y + 12, x + 20, y + 5 + phase % 2), fill=palette["green"], width=2)
    draw.rectangle((x + 19, y + 3 + phase % 2, x + 24, y + 6 + phase % 2), fill=palette["yellow"], outline=palette["tan_dark"])


def _draw_comb(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]]) -> None:
    draw.rectangle((x, y, x + 12, y + 2), fill=palette["yellow"], outline=palette["tan_dark"])
    for index in range(6):
        draw.line((x + 1 + index * 2, y + 2, x + 1 + index * 2, y + 6), fill=palette["tan_dark"])


def _draw_dice(draw: Any, x: int, y: int, palette: dict[str, tuple[int, int, int, int]]) -> None:
    draw.rounded_rectangle((x, y, x + 9, y + 9), radius=2, fill=palette["paper"], outline=palette["dark"])
    for px, py in ((x + 2, y + 2), (x + 7, y + 2), (x + 4, y + 4), (x + 2, y + 7), (x + 7, y + 7)):
        draw.ellipse((px - 1, py - 1, px + 1, py + 1), fill=palette["dark"])


def _draw_confetti(draw: Any, x: int, y: int, color: tuple[int, int, int, int]) -> None:
    draw.rectangle((x, y, x + 1, y + 1), fill=color)


def _sprite_matrix(stage: str, frame_index: int, compact: bool = False) -> tuple[str, ...]:
    key = _sprite_key(stage, frame_index)
    matrix = _normalize_matrix(PIXEL_SPRITES[key])

    if not compact:
        return matrix

    return tuple(matrix[index] for index in SPRITE_ROWS_FOR_COMPACT if index < len(matrix))


def _sprite_key(stage: str, frame_index: int) -> str:
    if stage == "ERROR":
        return "DOWN"
    if stage in {"RESOLVE", "DEFINE_DOD", "CONTEXT", "PLAN", "JUDGE"}:
        return "SIT"
    if stage in {"MODEL", "GEN", "GEN_BEFORE", "GEN_AFTER", "DONE"}:
        return "RUN1" if frame_index % 2 else "RUN0"
    if stage in {"DRAFT", "EDIT", "AI_GLUE", "GLUE", "UNFOLD", "RANDOM", "ANGLE"}:
        return "SIT"

    return "RUN0"


def _normalize_matrix(matrix: tuple[str, ...]) -> tuple[str, ...]:
    width = max(len(row) for row in matrix)
    return tuple(row.ljust(width, ".") for row in matrix)


def _rich_sprite_text(stage: str, frame_index: int) -> Any:
    if Text is None:
        return "\n".join(_plain_sprite_lines(stage, frame_index, compact=False))

    text = Text()
    color_rows = _dog_color_rows(stage, frame_index, compact=False)

    if color_rows is not None:
        for top, bottom in _color_row_pairs(color_rows):
            for index in range(len(top)):
                char, style = _rich_half_color(top[index], bottom[index])
                text.append(char, style=style)
            text.append("\n")

        return text

    for top, bottom in _row_pairs(_sprite_matrix(stage, frame_index, compact=False)):
        for index in range(len(top)):
            char, style = _rich_half_pixel(top[index], bottom[index])
            text.append(char, style=style)
        text.append("\n")

    return text


def _color_row_pairs(rows: tuple[tuple[str | None, ...], ...]) -> list[tuple[tuple[str | None, ...], tuple[str | None, ...]]]:
    width = max(len(row) for row in rows)
    padded = [row + (None,) * (width - len(row)) for row in rows]

    if len(padded) % 2:
        padded.append((None,) * width)

    return [(padded[index], padded[index + 1]) for index in range(0, len(padded), 2)]


def _row_pairs(matrix: tuple[str, ...]) -> list[tuple[str, str]]:
    width = max(len(row) for row in matrix)
    padded = [row.ljust(width, ".") for row in matrix]

    if len(padded) % 2:
        padded.append("." * width)

    return [(padded[index], padded[index + 1]) for index in range(0, len(padded), 2)]


def _plain_half_pixel(top: str, bottom: str) -> str:
    top_filled = top != "."
    bottom_filled = bottom != "."

    if top_filled and bottom_filled:
        return "█"
    if top_filled:
        return "▀"
    if bottom_filled:
        return "▄"
    return " "


def _plain_half_color(top: str | None, bottom: str | None) -> str:
    if top and bottom:
        return "█"
    if top:
        return "▀"
    if bottom:
        return "▄"
    return " "


def _rich_half_pixel(top: str, bottom: str) -> tuple[str, str]:
    top_color = PIXEL_COLORS.get(top)
    bottom_color = PIXEL_COLORS.get(bottom)

    if top_color and bottom_color:
        if top_color == bottom_color:
            return "█", top_color
        return "▀", f"{top_color} on {bottom_color}"
    if top_color:
        return "▀", top_color
    if bottom_color:
        return "▄", bottom_color
    return " ", ""


def _rich_half_color(top: str | None, bottom: str | None) -> tuple[str, str]:
    if top and bottom:
        if top == bottom:
            return "█", top
        return "▀", f"{top} on {bottom}"
    if top:
        return "▀", top
    if bottom:
        return "▄", bottom
    return " ", ""


def _prop_lines(prop: tuple[str, ...], rows: int) -> list[str]:
    lines = list(prop[:rows])

    while len(lines) < rows:
        lines.append("")

    return lines


def _normalize_scene(lines: list[str], rows: int) -> list[str]:
    normalized = [_fit(line, DOG_INNER_WIDTH) for line in lines[:rows]]

    while len(normalized) < rows:
        normalized.append(" " * DOG_INNER_WIDTH)

    return normalized


class RickAnimator:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._ui_enabled = enabled and sys.stderr.isatty() and Live is not None and _terminal_is_large_enough()
        self._history: list[tuple[str, str]] = []
        self._message = "ready"
        self._stage = "MODEL"
        self._created_at = time.monotonic()
        self._console: Any | None = Console(stderr=True) if Console is not None else None
        self._live: Any | None = None

    def start(self, message: str) -> None:
        if not self.enabled:
            return

        if self._ui_enabled:
            self._update(message)
            self._ensure_live()
            self._live.update(self._render_live(), refresh=True)
            return

        print(rick_status_line(message), flush=True)

    def stop(self, final_message: str | None = None) -> None:
        if not self.enabled:
            return

        if self._ui_enabled:
            if final_message:
                self._update(final_message)
                self._ensure_live()
                self._live.update(self._render_live(), refresh=True)
                time.sleep(0.1)
            self._stop_live()
            return

        if final_message:
            print(rick_status_line(final_message), flush=True)

    def _update(self, message: str) -> None:
        self._message = message
        self._stage = scene_key_for(message)
        self._history.append((datetime.now().strftime("%H:%M:%S"), message))
        self._history = self._history[-HISTORY_LIMIT:]

    def _ensure_live(self) -> None:
        if self._live is not None:
            return

        self._live = Live(
            None,
            console=self._console,
            refresh_per_second=8,
            transient=False,
            get_renderable=self._render_live,
        )
        self._live.start(refresh=True)

    def _stop_live(self) -> None:
        if self._live is None:
            return

        self._live.stop()
        self._live = None

    def _render_live(self) -> Any:
        if Table is None:
            return "\n".join(render_rick_panel(self._stage, rows=30, frame_index=self._current_frame_index()))

        size = shutil.get_terminal_size((120, 40))
        height = max(12, size.lines - LIVE_VERTICAL_MARGIN)
        dog_width = _dog_panel_width(size.columns)
        chat_width = max(MIN_CHAT_WIDTH, size.columns - dog_width - 5)

        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(ratio=1, min_width=MIN_CHAT_WIDTH)
        table.add_column(width=dog_width)
        table.add_row(self._chat_renderable(chat_width, height), self._dog_renderable(dog_width, height))
        return table

    def _chat_renderable(self, width: int, height: int) -> Any:
        if Text is None:
            return ""

        inner_width = max(24, width - 6)
        body_height = max(4, height - 9)
        visible_lines = _chat_history_lines(self._history, inner_width, body_height)
        text = Text()
        text.append("Rick session\n", style="bold cyan")
        text.append("workflow transcript\n\n", style="dim")

        for line, style in visible_lines:
            text.append(line, style=style)
            text.append("\n")

        if visible_lines:
            text.append("\n")

        text.append("> ", style="bold cyan")
        text.append(_truncate(self._message, inner_width - 2), style="white")

        if Panel is None:
            return text

        kwargs: dict[str, Any] = {
            "title": "context",
            "border_style": "cyan",
            "padding": (1, 2),
            "height": height,
        }
        if box is not None:
            kwargs["box"] = box.ROUNDED
        return Panel(text, **kwargs)

    def _dog_renderable(self, width: int, height: int) -> Any:
        if Text is None:
            return "\n".join(render_rick_panel(self._stage, rows=height, frame_index=self._current_frame_index()))

        spec = SCENE_SPECS.get(self._stage, SCENE_SPECS["MODEL"])
        if height < 32 or width < DOG_PANEL_WIDTH or Group is None or Panel is None or Align is None:
            lines = render_rick_panel(
                self._stage,
                rows=height,
                frame_index=self._current_frame_index(),
                width=min(width, DOG_WIDTH),
            )
            return Text("\n".join(lines), style="bright_white")

        sprite = _rich_sprite_text(self._stage, self._current_frame_index())
        prop = Text("\n".join(spec.prop[:4]), style="bright_white")
        caption = Text(spec.action, style="bold white")
        content = Group(Align.center(sprite), Align.center(caption), "", prop)
        kwargs: dict[str, Any] = {
            "title": f"RICK / {self._stage}",
            "border_style": "magenta",
            "padding": (1, 2),
            "height": height,
            "width": width,
        }
        if box is not None:
            kwargs["box"] = box.ROUNDED
        return Panel(content, **kwargs)

    def _current_frame_index(self) -> int:
        return int((time.monotonic() - self._created_at) / FRAME_DELAY_SECONDS)


def _chat_history_lines(history: list[tuple[str, str]], width: int, max_lines: int) -> list[tuple[str, str]]:
    if not history:
        return [("No events yet.", "dim")]

    lines: list[tuple[str, str]] = []

    for stamp, message in history:
        stage = scene_key_for(message)
        prefix = f"{stamp} {stage:<10} "
        wrapped = textwrap.wrap(
            message,
            width=max(12, width - len(prefix)),
            break_long_words=False,
            break_on_hyphens=False,
        ) or [""]
        style = _stage_style(stage)

        for index, chunk in enumerate(wrapped):
            line_prefix = prefix if index == 0 else " " * len(prefix)
            lines.append((_truncate(line_prefix + chunk, width), style))

    if len(lines) <= max_lines:
        return lines

    return [("...", "dim")] + lines[-(max_lines - 1) :]


def _stage_style(stage: str) -> str:
    if stage in {"ERROR"}:
        return "bold red"
    if stage in {"JUDGE", "RANDOM"}:
        return "yellow"
    if stage in {"GEN", "GEN_BEFORE", "GEN_AFTER", "UNFOLD"}:
        return "cyan"
    if stage in {"AI_GLUE", "GLUE", "EDIT", "DONE"}:
        return "green"
    if stage in {"MODEL"}:
        return "magenta"
    return "white"


def _dog_panel_width(columns: int) -> int:
    if columns >= 116:
        preferred = DOG_PANEL_WIDTH
    elif columns >= 104:
        preferred = 48
    else:
        preferred = 40

    return min(preferred, max(32, columns - MIN_CHAT_WIDTH - 5))


def render_rick_panel(stage_or_message: str, rows: int = 30, frame_index: int = 0, width: int = DOG_WIDTH) -> list[str]:
    stage = scene_key_for(stage_or_message)
    rows = max(5, rows)
    width = max(18, width)
    inner = width - 2
    compact = rows < 30
    frames = COMPACT_FRAMES if compact else FRAMES
    frame = frames.get(stage, frames["MODEL"])[frame_index % len(frames.get(stage, frames["MODEL"]))]
    available_scene_rows = max(0, rows - 4)

    lines = [
        "+" + "-" * inner + "+",
        "|" + _center(f"RICK / {stage}", inner) + "|",
        "+" + "-" * inner + "+",
    ]

    for line in frame[:available_scene_rows]:
        lines.append("|" + _fit_art(line, inner) + "|")

    while len(lines) < rows - 1:
        lines.append("|" + " " * inner + "|")

    lines.append("+" + "-" * inner + "+")
    return lines[:rows]


def demo_rick_animation() -> None:
    animator = RickAnimator(enabled=True)
    messages = [
        "step: ResolveStep",
        "step: DefineDodStep",
        "llm call 1/24: DEFINE_DOD",
        "done: DEFINE_DOD",
        "step: ContextStep",
        "done: CONTEXT",
        "step: GenerateStep",
        "llm call 2/24: GEN(custom) candidate 1",
        "done: GEN candidate 1",
        "step: GenerateStep",
        "llm call 3/24: GEN(angle) candidate 1",
        "done: ANGLE candidate 1",
        "step: GenerateStep",
        "llm call 4/24: GEN(plan) candidate 1",
        "done: PLAN candidate 1",
        "step: GenerateStep",
        "llm call 5/24: GEN(draft) candidate 1",
        "done: DRAFT candidate 1",
        "step: JudgeStep",
        "llm call 6/24: JUDGE",
        "done: JUDGE",
        "step: UnfoldStep",
        "llm call 7/24: EXPLODE(outline)",
        "done: UNFOLD result",
        "step: GenerateRelativeStep",
        "llm call 8/24: GEN_BEFORE(opening) candidate 1",
        "done: GEN_BEFORE applied",
        "llm call 9/24: GEN_AFTER(ending) candidate 1",
        "done: GEN_AFTER applied",
        "AUTO SELECT RANDOM",
        "step: OutputGlueStep",
        "done: OUTPUT_GLUE",
        "step: OutputAiGlueStep",
        "llm call 10/24: OUTPUT_AI_GLUE",
        "done: OUTPUT_AI_GLUE result",
        "step: EditStep",
        "llm call 11/24: EDIT",
        "done: EDIT result",
    ]

    try:
        for message in messages:
            animator.start(message)
            time.sleep(0.8)
    finally:
        animator.stop("done")


def scene_key_for(message: str) -> str:
    upper = message.upper().strip()

    if upper in SCENE_SPECS:
        return upper
    if "ERROR" in upper:
        return "ERROR"
    if "AUTO SELECT" in upper or "RANDOM" in upper:
        return "RANDOM"
    if "DEFINE_DOD" in upper or "DEFINEDOD" in upper:
        return "DEFINE_DOD"
    if "GEN_BEFORE" in upper:
        return "GEN_BEFORE"
    if "GEN_AFTER" in upper:
        return "GEN_AFTER"
    if "UNFOLD_JUDGE" in upper or "UNFOLD" in upper or "EXPLODE" in upper:
        return "UNFOLD"
    if "OUTPUT_AI_GLUE" in upper or "OUTPUTAIGLUE" in upper:
        return "AI_GLUE"
    if "OUTPUT_GLUE" in upper or "OUTPUTGLUE" in upper or "GLUE" in upper:
        return "GLUE"
    if "GEN(ANGLE" in upper:
        return "ANGLE"
    if "GEN(PLAN" in upper:
        return "PLAN"
    if "GEN(DRAFT" in upper:
        return "DRAFT"
    if "GENERATE" in upper or "GEN(" in upper:
        return "GEN"

    for key in ["RESOLVE", "CONTEXT", "ANGLE", "PLAN", "DRAFT", "JUDGE", "EDIT"]:
        if key in upper:
            return key

    if upper == "DONE" or upper.startswith("DONE ") or upper.startswith("DONE:") or "DONESTEP" in upper:
        return "DONE"
    if "LLM CALL" in upper:
        return "MODEL"

    return "MODEL"


def rick_status_line(message: str) -> str:
    stage = scene_key_for(message)
    action = SCENE_SPECS.get(stage, SCENE_SPECS["MODEL"]).action
    return f"Rick the white chihuahua {action} | {message}"


def _terminal_is_large_enough() -> bool:
    size = shutil.get_terminal_size((120, 40))
    return size.columns >= MIN_COLUMNS_FOR_UI and size.lines >= MIN_ROWS_FOR_UI


def _center(value: str, width: int) -> str:
    value = _truncate(value, width)
    return value.center(width)


def _fit(value: str, width: int) -> str:
    value = _truncate(value, width)
    return value + " " * max(0, width - len(value))


def _fit_art(value: str, width: int) -> str:
    if len(value) > width:
        value = value[:width]
    return value + " " * max(0, width - len(value))


def _truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value

    return value[: max(0, width - 1)] + "."


FRAMES = _build_frames(compact=False)
COMPACT_FRAMES = _build_frames(compact=True)
