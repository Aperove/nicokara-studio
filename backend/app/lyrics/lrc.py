from __future__ import annotations

import re
from dataclasses import dataclass


# [mm:ss], [mm:ss.xx], [mm:ss.xxx] and the [mm:ss:xx] variant some tools write
_TIME_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
# enhanced LRC marks words inside a line: <mm:ss.xx>
_WORD_TAG = re.compile(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>")
# [ar:...], [ti:...], [offset:...] and friends
_META_TAG = re.compile(r"^\[([A-Za-z#][A-Za-z0-9_]*):(.*)\]$")


@dataclass(frozen=True)
class ParsedLyrics:
    """Plain lyric text and, for LRC input, when each line starts."""

    text: str
    line_starts_ms: list[int] | None


def _milliseconds(minutes: str, seconds: str, fraction: str | None) -> int:
    total = int(minutes) * 60_000 + int(seconds) * 1_000
    if fraction:
        total += round(int(fraction) * 1000 / 10 ** len(fraction))
    return total


def parse_lyrics(text: str) -> ParsedLyrics:
    """Accept plain lyrics or LRC.

    LRC is recognised by its line timestamps.  Its tags are removed, lines
    carrying several timestamps (a repeated chorus) are written out once per
    timestamp, and everything is put in time order.  The start times are only
    line-level and often a little early, so they serve as a guide, never as
    the final timing.
    """
    timed: list[tuple[int, int, str]] = []
    offset_ms = 0
    saw_untimed_text = False
    for order, raw in enumerate(text.splitlines()):
        line = raw.strip().lstrip("﻿")
        if not line:
            continue
        meta = _META_TAG.fullmatch(line)
        if meta and not _TIME_TAG.match(line):
            if meta.group(1).lower() == "offset":
                try:
                    offset_ms = int(meta.group(2).strip())
                except ValueError:
                    offset_ms = 0
            continue
        tags = []
        rest = line
        while True:
            match = _TIME_TAG.match(rest)
            if not match:
                break
            tags.append(_milliseconds(*match.groups()))
            rest = rest[match.end() :].lstrip()
        if not tags:
            saw_untimed_text = True
            continue
        content = _WORD_TAG.sub("", rest).strip()
        if not content:
            continue  # a timestamp with no words marks an interlude
        timed.extend((stamp, order, content) for stamp in tags)

    # Plain lyrics, or a file that merely contains a stray bracket.
    if len(timed) < 2 or saw_untimed_text:
        return ParsedLyrics(text=text, line_starts_ms=None)

    timed.sort()
    return ParsedLyrics(
        text="\n".join(content for _, _, content in timed),
        # A positive [offset] means the lyrics should appear earlier.
        line_starts_ms=[max(0, stamp - offset_ms) for stamp, _, _ in timed],
    )
