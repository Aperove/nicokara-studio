from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from app.alignment.editing import retime_line
from app.alignment.models import AlignedLine, LyricTimeline


Rest = tuple[int, int]

_FRAME_MS = 50
# A median over ~half a second ignores breaths and clicks.
_SMOOTHING_FRAMES = 11
# "Quiet" is judged against how loud this song's own singing is.
_LOUD_PERCENTILE = 80
_QUIET_BELOW_LOUD_DB = 5.0
# Only a long silence is certain to fall between two lyric lines.
MIN_REST_MS = 2_000
# A stem whose quiet parts are not clearly quieter than its singing still
# carries accompaniment, and its "rests" cannot be trusted.
_MIN_DYNAMIC_RANGE_DB = 8.0
# Soft phrase onsets and endings sit below the threshold, so the edges of a
# detected rest are fuzzy: a line has to reach well inside to count as caught.
_EDGE_MARGIN_MS = 500
_MIN_CAUGHT_MS = 500
# How many neighbouring lines may be re-spread to make room.
_MAX_NEIGHBOURS = 2
# A slow song breathes for seconds between the phrases of one lyric line.
# Such a line only dips into the rest; a line timed where nobody sings has
# most of its length in it.  (Measured: 8-30% for pauses, 59-84% for lines
# that really were misplaced.)
_MIN_CAUGHT_SHARE = 0.4
# Milliseconds per mora between which a line can plausibly be sung.
_SINGABLE_PACE_MS = (90, 900)


def detect_rests(audio_path: Path, *, min_rest_ms: int = MIN_REST_MS) -> list[Rest]:
    """Stretches of an isolated vocal stem in which nobody sings.

    Returns an empty list when the stem is not clean enough to tell.
    """
    import numpy as np
    import soundfile as sf
    from scipy.ndimage import median_filter

    wave, sample_rate = sf.read(audio_path, dtype="float32")
    if wave.ndim > 1:
        wave = wave.mean(axis=1)
    frame = int(sample_rate * _FRAME_MS / 1000)
    count = len(wave) // frame
    if count < _SMOOTHING_FRAMES:
        return []
    frames = wave[: count * frame].reshape(count, frame)
    level = 20 * np.log10(np.sqrt((frames**2).mean(axis=1)) + 1e-6)
    level = median_filter(level, size=_SMOOTHING_FRAMES)

    loud = float(np.percentile(level, _LOUD_PERCENTILE))
    if loud - float(np.percentile(level, 30)) < _MIN_DYNAMIC_RANGE_DB:
        return []
    quiet = level <= loud - _QUIET_BELOW_LOUD_DB

    rests: list[Rest] = []
    start: int | None = None
    for index, is_quiet in enumerate([*quiet, False]):
        if is_quiet and start is None:
            start = index
        elif not is_quiet and start is not None:
            if (index - start) * _FRAME_MS >= min_rest_ms:
                rests.append((start * _FRAME_MS, index * _FRAME_MS))
            start = None
    return rests


def _mora_count(line: AlignedLine) -> int:
    return max(1, sum(len(token.moras) for token in line.tokens))


def _typical_pace(lines: list[AlignedLine]) -> float:
    """Milliseconds per mora at which this song is usually sung."""
    paces = sorted(
        pace
        for pace in (
            (line.end_ms - line.start_ms) / _mora_count(line) for line in lines
        )
        if _SINGABLE_PACE_MS[0] <= pace <= _SINGABLE_PACE_MS[1]
    )
    return paces[len(paces) // 2] if paces else 250.0


def _overlap(line: AlignedLine, rest: Rest) -> int:
    return max(0, min(line.end_ms, rest[1]) - max(line.start_ms, rest[0]))


def _is_caught(line: AlignedLine, core: Rest) -> bool:
    overlap = _overlap(line, core)
    return overlap >= _MIN_CAUGHT_MS and overlap >= _MIN_CAUGHT_SHARE * (
        line.end_ms - line.start_ms
    )


def move_lines_out_of_rests(
    timeline: LyricTimeline,
    rests: list[Rest],
    *,
    duration_ms: int,
) -> tuple[LyricTimeline, list[int], list[int]]:
    """Re-place lyric lines that were timed where nobody sings.

    Lines caught in a rest are handed to the sung time before or after it,
    whichever split keeps the singing pace most even, and spread there in
    proportion to their length.  A line that merely pauses for a rest, with
    most of its length sung outside it, is left alone.

    Returns the new timeline, the indexes that moved, and the indexes that
    are still inside a rest because no plausible place was found for them.
    """
    lines = list(timeline.lines)
    moved: list[int] = []
    unresolved: list[int] = []
    pace = _typical_pace(lines)
    for rest in rests:
        core = (rest[0] + _EDGE_MARGIN_MS, rest[1] - _EDGE_MARGIN_MS)
        stuck = [
            index
            for index, line in enumerate(lines)
            if _is_caught(line, core)
        ]
        if not stuck:
            continue
        # A neighbour parked right at the edge of the rest takes the room the
        # stuck lines need, so neighbours join the group until they all fit.
        placed = False
        for widen in range(_MAX_NEIGHBOURS + 1):
            for grow_before, grow_after in _growth_options(widen):
                group_first = max(0, stuck[0] - grow_before)
                group_last = min(len(lines) - 1, stuck[-1] + grow_after)
                # a neighbour may only join from its own side of the rest
                if any(
                    lines[index].start_ms < rest[0]
                    for index in range(stuck[-1] + 1, group_last + 1)
                ) or any(
                    lines[index].end_ms > rest[1]
                    for index in range(group_first, stuck[0])
                ):
                    continue
                caught = list(range(group_first, group_last + 1))
                if _place_around_rest(
                    lines, caught, stuck, rest, pace, duration_ms, moved
                ):
                    placed = True
                    break
            if placed:
                break
        if not placed:
            unresolved.extend(stuck)
    return (
        replace(timeline, lines=lines),
        sorted(set(moved)),
        sorted(set(unresolved)),
    )


def _growth_options(widen: int) -> list[tuple[int, int]]:
    """Ways to add `widen` neighbouring lines, later ones first."""
    return [(widen - after, after) for after in range(widen, -1, -1)]


def _place_around_rest(
    lines: list[AlignedLine],
    caught: list[int],
    stuck: list[int],
    rest: Rest,
    pace: float,
    duration_ms: int,
    moved: list[int],
) -> bool:
    first, last = caught[0], caught[-1]
    # Lines only brushing the rest with a long tail or head stay put;
    # those are trimmed rather than moved.
    before_floor = lines[first - 1].end_ms if first > 0 else 0
    after_ceiling = (
        lines[last + 1].start_ms if last + 1 < len(lines) else duration_ms
    )
    counts = [_mora_count(lines[index]) for index in caught]

    best_split, best_cost = 0, float("inf")
    best_bounds = (rest[0], rest[1])
    # Neighbours that joined from before the rest stay before it, and
    # those from after it stay after it; only the stuck lines may switch.
    lowest_split = stuck[0] - first
    highest_split = stuck[-1] - first + 1
    for split in range(lowest_split, highest_split + 1):
        before, after = counts[:split], counts[split:]
        # Sung time next to the rest: what the caught lines already reach,
        # or, for lines lying wholly inside the rest, as much as they
        # need at the song's typical pace.
        before_start = max(
            before_floor,
            min(lines[first].start_ms, rest[0] - round(sum(before) * pace)),
        )
        after_end = min(
            after_ceiling,
            max(lines[last].end_ms, rest[1] + round(sum(after) * pace)),
        )
        room_before = rest[0] - before_start if before else 0
        room_after = after_end - rest[1] if after else 0
        if (before and room_before < 200 * len(before)) or (
            after and room_after < 200 * len(after)
        ):
            continue
        paces = []
        if before:
            paces.append(room_before / sum(before))
        if after:
            paces.append(room_after / sum(after))
        # Never squeeze or stretch lines to a pace nobody could sing, not
        # even to make room: such a line is better left for a person.
        if any(
            sung < _SINGABLE_PACE_MS[0] or sung > _SINGABLE_PACE_MS[1]
            for sung in paces
        ):
            continue
        # Prefer an even pace on both sides of the rest.
        cost = max(paces) / max(1.0, min(paces))
        if cost < best_cost:
            best_split, best_cost = split, cost
            best_bounds = (before_start, after_end)
    if best_cost == float("inf"):
        return False

    def spread(indexes: list[int], start_ms: int, end_ms: int) -> None:
        total = sum(_mora_count(lines[index]) for index in indexes)
        cursor = float(start_ms)
        for index in indexes:
            length = (end_ms - start_ms) * _mora_count(lines[index]) / total
            new_start = round(cursor)
            new_end = max(new_start + 1, round(cursor + length))
            if (new_start, new_end) != (
                lines[index].start_ms,
                lines[index].end_ms,
            ):
                lines[index] = retime_line(lines[index], new_start, new_end)
                moved.append(index)
            cursor += length

    before_indexes = caught[:best_split]
    after_indexes = caught[best_split:]
    if before_indexes:
        spread(before_indexes, best_bounds[0], rest[0])
    if after_indexes:
        spread(after_indexes, rest[1], best_bounds[1])
    return True
