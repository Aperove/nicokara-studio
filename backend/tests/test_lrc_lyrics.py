from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.ai.whisper import (
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
)
from app.alignment.aligner import LyricTimelineAligner
from app.alignment.refiner import transcript_from_units
from app.core.config import Settings
from app.core.database import Database
from app.lyrics.lrc import parse_lyrics
from app.lyrics.models import LyricDocument, LyricLine, LyricToken
from app.main import create_app
from app.tasks.pipeline import TranscriptionPipeline


ROWS = ["あいうえお", "かきくけこ", "さしすせそ"]


def lyrics_of(rows: list[str]) -> LyricDocument:
    return LyricDocument(
        provider="local",
        source_text="\n".join(rows),
        lines=[LyricLine(row, row, row, [LyricToken(row, row)]) for row in rows],
    )


def test_plain_lyrics_pass_through_untouched() -> None:
    text = "あいうえお\n\nかきくけこ\n"

    parsed = parse_lyrics(text)

    assert parsed.text == text
    assert parsed.line_starts_ms is None


def test_lrc_tags_are_removed_and_line_starts_kept() -> None:
    parsed = parse_lyrics(
        "[ti:test]\n[ar:someone]\n"
        "[00:12.50]あいうえお\n"
        "[00:20.00]\n"  # interlude marker
        "[01:05.123]<01:05.12>かき<01:06.00>くけこ\n"
        "[02:00:50]さしすせそ\n"
    )

    assert parsed.text == "あいうえお\nかきくけこ\nさしすせそ"
    assert parsed.line_starts_ms == [12_500, 65_123, 120_500]


def test_repeated_lines_are_written_out_in_time_order_and_offset_applies() -> None:
    parsed = parse_lyrics(
        "[offset:500]\n"
        "[00:10.00][01:10.00]あいうえお\n"
        "[00:40.00]かきくけこ\n"
    )

    assert parsed.text == "あいうえお\nかきくけこ\nあいうえお"
    assert parsed.line_starts_ms == [9_500, 39_500, 69_500]


def test_text_that_only_looks_a_bit_like_lrc_is_left_alone() -> None:
    # one stray timestamp, or timed and untimed lines mixed: not an LRC file
    for text in ("[00:10.00]あいうえお\n", "[00:10.00]あいうえお\nかきくけこ\n[00:20.00]さ\n"):
        assert parse_lyrics(text).line_starts_ms is None


class IdleRunner:
    can_accept = True
    pipeline = None

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def enqueue(self, job_id: str, **_: object) -> None:
        pass


def test_pasted_lrc_is_stored_as_plain_lyrics_plus_line_starts(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    mp4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"video-data"
    with TestClient(create_app(settings, runner=IdleRunner())) as client:
        lrc_job = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", mp4, "video/mp4")},
            data={"lyrics_text": "[00:10.00]あいうえお\n[00:20.00]かきくけこ"},
        ).json()["id"]
        plain_job = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", mp4, "video/mp4")},
            data={"lyrics_text": "あいうえお\nかきくけこ"},
        ).json()["id"]

    lrc_dir, plain_dir = tmp_path / "jobs" / lrc_job, tmp_path / "jobs" / plain_job
    assert (lrc_dir / "lyrics.txt").read_text("utf-8") == "あいうえお\nかきくけこ\n"
    assert json.loads((lrc_dir / "lyrics_lrc.json").read_text("utf-8")) == {
        "line_starts_ms": [10_000, 20_000]
    }
    assert not (plain_dir / "lyrics_lrc.json").exists()


def transcript_at(starts: list[int]) -> TranscriptDocument:
    words = [
        TranscriptWord(kana, start + i * 400, start + (i + 1) * 400, 0.9)
        for row, start in zip(ROWS, starts)
        for i, kana in enumerate(row)
    ]
    return TranscriptDocument(
        "ja", 1.0, 120.0, "",
        [TranscriptSegment(0, "", words[0].start_ms, words[-1].end_ms, -0.1, 0.0, words)],
    )


class WindowRefiner:
    """Pretends the forced aligner confirmed every window it was given."""

    def __init__(self) -> None:
        self.windows: dict[int, tuple[int, int]] = {}

    def refine_lines(self, lyrics, windows, audio_path, *, duration_seconds, work_dir):
        self.windows = dict(windows)
        return {
            index: transcript_from_units(
                [{"line": index, "text": lyrics.lines[index].surface,
                  "start_ms": start, "end_ms": end}],
                duration_seconds=duration_seconds,
            )
            for index, (start, end) in windows.items()
        }


def make_pipeline(tmp_path: Path, refiner=None):
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
            primary_aligner=refiner,
        ),
        job_dir,
    )


def test_lrc_only_overrules_a_line_that_is_grossly_misplaced(tmp_path: Path) -> None:
    refiner = WindowRefiner()
    pipeline, job_dir = make_pipeline(tmp_path, refiner)
    # The aligner put line 2 nine seconds early; lines 1 and 3 are within a
    # second of the LRC, which is as exact as LRC files get.
    (job_dir / "lyrics_lrc.json").write_text(
        json.dumps({"line_starts_ms": [10_400, 29_000, 39_500]}), encoding="utf-8"
    )
    # mark the transcript as already forced so no refinement pass runs first
    (job_dir / "transcript.source").write_text("karatimer\n", encoding="utf-8")

    timeline = pipeline._build_timeline(
        job_dir, lyrics_of(ROWS), transcript_at([10_000, 20_000, 40_000])
    )

    assert [line.start_ms for line in timeline.lines] == [10_000, 29_000, 40_000]
    assert timeline.lines[1].end_ms == 31_000  # keeps its own length
    assert list(refiner.windows) == [1]
    notes = json.loads((job_dir / "alignment_notes.json").read_text("utf-8"))
    assert notes["lrc_adjusted_lines"] == [1]


def test_an_lrc_that_does_not_match_the_lyrics_is_ignored(tmp_path: Path) -> None:
    pipeline, job_dir = make_pipeline(tmp_path)
    (job_dir / "lyrics_lrc.json").write_text(
        json.dumps({"line_starts_ms": [50_000, 60_000]}), encoding="utf-8"
    )

    timeline = pipeline._build_timeline(
        job_dir, lyrics_of(ROWS), transcript_at([10_000, 20_000, 40_000])
    )

    assert [line.start_ms for line in timeline.lines] == [10_000, 20_000, 40_000]
    assert not (job_dir / "alignment_notes.json").exists()
