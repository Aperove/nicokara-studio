from __future__ import annotations

from dataclasses import replace

from app.alignment.editing import MANUALLY_EDITED
from app.alignment.japanese import normalize_reading, split_moras
from app.alignment.models import AlignedMora, LyricTimeline
from app.lyrics.models import LyricDocument


_MAX_READING_LENGTH = 64
_EXTRA_KANA = "ーゝゞヽヾ・"


class ReadingEditError(ValueError):
    """Raised when a corrected reading cannot be applied."""


def _is_kana(character: str) -> bool:
    return (
        "ぁ" <= character <= "ゖ"  # hiragana
        or "ァ" <= character <= "ヺ"  # katakana
        or character in _EXTRA_KANA
    )


def clean_reading(reading: str) -> str:
    """A reading is written in kana only; anything else is a typing slip."""
    cleaned = "".join(reading.split())
    if not cleaned or len(cleaned) > _MAX_READING_LENGTH:
        raise ReadingEditError("a reading must be 1 to 64 kana long")
    if not all(_is_kana(character) for character in cleaned):
        raise ReadingEditError("a reading may only contain kana")
    return cleaned


def apply_reading_edits(
    lyrics: LyricDocument,
    timeline: LyricTimeline,
    edits: dict[tuple[int, int], str],
) -> tuple[LyricDocument, LyricTimeline, list[int]]:
    """Correct token readings in the lyrics and in the timeline.

    A wrong reading shows the wrong ruby text and, because alignment works
    on moras, also skews the rhythm inside the token.  The corrected token
    keeps its time span; its moras are rebuilt from the new reading and
    spread evenly, to be refreshed by re-aligning the line if desired.
    Returns the new documents and the indexes of the lines that changed.
    """
    if len(lyrics.lines) != len(timeline.lines):
        raise ReadingEditError("lyrics and timeline do not describe the same lines")
    lyric_lines = list(lyrics.lines)
    timed_lines = list(timeline.lines)
    changed: set[int] = set()
    for (line_index, token_index), reading in edits.items():
        if not 0 <= line_index < len(lyric_lines):
            raise ReadingEditError(f"line {line_index} does not exist")
        lyric_line, timed_line = lyric_lines[line_index], timed_lines[line_index]
        if not 0 <= token_index < len(lyric_line.tokens) or len(
            lyric_line.tokens
        ) != len(timed_line.tokens):
            raise ReadingEditError(
                f"token {token_index} of line {line_index} does not exist"
            )
        reading = clean_reading(reading)
        if lyric_line.tokens[token_index].reading == reading:
            continue

        lyric_tokens = list(lyric_line.tokens)
        lyric_tokens[token_index] = replace(lyric_tokens[token_index], reading=reading)
        lyric_lines[line_index] = replace(
            lyric_line,
            tokens=lyric_tokens,
            reading="".join(token.reading for token in lyric_tokens),
        )

        timed_token = timed_line.tokens[token_index]
        moras = split_moras(normalize_reading(reading))
        span = timed_token.end_ms - timed_token.start_ms
        timed_tokens = list(timed_line.tokens)
        timed_tokens[token_index] = replace(
            timed_token,
            reading=reading,
            moras=[
                AlignedMora(
                    reading=mora,
                    start_ms=timed_token.start_ms + span * position // len(moras),
                    end_ms=timed_token.start_ms + span * (position + 1) // len(moras),
                    # heard by nobody: timed by spreading over the token
                    matched=False,
                    confidence=0.0,
                )
                for position, mora in enumerate(moras)
            ],
        )
        timed_lines[line_index] = replace(
            timed_line,
            tokens=timed_tokens,
            reading="".join(token.reading for token in timed_tokens),
        )
        changed.add(line_index)

    if not changed:
        return lyrics, timeline, []
    warnings = list(timeline.warnings)
    if MANUALLY_EDITED not in warnings:
        warnings.append(MANUALLY_EDITED)
    return (
        replace(lyrics, lines=lyric_lines),
        replace(timeline, lines=timed_lines, warnings=warnings),
        sorted(changed),
    )
