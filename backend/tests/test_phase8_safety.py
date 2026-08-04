from __future__ import annotations

from datetime import UTC, datetime, timedelta
import asyncio
from pathlib import Path
import threading

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.database import Database
from app.main import create_app


def create_database_job(
    database: Database,
    storage_dir: Path,
    job_id: str,
) -> Path:
    job_dir = storage_dir / job_id
    job_dir.mkdir(parents=True)
    video_path = job_dir / "input.mp4"
    video_path.write_bytes(b"video")
    database.create_job(
        job_id=job_id,
        original_video_name="song.mp4",
        video_size_bytes=5,
        video_sha256="sha",
        video_path=video_path,
        lyrics_source="text",
        lyrics_path=None,
    )
    return job_dir


def test_api_responses_include_browser_security_headers(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == (
        "camera=(), microphone=(), geolocation=()"
    )


def test_queue_backpressure_rejects_upload_before_writing_files(
    tmp_path: Path,
) -> None:
    class FullRunner:
        can_accept = False

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )
    with TestClient(create_app(settings, runner=FullRunner())) as client:
        response = client.post(
            "/api/v1/jobs",
            files={
                "video": (
                    "song.mp4",
                    b"\x00\x00\x00\x18ftypisomvideo",
                    "video/mp4",
                )
            },
            data={"lyrics_text": "歌詞"},
        )

    assert response.status_code == 503
    assert list(settings.storage_dir.iterdir()) == []


def test_cleanup_deletes_only_expired_terminal_jobs(tmp_path: Path) -> None:
    from app.tasks.cleanup import JobCleanupService

    database = Database(tmp_path / "data" / "jobs.sqlite3")
    database.path.parent.mkdir(parents=True)
    database.initialize()
    storage_dir = tmp_path / "jobs"
    completed_dir = create_database_job(
        database,
        storage_dir,
        "00000000-0000-0000-0000-000000000001",
    )
    active_dir = create_database_job(
        database,
        storage_dir,
        "00000000-0000-0000-0000-000000000002",
    )
    database.update_job_state(
        completed_dir.name,
        status="COMPLETED",
        stage="VIDEO_RENDERING_COMPLETE",
        progress=100,
    )
    database.update_job_state(
        active_dir.name,
        status="PROCESSING",
        stage="TRANSCRIBING",
        progress=40,
    )
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    with database.connect() as connection:
        connection.execute("UPDATE jobs SET updated_at = ?", (old,))

    deleted = JobCleanupService(
        database=database,
        storage_dir=storage_dir,
        retention_hours=24,
    ).run_once()

    assert deleted == [completed_dir.name]
    assert not completed_dir.exists()
    assert database.get_job(completed_dir.name) is None
    assert active_dir.exists()
    assert database.get_job(active_dir.name) is not None


def test_restart_marks_interrupted_jobs_failed_and_requeues_uploads(
    tmp_path: Path,
) -> None:
    class RecordingRunner:
        can_accept = True

        def __init__(self) -> None:
            self.job_ids: list[str] = []

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def enqueue(self, job_id: str) -> None:
            self.job_ids.append(job_id)

    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    settings.prepare_directories()
    database = Database(settings.database_path)
    database.initialize()
    uploaded_id = "00000000-0000-0000-0000-000000000003"
    interrupted_id = "00000000-0000-0000-0000-000000000004"
    create_database_job(database, settings.storage_dir, uploaded_id)
    create_database_job(database, settings.storage_dir, interrupted_id)
    database.update_job_state(
        interrupted_id,
        status="PROCESSING",
        stage="RENDERING_VIDEO",
        progress=98,
    )

    runner = RecordingRunner()
    with TestClient(create_app(settings, runner=runner)):
        pass

    assert runner.job_ids == [uploaded_id]
    interrupted = database.get_job(interrupted_id)
    assert interrupted is not None
    assert interrupted["status"] == "FAILED"
    assert interrupted["error_code"] == "SERVICE_RESTARTED"


def test_startup_cleanup_removes_expired_completed_job(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=True,
        job_retention_hours=24,
    )
    settings.prepare_directories()
    database = Database(settings.database_path)
    database.initialize()
    job_id = "00000000-0000-0000-0000-000000000005"
    job_dir = create_database_job(database, settings.storage_dir, job_id)
    database.update_job_state(
        job_id,
        status="COMPLETED",
        stage="VIDEO_RENDERING_COMPLETE",
        progress=100,
    )
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    with database.connect() as connection:
        connection.execute(
            "UPDATE jobs SET updated_at = ? WHERE id = ?",
            (old, job_id),
        )

    with TestClient(create_app(settings)):
        pass

    assert not job_dir.exists()
    assert database.get_job(job_id) is None


def test_sqlite_uses_wal_busy_timeout_and_status_index(tmp_path: Path) -> None:
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()

    with database.connect() as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        indexes = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }

    assert journal_mode.lower() == "wal"
    assert busy_timeout >= 5000
    assert "idx_jobs_status_updated" in indexes


def test_download_rejects_database_path_outside_job_directory(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/jobs",
            files={
                "video": (
                    "song.mp4",
                    b"\x00\x00\x00\x18ftypisomvideo",
                    "video/mp4",
                )
            },
            data={"lyrics_text": "歌詞"},
        )
        job_id = response.json()["id"]
        outside = tmp_path / "outside.json"
        outside.write_text('{"secret": true}', encoding="utf-8")
        with client.app.state.database.connect() as connection:
            connection.execute(
                "UPDATE jobs SET transcript_path = ? WHERE id = ?",
                (str(outside), job_id),
            )

        download = client.get(f"/api/v1/jobs/{job_id}/transcript")

    assert download.status_code == 410


def test_periodic_cleanup_runs_while_service_is_alive() -> None:
    from app.tasks.cleanup import PeriodicCleanupRunner

    class RecordingCleanup:
        def __init__(self) -> None:
            self.calls = 0
            self.called = threading.Event()

        def run_once(self) -> list[str]:
            self.calls += 1
            self.called.set()
            return []

    async def scenario() -> int:
        cleanup = RecordingCleanup()
        runner = PeriodicCleanupRunner(
            cleanup,
            interval_seconds=0.01,
        )
        await runner.start()
        completed = await asyncio.to_thread(cleanup.called.wait, 1)
        await runner.stop()
        assert completed
        return cleanup.calls

    assert asyncio.run(scenario()) >= 1


def test_upload_rate_limiter_blocks_repeated_requests() -> None:
    from app.core.rate_limit import UploadRateLimiter

    limiter = UploadRateLimiter(
        max_requests=2,
        window_seconds=60,
    )

    assert limiter.allow("127.0.0.1", now=100)
    assert limiter.allow("127.0.0.1", now=101)
    assert not limiter.allow("127.0.0.1", now=102)
    assert limiter.allow("127.0.0.1", now=161)


def test_api_rate_limits_upload_creation(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        max_uploads_per_hour=1,
    )
    upload = {
        "video": (
            "song.mp4",
            b"\x00\x00\x00\x18ftypisomvideo",
            "video/mp4",
        )
    }

    with TestClient(create_app(settings)) as client:
        first = client.post(
            "/api/v1/jobs",
            files=upload,
            data={"lyrics_text": "歌詞"},
        )
        second = client.post(
            "/api/v1/jobs",
            files=upload,
            data={"lyrics_text": "歌詞"},
        )

    assert first.status_code == 201
    assert second.status_code == 429
    assert second.headers["retry-after"]
