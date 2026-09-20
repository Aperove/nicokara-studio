from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from app.ai.whisper import TranscriptDocument, TranscriptSegment, TranscriptWord
from app.alignment.editing import replace_line, retime_line
from app.alignment.models import AlignedLine, LyricTimeline
from app.lyrics.models import LyricDocument


logger = logging.getLogger(__name__)

WORKER_PATH = Path(__file__).with_name("qwen_worker.py")

# A forced aligner drifts on a whole song but is accurate on short
# excerpts, so the coarse timeline decides which lines share an excerpt.
_TARGET_CHUNK_MS = 30_000
_MAX_CHUNK_MS = 60_000
_LONG_REST_MS = 6_000
_PAD_MS = 1_000
_TAIL_PAD_MS = 4_000
_SOLID_LINE_RATIO = 0.75
# Slack after a hand-picked line window: phrase endings are marked roughly.
# There is deliberately none before it: the model pins the first word of an
# excerpt to the excerpt's start, which is exactly where the person put it.
_LINE_TAIL_PAD_MS = 300


# A re-aligned line may end slightly past the window it was given.
_REALIGN_SLACK_MS = 300
_MIN_REALIGNED_CONFIDENCE = 0.6


class ForcedAlignmentError(RuntimeError):
    """Raised when the external forced aligner cannot produce timings."""


@dataclass(frozen=True)
class AlignmentChunk:
    start_ms: int
    end_ms: int
    line_indexes: tuple[int, ...]


def is_solid(line: AlignedLine) -> bool:
    """True when the coarse timing of a line was actually heard by ASR."""
    moras = [mora for token in line.tokens for mora in token.moras]
    if not moras:
        return False
    heard = sum(1 for mora in moras if mora.matched and mora.confidence == 1.0)
    return heard / len(moras) >= _SOLID_LINE_RATIO


def plan_chunks(
    timeline: LyricTimeline,
    duration_ms: int,
) -> list[AlignmentChunk]:
    lines = timeline.lines
    solid = [is_solid(line) for line in lines]
    groups: list[list[int]] = []
    for index, line in enumerate(lines):
        if not groups:
            groups.append([index])
            continue
        first = lines[groups[-1][0]]
        span = line.end_ms - first.start_ms
        rest = line.start_ms - lines[index - 1].end_ms
        # Only cut where both neighbours are trustworthy; a region the ASR
        # got wrong stays inside one excerpt together with its surroundings.
        can_cut = solid[index] and solid[index - 1]
        if (
            can_cut and (span > _TARGET_CHUNK_MS or rest > _LONG_REST_MS)
        ) or span > _MAX_CHUNK_MS:
            groups.append([index])
        else:
            groups[-1].append(index)

    chunks: list[AlignmentChunk] = []
    for group in groups:
        first, last = group[0], group[-1]
        start_ms = lines[first].start_ms - _PAD_MS
        if first > 0:
            previous_end = lines[first - 1].end_ms
            start_ms = (
                min(start_ms, previous_end)
                if solid[first] and solid[first - 1]
                else previous_end - _PAD_MS
            )
        if last + 1 < len(lines):
            end_ms = max(lines[last].end_ms + _PAD_MS, lines[last + 1].start_ms)
        else:
            end_ms = lines[last].end_ms + _TAIL_PAD_MS
        start_ms = max(0, start_ms)
        end_ms = min(duration_ms, end_ms)
        if end_ms > start_ms:
            chunks.append(AlignmentChunk(start_ms, end_ms, tuple(group)))
    return chunks


class QwenForcedAlignmentRefiner:
    """Refine a coarse lyric timeline with Qwen3-ForcedAligner.

    The model runs in a separate interpreter (see ``qwen_worker.py``); the
    result comes back as a transcript whose words are the lyrics themselves,
    ready for the regular timeline aligner.
    """

    def __init__(
        self,
        *,
        python_command: Sequence[str],
        model: str = "Qwen/Qwen3-ForcedAligner-0.6B",
        device: str = "cuda:0",
        timeout_seconds: int = 900,
    ) -> None:
        self.python_command = tuple(python_command)
        self.model = model
        self.device = device
        self.timeout_seconds = timeout_seconds

    def refine(
        self,
        lyrics: LyricDocument,
        timeline: LyricTimeline,
        audio_path: Path,
        *,
        duration_seconds: float,
        work_dir: Path,
    ) -> TranscriptDocument:
        chunks = plan_chunks(timeline, round(duration_seconds * 1000))
        if not chunks:
            raise ForcedAlignmentError("No lyric lines to align")
        return transcript_from_units(
            self._run(lyrics, chunks, audio_path, work_dir),
            duration_seconds=duration_seconds,
        )

    def refine_lines(
        self,
        lyrics: LyricDocument,
        windows: dict[int, tuple[int, int]],
        audio_path: Path,
        *,
        duration_seconds: float,
        work_dir: Path,
    ) -> dict[int, TranscriptDocument]:
        """Re-time individual lines inside windows chosen by a person."""
        duration_ms = round(duration_seconds * 1000)
        chunks = [
            AlignmentChunk(
                max(0, start_ms),
                min(duration_ms, end_ms + _LINE_TAIL_PAD_MS),
                (index,),
            )
            for index, (start_ms, end_ms) in sorted(windows.items())
        ]
        if not chunks:
            return {}
        by_line: dict[int, list[dict]] = {}
        for unit in self._run(lyrics, chunks, audio_path, work_dir):
            by_line.setdefault(int(unit["line"]), []).append(unit)
        return {
            index: transcript_from_units(
                units, duration_seconds=duration_seconds
            )
            for index, units in by_line.items()
        }

    def _run(
        self,
        lyrics: LyricDocument,
        chunks: list[AlignmentChunk],
        audio_path: Path,
        work_dir: Path,
    ) -> list[dict]:
        request_path = work_dir / "forced_alignment_request.json"
        response_path = work_dir / "forced_alignment.json"
        request_path.write_text(
            json.dumps(
                {
                    "audio": str(audio_path),
                    "model": self.model,
                    "device": self.device,
                    "chunks": [
                        {
                            "start_ms": chunk.start_ms,
                            "end_ms": chunk.end_ms,
                            "lines": [
                                {
                                    "index": index,
                                    "text": lyrics.lines[index].surface,
                                }
                                for index in chunk.line_indexes
                            ],
                        }
                        for chunk in chunks
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        response_path.unlink(missing_ok=True)
        try:
            subprocess.run(
                [
                    *self.python_command,
                    str(WORKER_PATH),
                    str(request_path),
                    str(response_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "worker exited with an error").strip()
            raise ForcedAlignmentError(detail[-2000:]) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ForcedAlignmentError(str(exc)) from exc
        finally:
            request_path.unlink(missing_ok=True)
        if not response_path.is_file():
            raise ForcedAlignmentError("Forced aligner produced no output")
        return json.loads(response_path.read_text(encoding="utf-8"))["units"]


def transcript_from_units(
    units: list[dict],
    *,
    duration_seconds: float,
) -> TranscriptDocument:
    words = [
        TranscriptWord(
            text=unit["text"],
            start_ms=int(unit["start_ms"]),
            end_ms=int(unit["end_ms"]),
            confidence=1.0,
        )
        for unit in units
    ]
    if not words:
        raise ForcedAlignmentError("Forced aligner returned no timed words")
    return TranscriptDocument(
        language="ja",
        language_probability=1.0,
        duration_seconds=duration_seconds,
        text="".join(word.text for word in words),
        segments=[
            TranscriptSegment(
                id=0,
                text="".join(word.text for word in words),
                start_ms=words[0].start_ms,
                end_ms=words[-1].end_ms,
                confidence=0.0,
                no_speech_probability=0.0,
                words=words,
            )
        ],
    )


def realign_lines(
    aligner,
    refiner: QwenForcedAlignmentRefiner,
    lyrics: LyricDocument,
    timeline: LyricTimeline,
    indexes: list[int],
    audio_path: Path,
    *,
    duration_seconds: float,
    work_dir: Path,
) -> tuple[LyricTimeline, list[int]]:
    """Re-time whole lines inside the windows they currently occupy.

    The start of each window is authoritative (the model pins the first word
    of an excerpt to the excerpt's start); the rhythm inside the line and its
    ending come from the forced aligner.  Lines the model cannot explain keep
    their current timing.  Returns the indexes that were re-timed.
    """
    windows = {
        index: (timeline.lines[index].start_ms, timeline.lines[index].end_ms)
        for index in indexes
    }
    transcripts = refiner.refine_lines(
        lyrics,
        windows,
        audio_path,
        duration_seconds=duration_seconds,
        work_dir=work_dir,
    )
    realigned: list[int] = []
    for index, transcript in transcripts.items():
        start_ms, end_ms = windows[index]
        try:
            line = aligner.align(
                LyricDocument(
                    provider=lyrics.provider,
                    source_text=lyrics.lines[index].source,
                    lines=[lyrics.lines[index]],
                ),
                transcript,
            ).lines[0]
        except ValueError:
            continue
        if (
            line.confidence < _MIN_REALIGNED_CONFIDENCE
            or line.end_ms <= line.start_ms
        ):
            continue
        upper = end_ms + _REALIGN_SLACK_MS
        if line.start_ms != start_ms or line.end_ms > upper:
            line = retime_line(
                line, start_ms, max(start_ms + 1, min(line.end_ms, upper))
            )
        timeline = replace_line(timeline, index, line)
        realigned.append(index)
    return timeline, sorted(realigned)
