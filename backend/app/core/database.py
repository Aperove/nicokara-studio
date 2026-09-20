from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    original_video_name TEXT NOT NULL,
    video_size_bytes INTEGER NOT NULL,
    video_sha256 TEXT NOT NULL,
    video_path TEXT NOT NULL,
    lyrics_source TEXT,
    lyrics_path TEXT,
    vocal_mode TEXT NOT NULL DEFAULT 'on',
    audio_path TEXT,
    transcript_path TEXT,
    lyrics_processed_path TEXT,
    timeline_path TEXT,
    ass_path TEXT,
    output_path TEXT,
    output_off_path TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            for name in (
                "vocal_mode",
                "audio_path",
                "transcript_path",
                "lyrics_processed_path",
                "timeline_path",
                "ass_path",
                "output_path",
                "output_off_path",
            ):
                if name not in columns:
                    connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT")
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_status_updated
                ON jobs(status, updated_at)
                """
            )

    def create_job(
        self,
        *,
        job_id: str,
        original_video_name: str,
        video_size_bytes: int,
        video_sha256: str,
        video_path: Path,
        lyrics_source: str | None,
        lyrics_path: Path | None,
        vocal_mode: str = "on",
    ) -> dict:
        timestamp = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, stage, progress, original_video_name,
                    video_size_bytes, video_sha256, video_path,
                    lyrics_source, lyrics_path, vocal_mode,
                    created_at, updated_at
                )
                VALUES (?, 'UPLOADED', 'UPLOAD_COMPLETE', 100,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    original_video_name,
                    video_size_bytes,
                    video_sha256,
                    str(video_path),
                    lyrics_source,
                    str(lyrics_path) if lyrics_path else None,
                    vocal_mode,
                    timestamp,
                    timestamp,
                ),
            )
        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError("Created job could not be read back")
        return job

    def get_job(self, job_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_job_state(
        self,
        job_id: str,
        *,
        status: str,
        stage: str,
        progress: int,
        audio_path: Path | None = None,
        transcript_path: Path | None = None,
        lyrics_processed_path: Path | None = None,
        timeline_path: Path | None = None,
        ass_path: Path | None = None,
        output_path: Path | None = None,
        output_off_path: Path | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        assignments = [
            "status = ?",
            "stage = ?",
            "progress = ?",
            "error_code = ?",
            "error_message = ?",
            "updated_at = ?",
        ]
        values: list[object] = [
            status,
            stage,
            progress,
            error_code,
            error_message,
            utc_now(),
        ]
        if audio_path is not None:
            assignments.append("audio_path = ?")
            values.append(str(audio_path))
        if transcript_path is not None:
            assignments.append("transcript_path = ?")
            values.append(str(transcript_path))
        if lyrics_processed_path is not None:
            assignments.append("lyrics_processed_path = ?")
            values.append(str(lyrics_processed_path))
        if timeline_path is not None:
            assignments.append("timeline_path = ?")
            values.append(str(timeline_path))
        if ass_path is not None:
            assignments.append("ass_path = ?")
            values.append(str(ass_path))
        if output_path is not None:
            assignments.append("output_path = ?")
            values.append(str(output_path))
            # Every render decides anew whether an off-vocal version exists.
            assignments.append("output_off_path = ?")
            values.append(str(output_off_path) if output_off_path else None)
        values.append(job_id)

        with self.connect() as connection:
            cursor = connection.execute(
                f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Job not found: {job_id}")

    def list_jobs(self, *, limit: int = 20) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_job_video(
        self,
        job_id: str,
        *,
        original_video_name: str,
        video_size_bytes: int,
        video_sha256: str,
    ) -> None:
        """Record a video that arrived after the job was created."""
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET original_video_name = ?, video_size_bytes = ?,
                    video_sha256 = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    original_video_name,
                    video_size_bytes,
                    video_sha256,
                    utc_now(),
                    job_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Job not found: {job_id}")

    def list_job_ids(self, *, status: str) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id FROM jobs
                WHERE status = ?
                ORDER BY created_at ASC
                """,
                (status,),
            ).fetchall()
        return [row["id"] for row in rows]

    def recover_interrupted_jobs(self) -> list[str]:
        timestamp = utc_now()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM jobs WHERE status = 'PROCESSING'"
            ).fetchall()
            connection.execute(
                """
                UPDATE jobs
                SET status = 'FAILED',
                    error_code = 'SERVICE_RESTARTED',
                    error_message = ?,
                    updated_at = ?
                WHERE status = 'PROCESSING'
                """,
                (
                    "Processing was interrupted by a service restart. "
                    "Create a new task to retry.",
                    timestamp,
                ),
            )
        return [row["id"] for row in rows]

    def list_expired_terminal_job_ids(self, *, cutoff: str) -> list[str]:
        terminal_statuses = (
            "COMPLETED",
            "FAILED",
            "TRANSCRIBED",
            "LYRICS_PROCESSED",
            "ALIGNED",
            "SUBTITLE_GENERATED",
            "AWAITING_REVIEW",
        )
        placeholders = ", ".join("?" for _ in terminal_statuses)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id FROM jobs
                WHERE status IN ({placeholders})
                  AND updated_at < ?
                ORDER BY updated_at ASC
                """,
                (*terminal_statuses, cutoff),
            ).fetchall()
        return [row["id"] for row in rows]

    def delete_job(self, job_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM jobs WHERE id = ?",
                (job_id,),
            )
