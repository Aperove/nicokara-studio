from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai.whisper import (
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
)
from app.alignment.aligner import LyricTimelineAligner
from app.alignment.editing import (
    MANUALLY_EDITED,
    TimelineEditError,
    apply_line_edits,
    retime_line,
    trim_overlaps,
)
from app.alignment.refiner import transcript_from_units
from app.core.config import Settings
from app.core.database import Database
from app.lyrics.models import LyricDocument, LyricLine, LyricToken
from app.main import create_app
from app.subtitle.ass_generator import AssGenerator
from app.tasks.pipeline import TranscriptionPipeline


ROWS = ["あいうえお", "かきくけこ", "さしすせそ"]


def lyrics_of(rows: list[str]) -> LyricDocument:
    return LyricDocument(
        provider="local",
        source_text="\n".join(rows),
        lines=[LyricLine(row, row, row, [LyricToken(row, row)]) for row in rows],
    )


def transcript_of(timed_rows: list[tuple[str, int]]) -> TranscriptDocument:
    words = [
        TranscriptWord(kana, start + i * 400, start + (i + 1) * 400, 0.9)
        for row, start in timed_rows
        for i, kana in enumerate(row)
    ]
    return TranscriptDocument(
        language="ja",
        language_probability=1.0,
        duration_seconds=60.0,
        text="",
        segments=[
            TranscriptSegment(
                0, "", words[0].start_ms, words[-1].end_ms, -0.1, 0.0, words
            )
        ],
    )


def sample_timeline():
    return LyricTimelineAligner().align(
        lyrics_of(ROWS),
        transcript_of([(ROWS[0], 10_000), (ROWS[1], 14_000), (ROWS[2], 18_000)]),
    )


def test_retiming_a_line_keeps_its_internal_rhythm() -> None:
    line = sample_timeline().lines[0]

    moved = retime_line(line, 20_000, 24_000)

    assert (moved.start_ms, moved.end_ms) == (20_000, 24_000)
    starts = [mora.start_ms for mora in moved.tokens[0].moras]
    assert starts == [20_000, 20_800, 21_600, 22_400, 23_200]
    assert moved.tokens[0].moras[-1].end_ms == 24_000


def test_edits_mark_the_timeline_and_trim_an_overlapping_neighbour() -> None:
    edited = apply_line_edits(sample_timeline(), {1: (11_000, 13_000)})

    assert MANUALLY_EDITED in edited.warnings
    assert edited.lines[0].end_ms == 11_000
    assert (edited.lines[1].start_ms, edited.lines[1].end_ms) == (11_000, 13_000)


def test_overlapping_neighbours_are_trimmed_without_marking_an_edit() -> None:
    timeline = sample_timeline()
    lines = list(timeline.lines)
    lines[0] = retime_line(lines[0], 10_000, 15_000)  # runs into line 2 at 14 s
    overlapping = type(timeline)(timeline.confidence, lines, timeline.warnings)

    trimmed = trim_overlaps(overlapping)

    assert trimmed.lines[0].end_ms == trimmed.lines[1].start_ms == 14_000
    assert trimmed.lines[1:] == overlapping.lines[1:]
    assert MANUALLY_EDITED not in trimmed.warnings


@pytest.mark.parametrize(
    "edits",
    [
        {0: (5_000, 5_000)},
        {1: (9_000, 12_000)},
        {7: (1_000, 2_000)},
        {2: (50_000, 70_000)},
    ],
)
def test_impossible_edits_are_rejected(edits: dict) -> None:
    with pytest.raises(TimelineEditError):
        apply_line_edits(sample_timeline(), edits, duration_ms=60_000)


def fake_mp4() -> bytes:
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"video-data"


class InlinePipeline:
    def __init__(self, aligner=None, alignment_refiner=None) -> None:
        self.aligner = aligner
        self.alignment_refiner = alignment_refiner


class RecordingRunner:
    can_accept = True

    def __init__(self, pipeline: InlinePipeline) -> None:
        self.pipeline = pipeline
        self.enqueued: list[str] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def enqueue(self, job_id: str, **_: object) -> None:
        self.enqueued.append(job_id)


class NudgingRefiner:
    """Pretends the forced aligner found each line 200 ms into its window."""

    def refine_lines(self, lyrics, windows, audio_path, *, duration_seconds, work_dir):
        return {
            index: transcript_from_units(
                [
                    {
                        "line": index,
                        "text": lyrics.lines[index].surface,
                        "start_ms": start_ms + 200,
                        "end_ms": end_ms - 200,
                    }
                ],
                duration_seconds=duration_seconds,
            )
            for index, (start_ms, end_ms) in windows.items()
        }


def review_client(tmp_path: Path, runner: RecordingRunner) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    return TestClient(create_app(settings, runner=runner))


def prepare_review_job(client: TestClient, tmp_path: Path) -> tuple[str, Path]:
    response = client.post(
        "/api/v1/jobs",
        files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
        data={"lyrics_text": "\n".join(ROWS), "review": "true"},
    )
    assert response.status_code == 201
    job_id = response.json()["id"]
    job_dir = tmp_path / "jobs" / job_id
    assert json.loads((job_dir / "options.json").read_text("utf-8")) == {
        "review_before_render": True
    }
    timeline_path = job_dir / "timeline.json"
    timeline_path.write_text(
        json.dumps(sample_timeline().to_dict()), encoding="utf-8"
    )
    (job_dir / "lyrics_processed.json").write_text(
        json.dumps(lyrics_of(ROWS).to_dict()), encoding="utf-8"
    )
    (job_dir / "transcript.json").write_text(
        json.dumps(
            transcript_of([(ROWS[0], 10_000)]).to_dict()
        ),
        encoding="utf-8",
    )
    (job_dir / "audio.wav").write_bytes(b"RIFFmix")
    client.app.state.database.update_job_state(
        job_id,
        status="AWAITING_REVIEW",
        stage="REVIEW_PENDING",
        progress=96,
        timeline_path=timeline_path,
    )
    return job_id, job_dir


def test_review_flow_edit_refine_and_render(tmp_path: Path) -> None:
    runner = RecordingRunner(
        InlinePipeline(LyricTimelineAligner(), NudgingRefiner())
    )
    with review_client(tmp_path, runner) as client:
        job_id, job_dir = prepare_review_job(client, tmp_path)
        runner.enqueued.clear()
        base = f"/api/v1/jobs/{job_id}"

        review = client.get(f"{base}/review").json()
        assert review["can_refine"] is True
        assert review["has_vocals"] is False
        assert review["duration_ms"] == 60_000
        assert len(review["timeline"]["lines"]) == 3

        assert client.get(f"{base}/source").content == fake_mp4()
        assert client.get(f"{base}/audio/mix").status_code == 200
        assert client.get(f"{base}/audio/vocals").status_code == 404
        assert client.get(f"{base}/audio/secret").status_code == 404

        rejected = client.put(
            f"{base}/timeline",
            json={"lines": [{"index": 1, "start_ms": 1_000, "end_ms": 2_000}]},
        )
        assert rejected.status_code == 422

        # Moving line 1 alone would put it after line 2: edits are saved as
        # one batch so only the final arrangement has to be valid.
        out_of_order = client.put(
            f"{base}/timeline",
            json={"lines": [{"index": 1, "start_ms": 30_000, "end_ms": 34_000}]},
        )
        assert out_of_order.status_code == 422

        saved = client.put(
            f"{base}/timeline",
            json={
                "lines": [
                    {"index": 1, "start_ms": 30_000, "end_ms": 34_000},
                    {"index": 2, "start_ms": 36_000, "end_ms": 40_000},
                ]
            },
        )
        assert saved.status_code == 200
        stored = json.loads((job_dir / "timeline.json").read_text("utf-8"))
        assert stored["lines"][1]["start_ms"] == 30_000
        assert MANUALLY_EDITED in stored["warnings"]

        refined = client.post(f"{base}/timeline/refine", json={"lines": [1]})
        assert refined.status_code == 200
        assert refined.json()["refined_lines"] == [1]
        line = refined.json()["timeline"]["lines"][1]
        # The start a person marked stays put; the model only moves the end
        # and the rhythm inside the line.
        assert (line["start_ms"], line["end_ms"]) == (30_000, 33_800)

        rendered = client.post(f"{base}/render")
        assert rendered.status_code == 200
        assert rendered.json()["stage"] == "RENDER_QUEUED"
        assert runner.enqueued == [job_id]


def test_refine_is_unavailable_without_a_forced_aligner(tmp_path: Path) -> None:
    runner = RecordingRunner(InlinePipeline(LyricTimelineAligner(), None))
    with review_client(tmp_path, runner) as client:
        job_id, _ = prepare_review_job(client, tmp_path)

        assert client.get(f"/api/v1/jobs/{job_id}/review").json()[
            "can_refine"
        ] is False
        response = client.post(
            f"/api/v1/jobs/{job_id}/timeline/refine", json={"lines": [0]}
        )
        assert response.status_code == 409


class Renderer:
    def __init__(self) -> None:
        self.calls = 0

    def render(self, video, subtitle, output, **options) -> None:
        self.calls += 1
        output.write_bytes(b"rendered")


class FixedStep:
    def extract(self, video, audio) -> None:
        audio.write_bytes(b"wav")

    def transcribe(self, audio, **options):
        return transcript_of(
            [(ROWS[0], 10_000), (ROWS[1], 14_000), (ROWS[2], 18_000)]
        )

    def process(self, text: str) -> LyricDocument:
        return lyrics_of(ROWS)


def test_pipeline_pauses_for_review_then_renders_the_corrected_timeline(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_dir.mkdir(parents=True)
    video_path = job_dir / "input.mp4"
    video_path.write_bytes(b"video")
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("\n".join(ROWS), encoding="utf-8")
    (job_dir / "options.json").write_text(
        json.dumps({"review_before_render": True}), encoding="utf-8"
    )
    job_id = "f13ecf06-9ac4-486f-a5cd-b4959f02bc76"
    database.create_job(
        job_id=job_id,
        original_video_name="song.mp4",
        video_size_bytes=5,
        video_sha256="abc",
        video_path=video_path,
        lyrics_source="text",
        lyrics_path=lyrics_path,
    )
    step, renderer = FixedStep(), Renderer()
    pipeline = TranscriptionPipeline(
        database=database,
        extractor=step,
        transcriber=step,
        lyric_processor=step,
        aligner=LyricTimelineAligner(),
        subtitle_generator=AssGenerator(),
        video_renderer=renderer,
    )

    pipeline.process(job_id)

    job = database.get_job(job_id)
    assert job is not None
    assert (job["status"], job["stage"]) == ("AWAITING_REVIEW", "REVIEW_PENDING")
    assert renderer.calls == 0
    assert (job_dir / "lyrics.ass").is_file()

    timeline_path = job_dir / "timeline.json"
    from app.alignment.models import LyricTimeline

    corrected = apply_line_edits(
        LyricTimeline.from_dict(json.loads(timeline_path.read_text("utf-8"))),
        {2: (40_000, 44_000)},
    )
    timeline_path.write_text(json.dumps(corrected.to_dict()), encoding="utf-8")
    database.update_job_state(
        job_id, status="UPLOADED", stage="RENDER_QUEUED", progress=96
    )

    pipeline.process(job_id)

    job = database.get_job(job_id)
    assert job is not None and job["status"] == "COMPLETED"
    assert renderer.calls == 1
    # Rendered from the hand-corrected timing, not from a fresh alignment.
    assert "0:00:40.00" in (job_dir / "lyrics.ass").read_text("utf-8-sig")

    # A later style change must not realign away the manual correction.
    database.update_job_state(
        job_id, status="UPLOADED", stage="RESTYLE_QUEUED", progress=90
    )
    pipeline.process(job_id)
    stored = json.loads(timeline_path.read_text("utf-8"))
    assert stored["lines"][2]["start_ms"] == 40_000


def test_the_style_chosen_while_reviewing_is_stored_with_the_render_request(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner(InlinePipeline(LyricTimelineAligner(), None))
    with review_client(tmp_path, runner) as client:
        job_id, job_dir = prepare_review_job(client, tmp_path)
        base = f"/api/v1/jobs/{job_id}"
        style = client.get(f"{base}/style").json()

        invalid = client.post(f"{base}/render", json={**style, "sung_color": "red"})
        assert invalid.status_code == 422
        queued_before = len(runner.enqueued)

        chosen = client.post(
            f"{base}/render", json={**style, "sung_color": "#38BDF8", "glow": False}
        )

        assert chosen.status_code == 200
        assert len(runner.enqueued) == queued_before + 1
        stored = json.loads((job_dir / "style.json").read_text("utf-8"))
        assert (stored["sung_color"], stored["glow"]) == ("#38BDF8", False)
