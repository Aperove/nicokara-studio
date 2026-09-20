from __future__ import annotations

from dataclasses import dataclass

from app.ai.whisper import TranscriptDocument
from app.alignment.japanese import normalize_reading, split_moras
from app.alignment.models import (
    AlignedLine,
    AlignedMora,
    AlignedToken,
    LyricTimeline,
)
from app.lyrics.models import LyricDocument


@dataclass(frozen=True)
class _TargetMora:
    line_index: int
    token_index: int
    reading: str


@dataclass(frozen=True)
class _TimedMora:
    reading: str
    start_ms: int
    end_ms: int
    # False when Whisper's word timing collapsed (many words stamped at one
    # instant, common on sung audio): the text is usable, the time is not.
    reliable: bool = True


class AlignmentQualityError(ValueError):
    """Raised when audio-derived anchors are insufficient for a timeline."""


# Global alignment scores.  Whisper returns a handful of ~30 s segments for
# sung audio, so lyric lines cannot be paired with segments; instead the whole
# lyric mora sequence is aligned against the whole transcript mora sequence.
_MATCH = 2.0
_NEAR_MATCH = 1.0
_MISMATCH = -0.5
_SKIP_LYRIC = 0.6
# Skipping transcript material inside the song costs a little per mora, so a
# nearby imperfect rendition beats a distant exact repeat.  Material before
# the first and after the last lyric (speech, outro) is free.
_SKIP_TRANSCRIPT = 0.25

_DIAGONAL, _UP, _LEFT = 0, 1, 2

# Kana that ASR routinely interchanges when transcribing singing.
_CANONICAL = str.maketrans({"を": "お", "づ": "ず", "ぢ": "じ", "ゔ": "ぶ"})
_NEAR_PAIRS = frozenset(
    {
        frozenset({"は", "わ"}),
        frozenset({"へ", "え"}),
        frozenset({"う", "お"}),
        frozenset({"い", "え"}),
    }
)
_VOWELS = frozenset("あいうえお")

# Unmatched moras are laid out at the song's typical pace and may stretch a
# little to fill a gap, but never across a whole interlude.
_MAX_STRETCH = 1.6
_SOFT_ANCHOR_REACH = 3
# A sung mora shorter than this means the word timestamps collapsed.
_MIN_RELIABLE_MORA_MS = 40
# Anchors of one lyric line further apart than this cannot both be right.
_MAX_GAP_WITHIN_LINE_MS = 8000


class LyricTimelineAligner:
    def align(
        self,
        lyrics: LyricDocument,
        transcript: TranscriptDocument,
    ) -> LyricTimeline:
        targets = self._lyric_moras(lyrics)
        observations = self._transcript_moras(transcript)
        if not observations:
            raise AlignmentQualityError("No ASR word timestamps were detected")

        pairs = self._global_alignment(targets, observations)
        matches = {
            target_index: observation_index
            for target_index, observation_index, exact in pairs
            if exact
        }
        match_ratio = len(matches) / len(targets) if targets else 0.0
        if match_ratio < 0.15:
            raise AlignmentQualityError(
                "Audio-to-lyrics match is insufficient for a reliable timeline"
            )
        soft_anchors = self._soft_anchors(pairs, matches)
        aligned_moras = self._align_moras(
            targets,
            observations,
            matches,
            soft_anchors,
            round(transcript.duration_seconds * 1000),
        )
        confidence = match_ratio

        counts: dict[tuple[int, int], int] = {}
        for target in targets:
            key = (target.line_index, target.token_index)
            counts[key] = counts.get(key, 0) + 1

        lines: list[AlignedLine] = []
        mora_offset = 0
        for line_index, lyric_line in enumerate(lyrics.lines):
            tokens: list[AlignedToken] = []
            for token_index, lyric_token in enumerate(lyric_line.tokens):
                count = counts.get((line_index, token_index), 0)
                token_moras = aligned_moras[mora_offset : mora_offset + count]
                mora_offset += count
                if token_moras:
                    start_ms = token_moras[0].start_ms
                    end_ms = token_moras[-1].end_ms
                    token_confidence = self._confidence(token_moras)
                else:
                    anchor_ms = (
                        tokens[-1].end_ms
                        if tokens
                        else (
                            aligned_moras[mora_offset].start_ms
                            if mora_offset < len(aligned_moras)
                            else 0
                        )
                    )
                    start_ms = anchor_ms
                    end_ms = anchor_ms
                    token_confidence = 1.0
                tokens.append(
                    AlignedToken(
                        surface=lyric_token.surface,
                        reading=lyric_token.reading,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        confidence=token_confidence,
                        moras=token_moras,
                    )
                )
            lines.append(
                AlignedLine(
                    surface=lyric_line.surface,
                    reading=lyric_line.reading,
                    start_ms=tokens[0].start_ms,
                    end_ms=tokens[-1].end_ms,
                    confidence=sum(token.confidence for token in tokens) / len(tokens),
                    tokens=tokens,
                )
            )

        warnings = [] if confidence == 1.0 else ["partial_alignment"]
        return LyricTimeline(
            confidence=confidence,
            lines=lines,
            warnings=warnings,
        )

    @staticmethod
    def _lyric_moras(lyrics: LyricDocument) -> list[_TargetMora]:
        return [
            _TargetMora(line_index, token_index, mora)
            for line_index, line in enumerate(lyrics.lines)
            for token_index, token in enumerate(line.tokens)
            for mora in split_moras(normalize_reading(token.reading))
        ]

    @staticmethod
    def _transcript_moras(transcript: TranscriptDocument) -> list[_TimedMora]:
        result: list[_TimedMora] = []
        for segment in transcript.segments:
            for word in segment.words:
                moras = split_moras(normalize_reading(word.text))
                if not moras:
                    continue
                duration = word.end_ms - word.start_ms
                reliable = duration / len(moras) > _MIN_RELIABLE_MORA_MS
                for index, mora in enumerate(moras):
                    raw_start_ms = (
                        word.start_ms + duration * index // len(moras)
                    )
                    raw_end_ms = (
                        word.start_ms
                        + duration * (index + 1) // len(moras)
                    )
                    start_ms = max(
                        raw_start_ms,
                        result[-1].end_ms if result else raw_start_ms,
                    )
                    result.append(
                        _TimedMora(
                            reading=mora,
                            start_ms=start_ms,
                            end_ms=max(start_ms, raw_end_ms),
                            reliable=reliable,
                        )
                    )
        return result

    @staticmethod
    def _similarity(lyric: str, heard: str) -> float:
        left = lyric.translate(_CANONICAL)
        right = heard.translate(_CANONICAL)
        if left == right:
            return _MATCH
        if frozenset({left, right}) in _NEAR_PAIRS:
            return _NEAR_MATCH
        # A long-vowel mark stands for whichever vowel was actually sung.
        if "ー" in (left, right) and (left in _VOWELS or right in _VOWELS):
            return _NEAR_MATCH
        return _MISMATCH

    @classmethod
    def _global_alignment(
        cls,
        targets: list[_TargetMora],
        observations: list[_TimedMora],
    ) -> list[tuple[int, int, bool]]:
        """Monotonic alignment of all lyric moras against all heard moras.

        Returns (target_index, observation_index, exact) for every lyric mora
        that was paired with a heard mora.
        """
        target_count = len(targets)
        observation_count = len(observations)
        if not target_count or not observation_count:
            return []
        lyric_readings = [target.reading for target in targets]
        heard_readings = [observation.reading for observation in observations]

        previous = [0.0] * (observation_count + 1)
        moves: list[bytearray] = [bytearray(observation_count + 1)]
        for row in range(1, target_count + 1):
            lyric = lyric_readings[row - 1]
            current = [previous[0] - _SKIP_LYRIC] + [0.0] * observation_count
            row_moves = bytearray(observation_count + 1)
            row_moves[0] = _UP
            for column in range(1, observation_count + 1):
                best = previous[column - 1] + cls._similarity(
                    lyric, heard_readings[column - 1]
                )
                move = _DIAGONAL
                up = previous[column] - _SKIP_LYRIC
                if up > best:
                    best, move = up, _UP
                left = current[column - 1] - _SKIP_TRANSCRIPT
                if left > best:
                    best, move = left, _LEFT
                current[column] = best
                row_moves[column] = move
            moves.append(row_moves)
            previous = current

        # Trailing transcript material is free: end wherever scores best.
        column = max(
            range(observation_count + 1),
            key=lambda candidate: previous[candidate],
        )
        row = target_count
        pairs: list[tuple[int, int, bool]] = []
        while row > 0 and column > 0:
            move = moves[row][column]
            if move == _DIAGONAL:
                score = cls._similarity(
                    lyric_readings[row - 1], heard_readings[column - 1]
                )
                pairs.append((row - 1, column - 1, score > 0))
                row -= 1
                column -= 1
            elif move == _UP:
                row -= 1
            else:
                column -= 1
        pairs.reverse()
        return pairs

    @staticmethod
    def _soft_anchors(
        pairs: list[tuple[int, int, bool]],
        matches: dict[int, int],
    ) -> dict[int, int]:
        """Misheard moras that are pinned between nearby exact matches.

        Their heard time is still the best estimate of when they were sung.
        """
        soft: dict[int, int] = {}
        for target_index, observation_index, exact in pairs:
            if exact:
                continue
            before = any(
                target_index - offset in matches
                for offset in range(1, _SOFT_ANCHOR_REACH + 1)
            )
            after = any(
                target_index + offset in matches
                for offset in range(1, _SOFT_ANCHOR_REACH + 1)
            )
            if before and after:
                soft[target_index] = observation_index
        return soft

    @staticmethod
    def _median_mora_duration(observations: list[_TimedMora]) -> int:
        durations = sorted(
            o.end_ms - o.start_ms
            for o in observations
            if o.reliable and o.end_ms > o.start_ms
        )
        return durations[len(durations) // 2] if durations else 200

    @classmethod
    def _align_moras(
        cls,
        targets: list[_TargetMora],
        observations: list[_TimedMora],
        matches: dict[int, int],
        soft_anchors: dict[int, int],
        duration_ms: int,
    ) -> list[AlignedMora]:
        aligned: list[AlignedMora | None] = [None] * len(targets)
        for anchors, matched in ((matches, True), (soft_anchors, False)):
            for target_index, observation_index in anchors.items():
                observation = observations[observation_index]
                if not observation.reliable:
                    continue
                aligned[target_index] = AlignedMora(
                    reading=targets[target_index].reading,
                    start_ms=observation.start_ms,
                    end_ms=observation.end_ms,
                    matched=matched,
                    confidence=1.0 if matched else 0.5,
                )

        cls._drop_implausible_anchors(targets, aligned)
        pace = cls._median_mora_duration(observations)
        position = 0
        while position < len(targets):
            if aligned[position] is not None:
                position += 1
                continue
            run_start = position
            while position < len(targets) and aligned[position] is None:
                position += 1
            cls._fill_run(
                targets,
                aligned,
                run_start,
                position,
                pace,
                duration_ms,
            )

        # Heard, but timed by interpolation because the ASR time collapsed.
        for target_index in matches:
            mora = aligned[target_index]
            if mora is not None and not mora.matched:
                aligned[target_index] = AlignedMora(
                    reading=mora.reading,
                    start_ms=mora.start_ms,
                    end_ms=mora.end_ms,
                    matched=True,
                    confidence=0.5,
                )

        normalized: list[AlignedMora] = []
        for mora in aligned:
            assert mora is not None
            start_ms = max(
                mora.start_ms,
                normalized[-1].end_ms if normalized else mora.start_ms,
            )
            normalized.append(
                AlignedMora(
                    reading=mora.reading,
                    start_ms=start_ms,
                    end_ms=max(start_ms, mora.end_ms),
                    matched=mora.matched,
                    confidence=mora.confidence,
                )
            )
        return normalized

    @staticmethod
    def _drop_implausible_anchors(
        targets: list[_TargetMora],
        aligned: list[AlignedMora | None],
    ) -> None:
        """Keep each line's anchors within one plausible sung phrase.

        When the anchors of a single line straddle a long silence, the side
        with fewer anchors is a stray match (often a later repeat) and is
        released so it gets timed next to the rest of its line.
        """
        by_line: dict[int, list[int]] = {}
        for index, target in enumerate(targets):
            if aligned[index] is not None:
                by_line.setdefault(target.line_index, []).append(index)
        for indexes in by_line.values():
            while len(indexes) > 1:
                gaps = [
                    aligned[right].start_ms - aligned[left].end_ms
                    for left, right in zip(indexes, indexes[1:])
                ]
                widest = max(range(len(gaps)), key=gaps.__getitem__)
                if gaps[widest] <= _MAX_GAP_WITHIN_LINE_MS:
                    break
                before, after = indexes[: widest + 1], indexes[widest + 1 :]
                dropped, indexes = (
                    (before, after) if len(before) < len(after) else (after, before)
                )
                for index in dropped:
                    aligned[index] = None

    @staticmethod
    def _fill_run(
        targets: list[_TargetMora],
        aligned: list[AlignedMora | None],
        run_start: int,
        run_end: int,
        pace: int,
        duration_ms: int,
    ) -> None:
        """Time the unanchored moras in [run_start, run_end).

        Moras that share a line with a neighbouring anchor hug that anchor;
        whole unanchored lines are spread through the remaining gap at the
        song's typical pace, so every line keeps a visible karaoke sweep.
        """
        previous = aligned[run_start - 1] if run_start > 0 else None
        following = aligned[run_end] if run_end < len(targets) else None

        pieces: list[list[int]] = []
        for index in range(run_start, run_end):
            if (
                pieces
                and targets[pieces[-1][-1]].line_index
                == targets[index].line_index
            ):
                pieces[-1].append(index)
            else:
                pieces.append([index])

        def place(indexes: list[int], start_ms: float, end_ms: float) -> None:
            span = max(0.0, end_ms - start_ms)
            for offset, index in enumerate(indexes):
                aligned[index] = AlignedMora(
                    reading=targets[index].reading,
                    start_ms=round(start_ms + span * offset / len(indexes)),
                    end_ms=round(start_ms + span * (offset + 1) / len(indexes)),
                    matched=False,
                    confidence=0.0,
                )

        if previous is None and following is None:
            cursor = 0.0
            for piece in pieces:
                place(piece, cursor, cursor + len(piece) * pace)
                cursor += len(piece) * pace
            return

        if previous is None:
            assert following is not None
            cursor = float(following.start_ms)
            for piece in reversed(pieces):
                start_ms = max(0.0, cursor - len(piece) * pace)
                place(piece, start_ms, cursor)
                cursor = start_ms
            return

        if following is None:
            cursor = float(previous.end_ms)
            limit = float(max(duration_ms, previous.end_ms))
            for piece in pieces:
                end_ms = min(limit, cursor + len(piece) * pace)
                place(piece, cursor, end_ms)
                cursor = end_ms
            return

        gap_start = float(previous.end_ms)
        gap_end = float(max(previous.end_ms, following.start_ms))
        gap = gap_end - gap_start
        count = run_end - run_start
        natural = count * pace

        if len(pieces) == 1 or natural >= gap:
            # One phrase between two anchors, or no slack to distribute:
            # share the gap evenly, without stretching a phrase over a rest.
            same_line = (
                targets[run_start - 1].line_index
                == targets[run_end].line_index
            )
            if len(pieces) == 1 and not same_line and natural * _MAX_STRETCH < gap:
                piece = pieces[0]
                length = natural * _MAX_STRETCH
                if (
                    targets[piece[0]].line_index
                    == targets[run_start - 1].line_index
                ):
                    place(piece, gap_start, gap_start + length)
                elif (
                    targets[piece[-1]].line_index
                    == targets[run_end].line_index
                ):
                    place(piece, gap_end - length, gap_end)
                else:
                    middle = (gap_start + gap_end) / 2
                    place(piece, middle - length / 2, middle + length / 2)
                return
            cursor = gap_start
            for piece in pieces:
                end_ms = cursor + gap * len(piece) / count
                place(piece, cursor, end_ms)
                cursor = end_ms
            return

        head = (
            pieces[0]
            if targets[pieces[0][0]].line_index
            == targets[run_start - 1].line_index
            else None
        )
        tail = (
            pieces[-1]
            if targets[pieces[-1][-1]].line_index
            == targets[run_end].line_index
            else None
        )
        middle_pieces = pieces[
            (1 if head is not None else 0) : (
                len(pieces) - 1 if tail is not None else len(pieces)
            )
        ]
        if head is not None:
            place(head, gap_start, gap_start + len(head) * pace)
            gap_start += len(head) * pace
        if tail is not None:
            place(tail, gap_end - len(tail) * pace, gap_end)
            gap_end -= len(tail) * pace
        if not middle_pieces:
            return
        middle_natural = sum(len(piece) for piece in middle_pieces) * pace
        stretch = min(
            _MAX_STRETCH,
            max(1.0, (gap_end - gap_start) / max(1, middle_natural)),
        )
        slack = max(0.0, (gap_end - gap_start) - middle_natural * stretch)
        rest = slack / (len(middle_pieces) + 1)
        cursor = gap_start + rest
        for piece in middle_pieces:
            end_ms = cursor + len(piece) * pace * stretch
            place(piece, cursor, end_ms)
            cursor = end_ms + rest

    @staticmethod
    def _confidence(moras: list[AlignedMora]) -> float:
        return (
            sum(1 for mora in moras if mora.matched) / len(moras)
            if moras
            else 0.0
        )
