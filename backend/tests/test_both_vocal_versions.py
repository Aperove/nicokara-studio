from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai.whisper import (
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
)
from app.alignment.aligner import LyricTimelineAligner
from app.core.config import Settings
from app.core.database import Database
from app.lyrics.models import LyricDocument, LyricLine, LyricToken
from app.main import create_app
from app.subtitle.ass_generator import AssGenerator
from app.tasks.pipeline import TranscriptionPipeline
from app.video.download import (
    UnsupportedVideoUrl,
    YtDlpVideoDownloader,
    validate_video_url,
)
from app.video.rendering import FFmpegVideoRenderer, VideoRenderingError


ROWS = ["あいうえお", "かきくけこ"]


def lyrics_of(rows: list[str]) -> LyricDocument:
    return LyricDocument(
        provider="local",
        source_text="\n".join(rows),
        lines=[LyricLine(row, row, row, [LyricToken(row, row)]) for row in rows],
    )


class Steps:
    def extract(self, video, audio) -> None:
        audio.write_bytes(b"wav")

    def extract_stereo(self, video, stereo) -> None:
        stereo.write_bytes(b"stereo")

    def extract_vocal_stem(self, stereo, instrumental, vocals) -> None:
        vocals.write_bytes(b"vocals")

    def transcribe(self, audio, **options) -> TranscriptDocument:
        words = [
            TranscriptWord(kana, 5_000 + i * 400, 5_400 + i * 400, 0.9)
            for i, kana in enumerate("".join(ROWS))
        ]
        return TranscriptDocument(
            "ja", 1.0, 30.0, "",
            [TranscriptSegment(0, "", 5_000, 9_000, -0.1, 0.0, words)],
        )

    def process(self, text: str) -> LyricDocument:
        return lyrics_of(ROWS)


class Remover:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def remove_vocals(self, stereo: Path, instrumental: Path) -> None:
        if self.fail:
            raise RuntimeError("model missing")
        instrumental.write_bytes(b"instrumental")


class Renderer:
    def __init__(self, *, swap_fails: bool = False) -> None:
        self.swap_fails = swap_fails
        self.renders: list[dict] = []
        self.swaps: list[tuple[str, str]] = []

    def render(self, video, subtitle, output, **options) -> None:
        self.renders.append(options)
        output.write_bytes(b"on-vocal-video")

    def replace_audio(self, video: Path, audio: Path, output: Path) -> None:
        if self.swap_fails:
            raise VideoRenderingError("muxing failed")
        self.swaps.append((video.name, audio.name))
        output.write_bytes(b"off-vocal-video")


def run_job(tmp_path: Path, mode: str, renderer: Renderer, remover: Remover):
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_dir.mkdir(parents=True)
    video_path = job_dir / "input.mp4"
    video_path.write_bytes(b"video")
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("\n".join(ROWS), encoding="utf-8")
    job_id = "f13ecf06-9ac4-486f-a5cd-b4959f02bc76"
    database.create_job(
        job_id=job_id,
        original_video_name="song.mp4",
        video_size_bytes=5,
        video_sha256="abc",
        video_path=video_path,
        lyrics_source="text",
        lyrics_path=lyrics_path,
        vocal_mode=mode,
    )
    steps = Steps()
    pipeline = TranscriptionPipeline(
        database=database,
        extractor=steps,
        transcriber=steps,
        vocal_remover=remover,
        lyric_processor=steps,
        aligner=LyricTimelineAligner(),
        subtitle_generator=AssGenerator(),
        video_renderer=renderer,
        transcribe_vocal_stem=True,
    )
    pipeline.process(job_id)
    return pipeline, database, job_dir, job_id


def test_both_versions_come_from_a_single_render(tmp_path: Path) -> None:
    renderer = Renderer()

    _, database, job_dir, job_id = run_job(tmp_path, "both", renderer, Remover())

    job = database.get_job(job_id)
    assert job is not None and job["status"] == "COMPLETED"
    # the subtitles are burned in once; the off-vocal file only swaps audio
    assert len(renderer.renders) == 1
    assert renderer.renders[0]["vocal_mode"] == "on"
    assert renderer.swaps == [("final_karaoke.mp4", "audio_instrumental.wav")]
    assert (job_dir / "final_karaoke.mp4").read_bytes() == b"on-vocal-video"
    assert (job_dir / "final_karaoke_off.mp4").read_bytes() == b"off-vocal-video"
    assert job["output_off_path"] == str(job_dir / "final_karaoke_off.mp4")


@pytest.mark.parametrize("problem", ["separation", "muxing"])
def test_a_missing_off_vocal_version_never_fails_the_job(
    tmp_path: Path, problem: str
) -> None:
    renderer = Renderer(swap_fails=problem == "muxing")
    remover = Remover(fail=problem == "separation")

    _, database, job_dir, job_id = run_job(tmp_path, "both", renderer, remover)

    job = database.get_job(job_id)
    assert job is not None and job["status"] == "COMPLETED"
    assert (job_dir / "final_karaoke.mp4").is_file()
    assert not (job_dir / "final_karaoke_off.mp4").exists()
    assert job["output_off_path"] is None


def test_regenerating_refreshes_both_versions(tmp_path: Path) -> None:
    renderer = Renderer()
    pipeline, database, job_dir, job_id = run_job(
        tmp_path, "both", renderer, Remover()
    )
    (job_dir / "final_karaoke_off.mp4").write_bytes(b"stale")

    database.update_job_state(
        job_id, status="UPLOADED", stage="RENDER_QUEUED", progress=96
    )
    pipeline.process(job_id)

    job = database.get_job(job_id)
    assert job is not None and job["status"] == "COMPLETED"
    assert len(renderer.renders) == 2 and len(renderer.swaps) == 2
    assert (job_dir / "final_karaoke_off.mp4").read_bytes() == b"off-vocal-video"
    assert job["output_off_path"]


def test_single_mode_jobs_keep_their_old_behaviour(tmp_path: Path) -> None:
    renderer = Renderer()

    _, database, job_dir, job_id = run_job(tmp_path, "off", renderer, Remover())

    job = database.get_job(job_id)
    assert job is not None and job["status"] == "COMPLETED"
    assert renderer.renders[0]["vocal_mode"] == "off"
    assert renderer.swaps == []
    assert job["output_off_path"] is None


def test_replace_audio_copies_the_picture_and_encodes_only_audio(
    tmp_path: Path,
) -> None:
    recorder = tmp_path / "fake_ffmpeg.py"
    recorder.write_text(
        "import json, sys\n"
        "json.dump(sys.argv[1:], open(sys.argv[-1] + '.args', 'w'))\n"
        "open(sys.argv[-1], 'wb').write(b'muxed')\n",
        encoding="utf-8",
    )
    output = tmp_path / "off.mp4"

    FFmpegVideoRenderer(command=(sys.executable, str(recorder))).replace_audio(
        tmp_path / "on.mp4", tmp_path / "instrumental.wav", output
    )

    arguments = json.loads((tmp_path / "off.mp4.args").read_text("utf-8"))
    assert output.read_bytes() == b"muxed"
    assert arguments[arguments.index("-c:v") + 1] == "copy"
    assert arguments[arguments.index("-c:a") + 1] == "aac"
    assert ["-map", "0:v:0", "-map", "1:a:0"] == arguments[
        arguments.index("-map") : arguments.index("-map") + 4
    ]


def test_an_existing_database_gains_the_off_vocal_column(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL,"
            " stage TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,"
            " original_video_name TEXT NOT NULL, video_size_bytes INTEGER NOT NULL,"
            " video_sha256 TEXT NOT NULL, video_path TEXT NOT NULL,"
            " lyrics_source TEXT, lyrics_path TEXT, output_path TEXT,"
            " error_code TEXT, error_message TEXT,"
            " created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
    assert "output_off_path" in columns


class RecordingRunner:
    can_accept = True

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def enqueue(self, job_id: str, **_: object) -> None:
        pass


def test_api_defaults_to_both_and_serves_each_version(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    mp4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"video-data"
    with TestClient(create_app(settings, runner=RecordingRunner())) as client:
        job = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", mp4, "video/mp4")},
            data={"lyrics_text": "あ"},
        ).json()
        assert job["vocal_mode"] == "both"
        assert job["off_vocal_available"] is False

        base = f"/api/v1/jobs/{job['id']}"
        assert client.get(f"{base}/result", params={"vocal": "off"}).status_code == 409

        job_dir = tmp_path / "jobs" / job["id"]
        (job_dir / "final_karaoke.mp4").write_bytes(b"on")
        (job_dir / "final_karaoke_off.mp4").write_bytes(b"off")
        client.app.state.database.update_job_state(
            job["id"],
            status="COMPLETED",
            stage="VIDEO_RENDERING_COMPLETE",
            progress=100,
            output_path=job_dir / "final_karaoke.mp4",
            output_off_path=job_dir / "final_karaoke_off.mp4",
        )

        assert client.get(base).json()["off_vocal_available"] is True
        assert client.get(f"{base}/result").content == b"on"
        assert client.get(f"{base}/result", params={"vocal": "off"}).content == b"off"
        download = client.get(f"{base}/download", params={"vocal": "off"})
        assert "final_karaoke_off_vocal.mp4" in download.headers["content-disposition"]
        assert client.get(f"{base}/result", params={"vocal": "x"}).status_code == 422


def test_only_youtube_links_are_allowed_by_default() -> None:
    hosts = Settings().video_url_host_list
    assert hosts == ["youtube.com", "youtu.be"]
    assert validate_video_url("https://www.youtube.com/watch?v=abc", hosts)
    # Other video sites were left out on purpose; an operator who wants one
    # has to add it to NICOKARA_VIDEO_URL_HOSTS explicitly.
    for url in (
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "https://b23.tv/abc123",
        "https://www.nicovideo.jp/watch/sm9",
    ):
        with pytest.raises(UnsupportedVideoUrl):
            validate_video_url(url, hosts)


def test_browser_cookies_are_opt_in_and_limited_to_known_browsers(
    tmp_path: Path,
) -> None:
    recorder = tmp_path / "fake_yt_dlp.py"
    recorder.write_text(
        "import json, sys\n"
        "args = sys.argv[1:]\n"
        "out = args[args.index('--output') + 1]\n"
        "json.dump(args, open(out + '.args', 'w'))\n"
        "open(out, 'wb').write(b'video')\n"
        "print('Title')\n",
        encoding="utf-8",
    )
    target = tmp_path / "input.mp4"

    def arguments(**options) -> list[str]:
        YtDlpVideoDownloader(
            allowed_hosts=["youtube.com"],
            command=(sys.executable, str(recorder)),
            **options,
        ).download("https://www.youtube.com/watch?v=abc123", target)
        return json.loads(Path(str(target) + ".args").read_text("utf-8"))

    assert "--cookies-from-browser" not in arguments()
    with_cookies = arguments(cookies_from_browser=" Edge ")
    assert with_cookies[with_cookies.index("--cookies-from-browser") + 1] == "edge"
    with pytest.raises(ValueError):
        YtDlpVideoDownloader(
            allowed_hosts=["youtube.com"], cookies_from_browser="--exec calc"
        )
