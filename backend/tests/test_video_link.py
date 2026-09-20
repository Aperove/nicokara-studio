from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import Database
from app.main import create_app
from app.tasks.pipeline import TranscriptionPipeline
from app.video.download import (
    DownloadedVideo,
    UnsupportedVideoUrl,
    VideoDownloadError,
    YtDlpVideoDownloader,
    validate_video_url,
)


HOSTS = ["youtube.com", "youtu.be"]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc123",
        "https://youtu.be/abc123",
        "http://music.youtube.com/watch?v=abc123",
        "  https://YOUTUBE.com/watch?v=abc123  ",
    ],
)
def test_links_to_allowed_sites_are_accepted(url: str) -> None:
    assert validate_video_url(url, HOSTS) == url.strip()


@pytest.mark.parametrize(
    "url",
    [
        "",
        "youtube.com/watch?v=abc123",
        "ftp://youtube.com/video",
        "file:///C:/Windows/system.ini",
        "https://example.com/watch?v=abc123",
        "https://youtube.com.evil.example/watch",
        "https://notyoutube.com/watch",
        "http://127.0.0.1:8100/health",
        "https://user:secret@youtube.com/watch",
        "https://youtube.com/watch?v=a b",
        "--exec=calc https://youtube.com/watch",
        "https://youtube.com/" + "a" * 3000,
    ],
)
def test_other_links_are_rejected(url: str) -> None:
    with pytest.raises(UnsupportedVideoUrl):
        validate_video_url(url, HOSTS)


FAKE_YT_DLP = """
import sys
arguments = sys.argv[1:]
assert arguments[-2] == "--", arguments
output = arguments[arguments.index("--output") + 1]
if "fail" in arguments[-1]:
    sys.exit("ERROR: video unavailable")
open(output, "wb").write(b"\\x00\\x00\\x00\\x18ftypisom" + b"video")
print("Example Title")
"""


def fake_downloader(tmp_path: Path, **options) -> YtDlpVideoDownloader:
    script = tmp_path / "fake_yt_dlp.py"
    script.write_text(FAKE_YT_DLP, encoding="utf-8")
    return YtDlpVideoDownloader(
        allowed_hosts=HOSTS, command=(sys.executable, str(script)), **options
    )


def test_downloader_writes_the_video_and_reports_its_title(tmp_path: Path) -> None:
    target = tmp_path / "job" / "input.mp4"

    video = fake_downloader(tmp_path).download("https://youtu.be/abc123", target)

    assert video == DownloadedVideo(path=target, title="Example Title")
    assert target.read_bytes().endswith(b"video")


def test_downloader_failures_leave_nothing_behind(tmp_path: Path) -> None:
    target = tmp_path / "job" / "input.mp4"
    downloader = fake_downloader(tmp_path)

    with pytest.raises(VideoDownloadError, match="video unavailable"):
        downloader.download("https://youtu.be/fail", target)
    assert not target.exists()

    with pytest.raises(VideoDownloadError, match="size limit"):
        fake_downloader(tmp_path, max_bytes=4).download(
            "https://youtu.be/abc123", target
        )
    assert not target.exists()

    with pytest.raises(UnsupportedVideoUrl):
        downloader.download("https://example.com/video", target)


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


def fake_mp4() -> bytes:
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"video-data"


def build_client(tmp_path: Path, runner: RecordingRunner) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    return TestClient(create_app(settings, runner=runner))


def test_a_job_can_be_created_from_a_link_instead_of_an_upload(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    with build_client(tmp_path, runner) as client:
        response = client.post(
            "/api/v1/jobs",
            data={
                "video_url": "https://www.youtube.com/watch?v=abc123",
                "lyrics_text": "あいうえお",
            },
        )

        assert response.status_code == 201
        job = response.json()
        assert job["status"] == "UPLOADED"
        assert job["video_size_bytes"] == 0
        job_dir = tmp_path / "jobs" / job["id"]
        assert (job_dir / "source_url.txt").read_text("utf-8").strip() == (
            "https://www.youtube.com/watch?v=abc123"
        )
        assert not (job_dir / "input.mp4").exists()
        assert (job_dir / "lyrics.txt").is_file()
        assert runner.enqueued == [job["id"]]


def test_link_and_upload_are_mutually_exclusive_and_links_are_checked(
    tmp_path: Path,
) -> None:
    with build_client(tmp_path, RecordingRunner()) as client:
        neither = client.post("/api/v1/jobs", data={"lyrics_text": "あ"})
        both = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", fake_mp4(), "video/mp4")},
            data={"video_url": "https://youtu.be/abc123"},
        )
        foreign = client.post(
            "/api/v1/jobs", data={"video_url": "https://example.com/video"}
        )
        local = client.post(
            "/api/v1/jobs", data={"video_url": "http://127.0.0.1:8100/health"}
        )

    assert [r.status_code for r in (neither, both, foreign, local)] == [422] * 4
    assert list((tmp_path / "jobs").iterdir()) == []


def test_recent_jobs_are_listed_newest_first(tmp_path: Path) -> None:
    with build_client(tmp_path, RecordingRunner()) as client:
        ids = [
            client.post(
                "/api/v1/jobs",
                files={"video": (f"song{n}.mp4", fake_mp4(), "video/mp4")},
                data={"lyrics_text": "あ"},
            ).json()["id"]
            for n in range(3)
        ]

        listed = client.get("/api/v1/jobs").json()
        limited = client.get("/api/v1/jobs", params={"limit": 2}).json()

    assert [job["id"] for job in listed] == ids[::-1]
    assert [job["id"] for job in limited] == ids[::-1][:2]
    assert listed[0]["original_video_name"] == "song2.mp4"


class StubDownloader:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.urls: list[str] = []

    def download(self, url: str, destination: Path) -> DownloadedVideo:
        self.urls.append(url)
        if self.fail:
            raise VideoDownloadError("video unavailable")
        destination.write_bytes(b"downloaded-video")
        return DownloadedVideo(destination, 'My "Song": Title/Version?')


class Extractor:
    def extract(self, video: Path, audio: Path) -> None:
        assert video.read_bytes() == b"downloaded-video"
        audio.write_bytes(b"wav")


class Transcriber:
    def transcribe(self, audio: Path, **options):
        from app.ai.whisper import TranscriptDocument

        return TranscriptDocument("ja", 1.0, 10.0, "", [])


def link_job(tmp_path: Path) -> tuple[Database, Path, str]:
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_dir.mkdir(parents=True)
    (job_dir / "source_url.txt").write_text(
        "https://youtu.be/abc123\n", encoding="utf-8"
    )
    job_id = "f13ecf06-9ac4-486f-a5cd-b4959f02bc76"
    database.create_job(
        job_id=job_id,
        original_video_name="在线视频.mp4",
        video_size_bytes=0,
        video_sha256="",
        video_path=job_dir / "input.mp4",
        lyrics_source=None,
        lyrics_path=None,
    )
    return database, job_dir, job_id


def test_pipeline_downloads_the_video_before_anything_else(tmp_path: Path) -> None:
    database, job_dir, job_id = link_job(tmp_path)
    downloader = StubDownloader()

    TranscriptionPipeline(
        database=database,
        extractor=Extractor(),
        transcriber=Transcriber(),
        video_downloader=downloader,
    ).process(job_id)

    job = database.get_job(job_id)
    assert job is not None and job["status"] == "TRANSCRIBED"
    assert downloader.urls == ["https://youtu.be/abc123"]
    assert job["video_size_bytes"] == len(b"downloaded-video")
    assert job["video_sha256"] == hashlib.sha256(b"downloaded-video").hexdigest()
    # characters that are illegal in file names never reach the display name
    assert job["original_video_name"] == "My Song TitleVersion.mp4"


def test_a_failed_download_fails_the_job_at_the_download_stage(
    tmp_path: Path,
) -> None:
    database, _, job_id = link_job(tmp_path)

    with pytest.raises(VideoDownloadError):
        TranscriptionPipeline(
            database=database,
            extractor=Extractor(),
            transcriber=Transcriber(),
            video_downloader=StubDownloader(fail=True),
        ).process(job_id)

    job = database.get_job(job_id)
    assert job is not None
    assert (job["status"], job["stage"], job["error_code"]) == (
        "FAILED",
        "DOWNLOADING_VIDEO",
        "VIDEO_DOWNLOAD_FAILED",
    )
