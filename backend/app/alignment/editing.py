from __future__ import annotations

from dataclasses import replace

from app.alignment.models import (
    AlignedLine,
    AlignedMora,
    AlignedToken,
    LyricTimeline,
)


MANUALLY_EDITED = "manually_edited"


class TimelineEditError(ValueError):
    """Raised when requested line timings cannot form a valid timeline."""


def retime_line(line: AlignedLine, start_ms: int, end_ms: int) -> AlignedLine:
    """Move a line to a new window, keeping the rhythm inside it.

    Every token and mora keeps its relative position; a line that had no
    duration at all is spread evenly over its moras instead.
    """
    if end_ms <= start_ms:
        raise TimelineEditError("A line must end after it starts")
    old_span = line.end_ms - line.start_ms
    new_span = end_ms - start_ms
    mora_total = sum(len(token.moras) for token in line.tokens)

    def scale(value: int) -> int:
        return start_ms + round((value - line.start_ms) * new_span / old_span)

    tokens: list[AlignedToken] = []
    mora_offset = 0
    for token in line.tokens:
        moras: list[AlignedMora] = []
        for mora in token.moras:
            if old_span > 0:
                mora_start, mora_end = scale(mora.start_ms), scale(mora.end_ms)
            else:
                mora_start = start_ms + new_span * mora_offset // mora_total
                mora_end = start_ms + new_span * (mora_offset + 1) // mora_total
            mora_offset += 1
            moras.append(replace(mora, start_ms=mora_start, end_ms=mora_end))
        if moras:
            token_start, token_end = moras[0].start_ms, moras[-1].end_ms
        elif old_span > 0:
            token_start, token_end = scale(token.start_ms), scale(token.end_ms)
        else:
            token_start = token_end = tokens[-1].end_ms if tokens else start_ms
        tokens.append(
            replace(token, start_ms=token_start, end_ms=token_end, moras=moras)
        )
    return replace(line, start_ms=start_ms, end_ms=end_ms, tokens=tokens)


def apply_line_edits(
    timeline: LyricTimeline,
    edits: dict[int, tuple[int, int]],
    *,
    duration_ms: int | None = None,
) -> LyricTimeline:
    """Return a timeline with the given lines moved to new windows."""
    lines = list(timeline.lines)
    for index, (start_ms, end_ms) in edits.items():
        if not 0 <= index < len(lines):
            raise TimelineEditError(f"Line {index} does not exist")
        if start_ms < 0 or (duration_ms is not None and end_ms > duration_ms):
            raise TimelineEditError(f"Line {index} is outside the song")
        lines[index] = retime_line(lines[index], start_ms, end_ms)
    for index in range(1, len(lines)):
        previous, current = lines[index - 1], lines[index]
        if current.start_ms <= previous.start_ms:
            raise TimelineEditError(
                f"Line {index} must start after line {index - 1}"
            )
        if previous.end_ms > current.start_ms:
            # Lines are sung one after another: a late ending gives way.
            lines[index - 1] = retime_line(
                previous, previous.start_ms, current.start_ms
            )
    warnings = list(timeline.warnings)
    if MANUALLY_EDITED not in warnings:
        warnings.append(MANUALLY_EDITED)
    return replace(timeline, lines=lines, warnings=warnings)


def trim_overlaps(timeline: LyricTimeline) -> LyricTimeline:
    """Lines are sung one after another: a late ending gives way."""
    lines = list(timeline.lines)
    for index in range(1, len(lines)):
        previous, current = lines[index - 1], lines[index]
        if previous.start_ms < current.start_ms < previous.end_ms:
            lines[index - 1] = retime_line(
                previous, previous.start_ms, current.start_ms
            )
    return replace(timeline, lines=lines)


def replace_line(
    timeline: LyricTimeline,
    index: int,
    line: AlignedLine,
) -> LyricTimeline:
    lines = list(timeline.lines)
    lines[index] = line
    return replace(timeline, lines=lines)
