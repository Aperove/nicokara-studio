from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.ai.whisper import (
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
)
from app.alignment.aligner import LyricTimelineAligner
from app.alignment.refiner import (
    ForcedAlignmentError,
    QwenForcedAlignmentRefiner,
    plan_chunks,
    transcript_from_units,
)
from app.core.database import Database
from app.lyrics.models import LyricDocument, LyricLine, LyricToken
from app.tasks.pipeline import TranscriptionPipeline


KANA_ROWS = ["あいうえお", "かきくけこ", "さしすせそ", "たちつてと"]


def lyrics_of(rows: list[str]) -> LyricDocument:
    return LyricDocument(
        provider="local",
        source_text="\n".join(rows),
        lines=[
            LyricLine(row, row, row, [LyricToken(row, row)]) for row in rows
        ],
    )


def transcript_of(timed_rows: list[tuple[str, int]], step_ms: int = 400):
    words = [
        TranscriptWord(
            kana, start + i * step_ms, start + (i + 1) * step_ms, 0.9
        )
        for row, start in timed_rows
        for i, kana in enumerate(row)
    ]
    return TranscriptDocument(
        language="ja",
        language_probability=1.0,
        duration_seconds=120.0,
        text="".join(row for row, _ in timed_rows),
        segments=[
            TranscriptSegment(
                0, "", words[0].start_ms, words[-1].end_ms, -0.1, 0.0, words
            )
        ],
    )


def test_chunks_cut_at_long_rests_and_cover_their_lines_with_padding() -> None:
    starts = [10_000, 12_500, 40_000, 42_500]
    timeline = LyricTimelineAligner().align(
        lyrics_of(KANA_ROWS),
        transcript_of(list(zip(KANA_ROWS, starts))),
    )

    chunks = plan_chunks(timeline, duration_ms=120_000)

    assert [chunk.line_indexes for chunk in chunks] == [(0, 1), (2, 3)]
    first, second = chunks
    assert first.start_ms == 9_000
    # Reaches the next sung line so a late phrase ending is never cut off.
    assert first.end_ms == 40_000
    assert second.start_ms <= 39_000
    assert second.end_ms == 42_500 + 2_000 + 4_000


def test_lines_the_asr_did_not_hear_stay_in_one_chunk_with_neighbours() -> None:
    rows = KANA_ROWS
    # Line 1 is missing from the ASR output and line 2 follows a long rest:
    # the cut before line 2 would separate the weak line from its context.
    timeline = LyricTimelineAligner().align(
        lyrics_of(rows),
        transcript_of([(rows[0], 10_000), (rows[2], 40_000), (rows[3], 42_500)]),
    )

    chunks = plan_chunks(timeline, duration_ms=120_000)

    assert any({0, 1, 2} <= set(chunk.line_indexes) for chunk in chunks)


def test_units_become_a_transcript_of_the_lyrics_themselves() -> None:
    transcript = transcript_from_units(
        [
            {"line": 0, "text": "あいう", "start_ms": 1000, "end_ms": 2200},
            {"line": 0, "text": "えお", "start_ms": 2200, "end_ms": 3000},
        ],
        duration_seconds=10.0,
    )

    timeline = LyricTimelineAligner().align(lyrics_of(["あいうえお"]), transcript)

    assert timeline.confidence == 1.0
    assert (timeline.lines[0].start_ms, timeline.lines[0].end_ms) == (1000, 3000)
    with pytest.raises(ForcedAlignmentError):
        transcript_from_units([], duration_seconds=10.0)


def test_refiner_runs_the_worker_in_another_interpreter(tmp_path: Path) -> None:
    fake_worker = tmp_path / "fake_worker.py"
    fake_worker.write_text(
        "import json, sys\n"
        "request = json.load(open(sys.argv[1], encoding='utf-8'))\n"
        "units = [\n"
        "    {'line': line['index'], 'text': line['text'],\n"
        "     'start_ms': chunk['start_ms'] + 1500,\n"
        "     'end_ms': chunk['start_ms'] + 3500}\n"
        "    for chunk in request['chunks'] for line in chunk['lines']\n"
        "]\n"
        "json.dump({'units': units}, open(sys.argv[2], 'w', encoding='utf-8'))\n",
        encoding="utf-8",
    )
    lyrics = lyrics_of(["あいうえお"])
    timeline = LyricTimelineAligner().align(
        lyrics, transcript_of([("あいうえお", 10_000)])
    )
    refiner = QwenForcedAlignmentRefiner(python_command=(sys.executable,))

    import app.alignment.refiner as refiner_module

    original = refiner_module.WORKER_PATH
    refiner_module.WORKER_PATH = fake_worker
    try:
        refined = refiner.refine(
            lyrics,
            timeline,
            tmp_path / "audio.wav",
            duration_seconds=120.0,
            work_dir=tmp_path,
        )
    finally:
        refiner_module.WORKER_PATH = original

    word = refined.segments[0].words[0]
    assert (word.text, word.start_ms, word.end_ms) == ("あいうえお", 10_500, 12_500)
    assert not (tmp_path / "forced_alignment_request.json").exists()
    assert (tmp_path / "forced_alignment.json").is_file()


def test_refiner_reports_a_missing_interpreter_as_alignment_error(
    tmp_path: Path,
) -> None:
    lyrics = lyrics_of(["あいうえお"])
    timeline = LyricTimelineAligner().align(
        lyrics, transcript_of([("あいうえお", 10_000)])
    )
    refiner = QwenForcedAlignmentRefiner(
        python_command=(str(tmp_path / "no-such-python.exe"),)
    )

    with pytest.raises(ForcedAlignmentError):
        refiner.refine(
            lyrics,
            timeline,
            tmp_path / "audio.wav",
            duration_seconds=120.0,
            work_dir=tmp_path,
        )


class ShiftingRefiner:
    """Pretends the forced aligner heard every line 300 ms later."""

    def __init__(self, *, fail: bool = False, garbage: bool = False) -> None:
        self.fail = fail
        self.garbage = garbage
        self.audio: Path | None = None

    def refine(self, lyrics, timeline, audio_path, *, duration_seconds, work_dir):
        self.audio = audio_path
        if self.fail:
            raise ForcedAlignmentError("worker crashed")
        units = [
            {
                "line": index,
                "text": "んんんんん" if self.garbage else line.surface,
                "start_ms": line.start_ms + 300,
                "end_ms": line.end_ms + 300,
            }
            for index, line in enumerate(timeline.lines)
        ]
        return transcript_from_units(units, duration_seconds=duration_seconds)


def build_pipeline(tmp_path: Path, refiner) -> tuple[TranscriptionPipeline, Path]:
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "audio.wav").write_bytes(b"mix")
    return (
        TranscriptionPipeline(
            database=database,
            extractor=None,
            transcriber=None,
            aligner=LyricTimelineAligner(),
            alignment_refiner=refiner,
        ),
        job_dir,
    )


def test_pipeline_adopts_the_refined_timeline_and_prefers_the_vocal_stem(
    tmp_path: Path,
) -> None:
    refiner = ShiftingRefiner()
    pipeline, job_dir = build_pipeline(tmp_path, refiner)
    (job_dir / "audio_vocals.wav").write_bytes(b"vocals")
    rows = KANA_ROWS[:2]

    timeline = pipeline._build_timeline(
        job_dir,
        lyrics_of(rows),
        transcript_of([(rows[0], 10_000), (rows[1], 12_500)]),
    )

    assert [line.start_ms for line in timeline.lines] == [10_300, 12_800]
    assert refiner.audio == job_dir / "audio_vocals.wav"


@pytest.mark.parametrize("mode", ["fail", "garbage"])
def test_pipeline_keeps_the_asr_timeline_when_refinement_goes_wrong(
    tmp_path: Path,
    mode: str,
) -> None:
    refiner = ShiftingRefiner(fail=mode == "fail", garbage=mode == "garbage")
    pipeline, job_dir = build_pipeline(tmp_path, refiner)
    rows = KANA_ROWS[:2]

    timeline = pipeline._build_timeline(
        job_dir,
        lyrics_of(rows),
        transcript_of([(rows[0], 10_000), (rows[1], 12_500)]),
    )

    assert [line.start_ms for line in timeline.lines] == [10_000, 12_500]
    assert refiner.audio == job_dir / "audio.wav"
