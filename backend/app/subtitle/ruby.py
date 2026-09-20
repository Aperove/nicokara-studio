from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable
import unicodedata

from app.alignment.models import AlignedLine
from app.alignment.japanese import normalize_reading


@dataclass(frozen=True)
class RubyPlacement:
    text: str
    x: int
    y: int


def text_width_units(text: str) -> float:
    """Approximate rendered width in full-width character units."""
    return sum(
        1.0
        if unicodedata.east_asian_width(character) in ("F", "W", "A")
        else 0.55
        for character in text
    )


def contains_kanji(text: str) -> bool:
    return any(
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        for character in text
    )


def kanji_runs(text: str) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, character in enumerate(text):
        if contains_kanji(character):
            if start is None:
                start = index
        elif start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(text)))
    return runs


def kanji_readings(surface: str, reading: str) -> list[tuple[int, int, str]]:
    runs = kanji_runs(surface)
    if not runs:
        return []
    pattern_parts = ["^"]
    position = 0
    for start, end in runs:
        pattern_parts.append(
            re.escape(normalize_reading(surface[position:start]))
        )
        pattern_parts.append("(.*?)")
        position = end
    pattern_parts.append(re.escape(normalize_reading(surface[position:])))
    pattern_parts.append("$")
    match = re.fullmatch(
        "".join(pattern_parts),
        normalize_reading(reading),
    )
    captured = list(match.groups()) if match else []
    return [
        (
            start,
            end,
            captured[index]
            if index < len(captured) and captured[index]
            else normalize_reading(surface[start:end]),
        )
        for index, (start, end) in enumerate(runs)
    ]


def ruby_placements(
    line: AlignedLine,
    *,
    play_res_x: int,
    baseline_y: int,
    base_font_size: int,
    ruby_font_size: int = 48,
    char_width_ratio: float = 0.68,
    center_x: int | None = None,
    measure: Callable[[str], float] | None = None,
) -> list[RubyPlacement]:
    """Where each reading goes, centred above its kanji.

    `measure` gives the rendered width of a piece of the line at the base
    font size.  Without it widths are estimated from the font size, which is
    only right for fonts whose glyphs are about 0.68 of it wide.
    """
    if measure is None:
        char_width = round(base_font_size * char_width_ratio)

        def measure(text: str) -> float:
            return text_width_units(text) * char_width

    line_left = (center_x or play_res_x / 2) - measure(line.surface) / 2
    placements: list[RubyPlacement] = []
    consumed = ""
    for token in line.tokens:
        for run_start, run_end, reading in kanji_readings(
            token.surface,
            token.reading,
        ):
            # Measured from the start of the line rather than added up word
            # by word, so rounding and kerning do not accumulate.
            before = measure(consumed + token.surface[:run_start])
            run = measure(token.surface[run_start:run_end])
            placements.append(
                RubyPlacement(
                    text=reading,
                    x=round(line_left + before + run / 2),
                    y=baseline_y - base_font_size // 2 - 2,
                )
            )
        consumed += token.surface
    return placements
