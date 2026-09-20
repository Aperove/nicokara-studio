from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.alignment.models import AlignedLine, AlignedToken, LyricTimeline
from app.core.config import Settings
from app.core.database import Database
from app.main import create_app
from app.subtitle.ass_generator import AssConfig, AssGenerator
from app.subtitle.style import SubtitleStyle, ass_color
from app.tasks.pipeline import TranscriptionPipeline


def fake_mp4() -> bytes:
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"video-data"


def sample_timeline() -> LyricTimeline:
    return LyricTimeline(
        confidence=1.0,
        lines=[
            AlignedLine(
                surface="試験",
                reading="しけん",
                start_ms=5000,
                end_ms=7000,
                confidence=1.0,
                tokens=[AlignedToken("試験", "しけん", 5000, 7000, 1.0)],
            )
        ],
    )


def test_hex_colors_become_ass_bgr_colors() -> None:
    assert ass_color("#FF8000") == "&H000080FF"
    assert ass_color("#FF8000", alpha=0x40) == "&H400080FF"


def test_style_changes_font_colors_layout_and_layers() -> None:
    style = SubtitleStyle(
        font_name="Yu Gothic",
        font_size=80,
        sung_color="#00FF00",
        unsung_color="#FFFFFF",
        outline_color="#000000",
        show_ruby=False,
        glow=False,
        layout="centered",
        vertical_position="top",
    )

    content = AssGenerator(config=style.apply_to(AssConfig())).generate(
        sample_timeline()
    )

    assert "Style: LyricBase,Yu Gothic,80,&H00FFFFFF" in content
    assert "Style: Highlight,Yu Gothic,80,&H0000FF00" in content
    assert r"\pos(960,173)" in content
    assert ",Ruby,," not in content
    assert ",Glow,," not in content


@pytest.mark.parametrize(
    "payload",
    [
        {"font_name": "Bad,Font"},
        {"font_name": "{\\b1}"},
        {"sung_color": "red"},
        {"font_size": 500},
        {"unknown_option": 1},
    ],
)
def test_style_rejects_unsafe_or_out_of_range_values(payload: dict) -> None:
    with pytest.raises(ValidationError):
        SubtitleStyle(**payload)


def test_timeline_round_trips_through_json() -> None:
    timeline = sample_timeline()
    assert LyricTimeline.from_dict(timeline.to_dict()) == timeline


class RecordingRunner:
    can_accept = True

    def __init__(self) -> None:
        self.enqueued: list[str] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def enqueue(self, job_id: str, **_: object) -> None:
        self.enqueued.append(job_id)


def build_client(tmp_path: Path, runner: RecordingRunner) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    return TestClient(create_app(settings, runner=runner))


def test_upload_stores_style_and_rejects_invalid_style(tmp_path: Path) -> None:
    runner = RecordingRunner()
    with build_client(tmp_path, runner) as client:
        response = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
            data={
                "lyrics_text": "試験",
                "style": json.dumps({"sung_color": "#00ff00"}),
            },
        )
        assert response.status_code == 201
        job_id = response.json()["id"]
        assert client.get(f"/api/v1/jobs/{job_id}/style").json()[
            "sung_color"
        ] == "#00FF00"

        rejected = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "試験", "style": '{"font_size": 9999}'},
        )
        assert rejected.status_code == 422


def test_restyle_requires_timeline_then_requeues_job(tmp_path: Path) -> None:
    runner = RecordingRunner()
    with build_client(tmp_path, runner) as client:
        job_id = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
            data={"lyrics_text": "試験"},
        ).json()["id"]
        runner.enqueued.clear()

        early = client.post(f"/api/v1/jobs/{job_id}/restyle", json={})
        assert early.status_code == 409

        job_dir = tmp_path / "jobs" / job_id
        timeline_path = job_dir / "timeline.json"
        timeline_path.write_text(
            json.dumps(sample_timeline().to_dict()), encoding="utf-8"
        )
        database: Database = client.app.state.database
        database.update_job_state(
            job_id,
            status="COMPLETED",
            stage="VIDEO_RENDERING_COMPLETE",
            progress=100,
            timeline_path=timeline_path,
        )

        response = client.post(
            f"/api/v1/jobs/{job_id}/restyle",
            json={"glow": False, "font_size": 90},
        )

        assert response.status_code == 200
        assert response.json()["stage"] == "RESTYLE_QUEUED"
        assert runner.enqueued == [job_id]
        assert json.loads((job_dir / "style.json").read_text("utf-8"))[
            "font_size"
        ] == 90


def test_pipeline_restyle_skips_transcription(tmp_path: Path) -> None:
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
    (job_dir / "timeline.json").write_text(
        json.dumps(sample_timeline().to_dict()), encoding="utf-8"
    )
    (job_dir / "style.json").write_text(
        json.dumps({"sung_color": "#00FF00", "glow": False}),
        encoding="utf-8",
    )
    database.update_job_state(
        job_id, status="UPLOADED", stage="RESTYLE_QUEUED", progress=90
    )

    class ForbiddenStep:
        def __getattr__(self, name: str):
            raise AssertionError(f"restyle must not call {name}")

    class Renderer:
        def render(self, video, subtitle, output, **options) -> None:
            output.write_bytes(b"rendered")

    TranscriptionPipeline(
        database=database,
        extractor=ForbiddenStep(),
        transcriber=ForbiddenStep(),
        subtitle_generator=AssGenerator(),
        video_renderer=Renderer(),
    ).process(job_id)

    job = database.get_job(job_id)
    assert job is not None
    assert job["status"] == "COMPLETED"
    content = (job_dir / "lyrics.ass").read_text(encoding="utf-8-sig")
    assert "&H0000FF00" in content
    assert ",Glow,," not in content
