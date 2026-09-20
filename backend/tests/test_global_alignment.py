from __future__ import annotations

import json
from pathlib import Path

from app.ai.whisper import (
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
)
from app.alignment.aligner import LyricTimelineAligner
from app.core.database import Database
from app.lyrics.models import LyricDocument, LyricLine, LyricToken
from app.subtitle.ass_generator import AssGenerator
from app.tasks.pipeline import TranscriptionPipeline


# Rows of the kana table: neutral, unmistakable test material.
KANA_ROWS = [
    "あいうえお",
    "かきくけこ",
    "さしすせそ",
    "たちつてと",
    "なにぬねの",
    "はひふへほ",
    "まみむめも",
    "らりるれろ",
]


def lyrics_of(rows: list[str]) -> LyricDocument:
    return LyricDocument(
        provider="local",
        source_text="\n".join(rows),
        lines=[
            LyricLine(
                source=row,
                surface=row,
                reading=row,
                tokens=[LyricToken(row, row)],
            )
            for row in rows
        ],
    )


def one_kana_words(
    text: str,
    start_ms: int,
    step_ms: int,
    *,
    duration_ms: int | None = None,
) -> list[TranscriptWord]:
    return [
        TranscriptWord(
            kana,
            start_ms + index * step_ms,
            start_ms
            + index * step_ms
            + (step_ms if duration_ms is None else duration_ms),
            0.9,
        )
        for index, kana in enumerate(text)
    ]


def segment(index: int, words: list[TranscriptWord]) -> TranscriptSegment:
    return TranscriptSegment(
        id=index,
        text="".join(word.text for word in words),
        start_ms=words[0].start_ms,
        end_ms=words[-1].end_ms,
        confidence=-0.2,
        no_speech_probability=0.0,
        words=words,
    )


def test_many_lines_inside_few_long_segments_all_get_a_karaoke_sweep() -> None:
    # Whisper emits one ~30 s segment per decoding window on sung audio, so
    # eight lyric lines arrive inside only two transcript segments.
    first = one_kana_words("".join(KANA_ROWS[:4]), 10_000, 400)
    second = one_kana_words("".join(KANA_ROWS[4:]), 40_000, 400)
    transcript = TranscriptDocument(
        language="ja",
        language_probability=1.0,
        duration_seconds=60.0,
        text="".join(KANA_ROWS),
        segments=[segment(0, first), segment(1, second)],
    )

    timeline = LyricTimelineAligner().align(lyrics_of(KANA_ROWS), transcript)

    assert timeline.confidence == 1.0
    assert [line.start_ms for line in timeline.lines] == [
        10_000,
        12_000,
        14_000,
        16_000,
        40_000,
        42_000,
        44_000,
        46_000,
    ]
    assert all(line.end_ms - line.start_ms == 2_000 for line in timeline.lines)


def test_collapsed_word_timestamps_are_heard_but_not_used_as_anchors() -> None:
    rows = KANA_ROWS[:3]
    # The middle line was recognised, but every word was stamped at the same
    # instant: a common Whisper failure on singing.
    words = [
        *one_kana_words(rows[0], 10_000, 400),
        *one_kana_words(rows[1], 12_000, 0, duration_ms=0),
        *one_kana_words(rows[2], 20_000, 400),
    ]
    transcript = TranscriptDocument(
        language="ja",
        language_probability=1.0,
        duration_seconds=30.0,
        text="".join(rows),
        segments=[segment(0, words)],
    )

    timeline = LyricTimelineAligner().align(lyrics_of(rows), transcript)
    middle = timeline.lines[1]

    assert timeline.confidence == 1.0
    assert middle.start_ms >= timeline.lines[0].end_ms
    assert middle.end_ms <= timeline.lines[2].start_ms
    # Laid out at the song's pace instead of collapsing to a single instant.
    assert middle.end_ms - middle.start_ms >= 1_500
    moras = middle.tokens[0].moras
    assert all(mora.matched for mora in moras)
    assert all(mora.end_ms > mora.start_ms for mora in moras)
    assert all(mora.confidence == 0.5 for mora in moras)


def test_stray_anchor_far_from_its_line_is_released() -> None:
    rows = ["あいうえお", "かきくけこ"]
    words = [
        *one_kana_words("あいうえ", 10_000, 400),
        # The last mora of line one is only "heard" after a long silence.
        *one_kana_words("お", 40_000, 400),
        *one_kana_words(rows[1], 41_000, 400),
    ]
    transcript = TranscriptDocument(
        language="ja",
        language_probability=1.0,
        duration_seconds=50.0,
        text="".join(rows),
        segments=[segment(0, words)],
    )

    timeline = LyricTimelineAligner().align(lyrics_of(rows), transcript)

    first = timeline.lines[0]
    assert first.start_ms == 10_000
    assert first.end_ms - first.start_ms < 5_000
    assert timeline.lines[1].start_ms == 41_000


def test_regenerating_a_job_realigns_from_stored_transcript(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_dir.mkdir(parents=True)
    video_path = job_dir / "input.mp4"
    video_path.write_bytes(b"video")
    job_id = "f13ecf06-9ac4-486f-a5cd-b4959f02bc76"
    database.create_job(
        job_id=job_id,
        original_video_name="song.mp4",
        video_size_bytes=5,
        video_sha256="abc",
        video_path=video_path,
        lyrics_source="text",
        lyrics_path=None,
    )
    rows = KANA_ROWS[:2]
    transcript = TranscriptDocument(
        language="ja",
        language_probability=1.0,
        duration_seconds=30.0,
        text="".join(rows),
        segments=[segment(0, one_kana_words("".join(rows), 5_000, 400))],
    )
    (job_dir / "transcript.json").write_text(
        json.dumps(transcript.to_dict()), encoding="utf-8"
    )
    (job_dir / "lyrics_processed.json").write_text(
        json.dumps(lyrics_of(rows).to_dict()), encoding="utf-8"
    )
    # A stale timeline from an older aligner: both lines collapsed.
    stale = LyricTimelineAligner().align(lyrics_of(rows), transcript).to_dict()
    for line in stale["lines"]:
        line["start_ms"] = line["end_ms"] = 0
    (job_dir / "timeline.json").write_text(json.dumps(stale), encoding="utf-8")
    database.update_job_state(
        job_id, status="UPLOADED", stage="RESTYLE_QUEUED", progress=90
    )

    class ForbiddenStep:
        def __getattr__(self, name: str):
            raise AssertionError(f"regenerating must not call {name}")

    class Renderer:
        def render(self, video, subtitle, output, **options) -> None:
            output.write_bytes(b"rendered")

    TranscriptionPipeline(
        database=database,
        extractor=ForbiddenStep(),
        transcriber=ForbiddenStep(),
        aligner=LyricTimelineAligner(),
        subtitle_generator=AssGenerator(),
        video_renderer=Renderer(),
    ).process(job_id)

    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "COMPLETED"
    refreshed = json.loads(
        (job_dir / "timeline.json").read_text(encoding="utf-8")
    )
    assert [line["start_ms"] for line in refreshed["lines"]] == [5_000, 7_000]
    assert r"\kf" in (job_dir / "lyrics.ass").read_text(encoding="utf-8-sig")
