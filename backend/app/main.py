from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.jobs import router as jobs_router
from app.ai.deepseek import DeepSeekClient
from app.ai.whisper import FasterWhisperTranscriber
from app.alignment.aligner import LyricTimelineAligner
from app.alignment.karatimer_aligner import KaratimerAligner
from app.alignment.refiner import QwenForcedAlignmentRefiner
from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.rate_limit import UploadRateLimiter
from app.schemas.jobs import CapabilitiesResponse, HealthResponse
from app.lyrics.processor import (
    DeepSeekLyricProcessor,
    LocalJapaneseLyricProcessor,
    OpenJTalkLyricProcessor,
    ResilientLyricProcessor,
    openjtalk_available,
)
from app.tasks.pipeline import TranscriptionPipeline
from app.tasks.runner import LocalTaskRunner
from app.tasks.cleanup import JobCleanupService, PeriodicCleanupRunner
from app.subtitle.ass_generator import AssGenerator
from app.video.audio import FFmpegAudioExtractor
from app.video.download import YtDlpVideoDownloader
from app.video.rendering import FFmpegVideoRenderer
from app.vocal.mdx import MDXNetVocalRemover
from app.vocal.remover import VocalRemover
from app.vocal.roformer import RoformerVocalStemSeparator


def expose_ffmpeg_on_path(ffmpeg_path: str) -> None:
    """Let libraries that shell out to a bare ``ffmpeg`` find ours.

    audio-separator (and pydub underneath it) ignore NICOKARA_FFMPEG_PATH
    and run ``ffmpeg`` from PATH, which fails when only an explicit binary
    path is configured.
    """
    candidate = Path(ffmpeg_path)
    if not candidate.is_file():
        return
    directory = str(candidate.resolve().parent)
    entries = os.environ.get("PATH", "").split(os.pathsep)
    if directory not in entries:
        os.environ["PATH"] = os.pathsep.join([directory, *entries])


def build_alignment_refiner(settings: Settings):
    if settings.forced_aligner_python is None:
        return None
    return QwenForcedAlignmentRefiner(
        python_command=(str(settings.forced_aligner_python),),
        model=settings.forced_aligner_model,
        device=settings.forced_aligner_device,
        timeout_seconds=settings.forced_aligner_timeout_seconds,
    )


def build_primary_aligner(settings: Settings):
    if settings.karatimer_python is None:
        return None
    return KaratimerAligner(
        python_command=(str(settings.karatimer_python),),
        device=settings.karatimer_device,
        timeout_seconds=settings.karatimer_timeout_seconds,
    )


def build_vocal_stem_separator(settings: Settings):
    if settings.vocal_stem_python is None:
        return None
    return RoformerVocalStemSeparator(
        python_command=(str(settings.vocal_stem_python),),
        model_dir=settings.vocal_removal_model_dir,
        model=settings.vocal_stem_model,
        timeout_seconds=settings.vocal_stem_timeout_seconds,
    )


def build_vocal_remover(settings: Settings):
    if settings.vocal_removal_backend == "stft":
        return VocalRemover()
    return MDXNetVocalRemover(
        model_dir=settings.vocal_removal_model_dir,
        model_filename=settings.vocal_removal_model,
    )


def create_app(
    settings: Settings | None = None,
    *,
    runner: Any | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolved_settings.prepare_directories()
        expose_ffmpeg_on_path(resolved_settings.ffmpeg_path)
        database = Database(resolved_settings.database_path)
        database.initialize()
        database.recover_interrupted_jobs()
        cleanup_runner = None
        if resolved_settings.cleanup_enabled:
            cleanup_runner = PeriodicCleanupRunner(
                JobCleanupService(
                    database=database,
                    storage_dir=resolved_settings.storage_dir,
                    retention_hours=resolved_settings.job_retention_hours,
                ),
                interval_seconds=(
                    resolved_settings.cleanup_interval_seconds
                ),
            )
        active_runner = runner
        if active_runner is None and resolved_settings.processing_enabled:
            local_lyric_processor = (
                OpenJTalkLyricProcessor()
                if openjtalk_available()
                else LocalJapaneseLyricProcessor()
            )
            if resolved_settings.deepseek_api_key is not None:
                lyric_processor = ResilientLyricProcessor(
                    primary=DeepSeekLyricProcessor(
                        client=DeepSeekClient(
                            api_key=resolved_settings.deepseek_api_key.get_secret_value(),
                            base_url=resolved_settings.deepseek_base_url,
                            model=resolved_settings.deepseek_model,
                            timeout_seconds=resolved_settings.deepseek_timeout_seconds,
                        )
                    ),
                    fallback=local_lyric_processor,
                )
            else:
                lyric_processor = local_lyric_processor
            active_runner = LocalTaskRunner(
                TranscriptionPipeline(
                    database=database,
                    extractor=FFmpegAudioExtractor(
                        command=(resolved_settings.ffmpeg_path,),
                        timeout_seconds=resolved_settings.ffmpeg_timeout_seconds,
                    ),
                    transcriber=FasterWhisperTranscriber(
                        model_name=resolved_settings.whisper_model,
                        device=resolved_settings.whisper_device,
                        compute_type=resolved_settings.whisper_compute_type,
                    ),
                    vocal_remover=build_vocal_remover(
                        resolved_settings
                    ),
                    lyric_processor=lyric_processor,
                    aligner=LyricTimelineAligner(),
                    subtitle_generator=AssGenerator(),
                    video_renderer=FFmpegVideoRenderer(
                        command=(resolved_settings.ffmpeg_path,),
                        timeout_seconds=(
                            resolved_settings.video_render_timeout_seconds
                        ),
                        preset=resolved_settings.video_render_preset,
                        crf=resolved_settings.video_render_crf,
                    ),
                    transcribe_vocal_stem=(
                        resolved_settings.transcribe_vocal_stem
                    ),
                    lyrics_hint=resolved_settings.whisper_lyrics_hint,
                    alignment_refiner=build_alignment_refiner(
                        resolved_settings
                    ),
                    vocal_stem_separator=build_vocal_stem_separator(
                        resolved_settings
                    ),
                    primary_aligner=build_primary_aligner(resolved_settings),
                    video_downloader=YtDlpVideoDownloader(
                        allowed_hosts=resolved_settings.video_url_host_list,
                        ffmpeg_path=resolved_settings.ffmpeg_path,
                        max_bytes=resolved_settings.max_video_bytes,
                        timeout_seconds=(
                            resolved_settings.video_download_timeout_seconds
                        ),
                        cookies_from_browser=(
                            resolved_settings.video_cookies_from_browser
                        ),
                    ),
                ),
                max_pending_jobs=resolved_settings.max_pending_jobs,
            )
        app.state.settings = resolved_settings
        app.state.database = database
        app.state.runner = active_runner
        app.state.upload_limiter = UploadRateLimiter(
            max_requests=resolved_settings.max_uploads_per_hour,
            window_seconds=3600,
        )
        if cleanup_runner is not None:
            await cleanup_runner.start()
        if active_runner is not None:
            await active_runner.start()
            for pending_job_id in database.list_job_ids(
                status="UPLOADED"
            ):
                if isinstance(active_runner, LocalTaskRunner):
                    await active_runner.enqueue(pending_job_id, force=True)
                elif getattr(active_runner, "can_accept", True):
                    await active_runner.enqueue(pending_job_id)
        try:
            yield
        finally:
            if active_runner is not None:
                await active_runner.stop()
            if cleanup_runner is not None:
                await cleanup_runner.stop()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        return response
    app.include_router(jobs_router, prefix=resolved_settings.api_prefix)

    @app.get(
        f"{resolved_settings.api_prefix}/capabilities",
        response_model=CapabilitiesResponse,
        tags=["health"],
    )
    def capabilities() -> CapabilitiesResponse:
        return CapabilitiesResponse(
            video_link_hosts=resolved_settings.video_url_host_list,
            job_listing=resolved_settings.job_listing_enabled,
        )

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    return app


app = create_app()
