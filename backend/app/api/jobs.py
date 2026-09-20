from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from app.ai.whisper import TranscriptDocument
from app.alignment.editing import TimelineEditError, apply_line_edits
from app.alignment.models import LyricTimeline
from app.alignment.refiner import realign_lines
from app.core.config import Settings
from app.core.database import Database
from app.lyrics.models import LyricDocument
from app.lyrics.readings import ReadingEditError, apply_reading_edits
from app.schemas.jobs import JobResponse
from app.services.uploads import save_lyrics, save_mp4
from app.subtitle.style import SubtitleStyle
from app.tasks.runner import QueueCapacityError
from app.video.download import UnsupportedVideoUrl, validate_video_url


router = APIRouter(prefix="/jobs", tags=["jobs"])


def safe_display_name(filename: str | None) -> str:
    candidate = Path(filename or "input.mp4").name
    candidate = re.sub(r"[\x00-\x1f\x7f]", "", candidate).strip()
    return candidate[:255] or "input.mp4"


RESTYLABLE_STATUSES = {
    "COMPLETED",
    "SUBTITLE_GENERATED",
    "FAILED",
    "AWAITING_REVIEW",
}
AUDIO_TRACKS = {"mix": "audio.wav", "vocals": "audio_vocals.wav"}
SOURCE_URL_FILE = "source_url.txt"
CLEAN_VOCALS = "audio_vocals_clean.wav"


class LineEdit(BaseModel):
    index: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


class TimelineEdits(BaseModel):
    lines: list[LineEdit] = Field(max_length=2000)


class ReadingEdit(BaseModel):
    line: int = Field(ge=0)
    token: int = Field(ge=0)
    reading: str = Field(min_length=1, max_length=64)


class ReadingEdits(BaseModel):
    edits: list[ReadingEdit] = Field(min_length=1, max_length=500)


class RefineRequest(BaseModel):
    lines: list[int] = Field(min_length=1, max_length=200)


def parse_style(raw: str | None) -> SubtitleStyle | None:
    if raw is None or not raw.strip():
        return None
    try:
        return SubtitleStyle.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="字幕样式参数无效",
        ) from exc


def write_style(job_dir: Path, style: SubtitleStyle) -> None:
    (job_dir / "style.json").write_text(
        json.dumps(style.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def services(request: Request) -> tuple[Settings, Database]:
    return request.app.state.settings, request.app.state.database


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    request: Request,
    video: UploadFile | None = File(default=None),
    video_url: str | None = Form(default=None),
    lyrics_text: str | None = Form(default=None),
    lyrics_file: UploadFile | None = File(default=None),
    vocal_mode: Literal["on", "off", "both"] = Form(default="both"),
    style: str | None = Form(default=None),
    review: bool = Form(default=False),
) -> JobResponse:
    settings, database = services(request)
    try:
        subtitle_style = parse_style(style)
    except HTTPException:
        if video is not None:
            await video.close()
        if lyrics_file:
            await lyrics_file.close()
        raise
    client_key = request.client.host if request.client else "unknown"
    limiter = request.app.state.upload_limiter
    if not limiter.allow(client_key):
        if video is not None:
            await video.close()
        if lyrics_file:
            await lyrics_file.close()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Upload rate limit exceeded. Try again later.",
            headers={"Retry-After": "3600"},
        )
    runner = getattr(request.app.state, "runner", None)
    if runner is not None and not getattr(runner, "can_accept", True):
        if video is not None:
            await video.close()
        if lyrics_file:
            await lyrics_file.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Processing queue is full. Try again later.",
            headers={"Retry-After": "60"},
        )
    job_id = str(uuid4())
    job_dir = settings.storage_dir / job_id
    video_path = job_dir / "input.mp4"
    lyrics_path = job_dir / "lyrics.txt"

    source_url: str | None = None
    if (video is None) == (not (video_url or "").strip()):
        if video is not None:
            await video.close()
        if lyrics_file:
            await lyrics_file.close()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="请上传视频文件，或填写视频链接（二选一）",
        )
    if video is None:
        if not settings.video_url_host_list:
            if lyrics_file:
                await lyrics_file.close()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="本服务未开放视频链接，请上传视频文件",
            )
        try:
            source_url = validate_video_url(
                video_url or "", settings.video_url_host_list
            )
        except UnsupportedVideoUrl as exc:
            if lyrics_file:
                await lyrics_file.close()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="不支持这个视频链接，目前只支持："
                + "、".join(settings.video_url_host_list),
            ) from exc

    original_name = safe_display_name(
        video.filename if video is not None else "在线视频.mp4"
    )
    if Path(original_name).suffix.lower() != ".mp4":
        if video is not None:
            await video.close()
        if lyrics_file:
            await lyrics_file.close()
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="第一版仅支持 .mp4 视频",
        )

    created = False
    try:
        if video is not None:
            saved = await save_mp4(
                video,
                video_path,
                max_bytes=settings.max_video_bytes,
            )
            size_bytes, sha256 = saved.size_bytes, saved.sha256
        else:
            # The pipeline downloads the video as its first stage.
            job_dir.mkdir(parents=True, exist_ok=False)
            (job_dir / SOURCE_URL_FILE).write_text(
                f"{source_url}\n", encoding="utf-8"
            )
            size_bytes, sha256 = 0, ""
        lyrics_source = await save_lyrics(
            lyrics_text=lyrics_text,
            lyrics_file=lyrics_file,
            destination=lyrics_path,
            max_bytes=settings.max_lyrics_bytes,
        )
        if subtitle_style is not None:
            write_style(job_dir, subtitle_style)
        if review:
            (job_dir / "options.json").write_text(
                json.dumps({"review_before_render": True}) + "\n",
                encoding="utf-8",
            )
        job = database.create_job(
            job_id=job_id,
            original_video_name=original_name,
            video_size_bytes=size_bytes,
            video_sha256=sha256,
            video_path=video_path,
            lyrics_source=lyrics_source,
            lyrics_path=lyrics_path if lyrics_source else None,
            vocal_mode=vocal_mode,
        )
        created = True
        if runner is not None:
            await runner.enqueue(job_id)
    except QueueCapacityError as exc:
        if created:
            database.delete_job(job_id)
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Processing queue is full. Try again later.",
            headers={"Retry-After": "60"},
        ) from exc
    except Exception:
        if created:
            database.delete_job(job_id)
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    return JobResponse.model_validate(job)


@router.get("", response_model=list[JobResponse])
def list_jobs(request: Request, limit: int = 20) -> list[JobResponse]:
    settings, database = services(request)
    if not settings.job_listing_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="本服务未开放任务列表",
        )
    jobs = database.list_jobs(limit=max(1, min(limit, 100)))
    return [JobResponse.model_validate(job) for job in jobs]


def existing_job(request: Request, job_id: str) -> dict:
    try:
        UUID(job_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc
    _, database = services(request)
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
    return job


def job_artifact(
    request: Request,
    job_id: str,
    *,
    field: str,
    not_ready: str,
    missing: str,
) -> Path:
    settings, _ = services(request)
    job = existing_job(request, job_id)
    path_value = job.get(field)
    if not path_value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=not_ready,
        )
    path = validated_job_file(settings, job_id, path_value)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=missing,
        )
    return path


@router.get("/{job_id}", response_model=JobResponse)
def get_job(request: Request, job_id: str) -> JobResponse:
    return JobResponse.model_validate(existing_job(request, job_id))


@router.get("/{job_id}/style", response_model=SubtitleStyle)
def get_style(request: Request, job_id: str) -> SubtitleStyle:
    settings, _ = services(request)
    existing_job(request, job_id)
    style_path = settings.storage_dir / job_id / "style.json"
    if not style_path.is_file():
        return SubtitleStyle()
    return SubtitleStyle.model_validate_json(
        style_path.read_text(encoding="utf-8")
    )


@router.post("/{job_id}/restyle", response_model=JobResponse)
async def restyle_job(
    request: Request,
    job_id: str,
    style: SubtitleStyle,
) -> JobResponse:
    """Regenerate subtitles and video from the existing timeline."""
    settings, database = services(request)
    job = existing_job(request, job_id)
    job_dir = settings.storage_dir / job_id
    if (
        job["status"] not in RESTYLABLE_STATUSES
        or not job.get("timeline_path")
        or not (job_dir / "timeline.json").is_file()
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="歌词时间轴尚未完成，暂时无法修改字幕样式",
        )
    runner = getattr(request.app.state, "runner", None)
    if runner is None or not getattr(runner, "can_accept", True):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Processing queue is full. Try again later.",
            headers={"Retry-After": "60"},
        )
    write_style(job_dir, style)
    database.update_job_state(
        job_id,
        status="UPLOADED",
        stage="RESTYLE_QUEUED",
        progress=90,
    )
    try:
        await runner.enqueue(job_id)
    except QueueCapacityError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Processing queue is full. Try again later.",
            headers={"Retry-After": "60"},
        ) from exc
    return JobResponse.model_validate(database.get_job(job_id))


def reviewable_job(request: Request, job_id: str) -> tuple[dict, Path]:
    settings, _ = services(request)
    job = existing_job(request, job_id)
    job_dir = settings.storage_dir / job_id
    if (
        job["status"] not in RESTYLABLE_STATUSES
        or not (job_dir / "timeline.json").is_file()
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="歌词时间轴尚未完成，暂时无法核对",
        )
    return job, job_dir


def read_timeline(job_dir: Path) -> LyricTimeline:
    return LyricTimeline.from_dict(
        json.loads((job_dir / "timeline.json").read_text(encoding="utf-8"))
    )


def write_timeline(job_dir: Path, timeline: LyricTimeline) -> dict:
    data = timeline.to_dict()
    (job_dir / "timeline.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return data


def song_duration_ms(job_dir: Path) -> int | None:
    transcript_path = job_dir / "transcript.json"
    if not transcript_path.is_file():
        return None
    data = json.loads(transcript_path.read_text(encoding="utf-8"))
    return round(float(data["duration_seconds"]) * 1000)


def job_pipeline(request: Request):
    return getattr(getattr(request.app.state, "runner", None), "pipeline", None)


def alignment_tools(request: Request) -> tuple[object | None, object | None]:
    pipeline = job_pipeline(request)
    return (
        getattr(pipeline, "aligner", None),
        getattr(pipeline, "primary_aligner", None)
        or getattr(pipeline, "alignment_refiner", None),
    )


@router.get("/{job_id}/source", response_class=FileResponse)
def get_source_video(request: Request, job_id: str) -> FileResponse:
    return FileResponse(
        job_artifact(
            request,
            job_id,
            field="video_path",
            not_ready="源视频不存在",
            missing="源视频不存在",
        ),
        media_type="video/mp4",
    )


@router.get("/{job_id}/audio/{track}", response_class=FileResponse)
def get_audio_track(request: Request, job_id: str, track: str) -> FileResponse:
    settings, _ = services(request)
    existing_job(request, job_id)
    filename = AUDIO_TRACKS.get(track)
    path = settings.storage_dir / job_id / filename if filename else None
    if track == "vocals":
        # The Roformer stem is the cleaner one to listen to, when it exists.
        clean_path = settings.storage_dir / job_id / CLEAN_VOCALS
        path = clean_path if clean_path.is_file() else path
    if path is None or not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该音轨不存在",
        )
    return FileResponse(path, media_type="audio/wav")


@router.get("/{job_id}/review")
def get_review(request: Request, job_id: str) -> dict:
    _, job_dir = reviewable_job(request, job_id)
    aligner, refiner = alignment_tools(request)
    notes_path = job_dir / "alignment_notes.json"
    notes = (
        json.loads(notes_path.read_text(encoding="utf-8"))
        if notes_path.is_file()
        else {}
    )
    lyrics_path = job_dir / "lyrics_processed.json"
    lyrics_info = (
        json.loads(lyrics_path.read_text(encoding="utf-8"))
        if lyrics_path.is_file()
        else {}
    )
    pipeline = job_pipeline(request)
    forced = getattr(pipeline, "primary_aligner", None) is not None
    is_forced = forced and pipeline._is_forced_transcript(job_dir)
    return {
        # Whole-song forced alignment is far more accurate than ASR, so a
        # job that had to do without it says so.
        "alignment_source": "forced" if is_forced else "asr",
        "forced_alignment_failure": (
            pipeline.forced_alignment_failure(job_dir) if forced else None
        ),
        "can_retry_forced_alignment": forced and not is_forced,
        # "local" readings come from a dictionary and are wrong more often
        "lyrics_provider": lyrics_info.get("provider"),
        "can_edit_readings": lyrics_path.is_file(),
        "rests": notes.get("rests", []),
        "moved_lines": notes.get("moved_lines", []),
        "lrc_adjusted_lines": notes.get("lrc_adjusted_lines", []),
        "timeline": read_timeline(job_dir).to_dict(),
        "duration_ms": song_duration_ms(job_dir),
        "has_vocals": (job_dir / AUDIO_TRACKS["vocals"]).is_file()
        or (job_dir / CLEAN_VOCALS).is_file(),
        "unresolved_lines": notes.get("unresolved_lines", []),
        "can_refine": aligner is not None and refiner is not None,
    }


@router.put("/{job_id}/timeline")
def update_timeline(request: Request, job_id: str, edits: TimelineEdits) -> dict:
    _, job_dir = reviewable_job(request, job_id)
    try:
        timeline = apply_line_edits(
            read_timeline(job_dir),
            {edit.index: (edit.start_ms, edit.end_ms) for edit in edits.lines},
            duration_ms=song_duration_ms(job_dir),
        )
    except TimelineEditError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"时间轴无效：{exc}",
        ) from exc
    return {"timeline": write_timeline(job_dir, timeline)}


@router.put("/{job_id}/readings")
def update_readings(request: Request, job_id: str, body: ReadingEdits) -> dict:
    """Correct the kana readings of lyric tokens."""
    _, job_dir = reviewable_job(request, job_id)
    lyrics_path = job_dir / "lyrics_processed.json"
    if not lyrics_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="这个任务没有可修改的读音数据",
        )
    lyrics = LyricDocument.from_dict(
        json.loads(lyrics_path.read_text(encoding="utf-8"))
    )
    try:
        lyrics, timeline, changed = apply_reading_edits(
            lyrics,
            read_timeline(job_dir),
            {(edit.line, edit.token): edit.reading for edit in body.edits},
        )
    except ReadingEditError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"读音无效：{exc}",
        ) from exc
    if changed:
        lyrics_path.write_text(
            json.dumps(lyrics.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return {
        "timeline": write_timeline(job_dir, timeline)
        if changed
        else timeline.to_dict(),
        "changed_lines": changed,
    }


@router.post("/{job_id}/timeline/forced")
def retry_forced_alignment(request: Request, job_id: str) -> dict:
    """Align the whole song again for a job that fell back to ASR."""
    _, job_dir = reviewable_job(request, job_id)
    pipeline = job_pipeline(request)
    if getattr(pipeline, "primary_aligner", None) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="本机未启用整首强制对齐",
        )
    try:
        timeline = pipeline.retry_forced_alignment(job_dir)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="整首强制对齐失败，请查看本地服务日志",
        ) from exc
    if timeline is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="整首强制对齐再次失败："
            + (pipeline.forced_alignment_failure(job_dir) or "原因未知"),
        )
    return {"timeline": write_timeline(job_dir, timeline)}


@router.post("/{job_id}/timeline/refine")
def refine_timeline_lines(
    request: Request,
    job_id: str,
    body: RefineRequest,
) -> dict:
    """Re-time the given lines inside their current windows."""
    _, job_dir = reviewable_job(request, job_id)
    aligner, refiner = alignment_tools(request)
    lyrics_path = job_dir / "lyrics_processed.json"
    duration_ms = song_duration_ms(job_dir)
    if (
        aligner is None
        or refiner is None
        or duration_ms is None
        or not lyrics_path.is_file()
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="本机未启用 AI 精对齐",
        )
    timeline = read_timeline(job_dir)
    lyrics = LyricDocument.from_dict(
        json.loads(lyrics_path.read_text(encoding="utf-8"))
    )
    indexes = sorted(set(body.lines))
    if indexes[-1] >= len(timeline.lines) or len(lyrics.lines) != len(
        timeline.lines
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="歌词行不存在",
        )
    vocals_path = job_dir / AUDIO_TRACKS["vocals"]
    try:
        timeline, refined_lines = realign_lines(
            aligner,
            refiner,
            lyrics,
            timeline,
            indexes,
            vocals_path if vocals_path.is_file() else job_dir / "audio.wav",
            duration_seconds=duration_ms / 1000,
            work_dir=job_dir,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI 精对齐失败，请查看本地服务日志",
        ) from exc
    try:
        timeline = apply_line_edits(timeline, {})
    except TimelineEditError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"时间轴无效：{exc}",
        ) from exc
    return {
        "timeline": write_timeline(job_dir, timeline),
        "refined_lines": sorted(refined_lines),
    }


@router.post("/{job_id}/render", response_model=JobResponse)
async def render_job(
    request: Request,
    job_id: str,
    style: SubtitleStyle | None = None,
) -> JobResponse:
    """Render the video from the (possibly hand-corrected) timeline.

    The style can be chosen while reviewing, next to the live preview; it
    is stored only once the queue has room for the job.
    """
    _, database = services(request)
    _, job_dir = reviewable_job(request, job_id)
    runner = getattr(request.app.state, "runner", None)
    if runner is None or not getattr(runner, "can_accept", True):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Processing queue is full. Try again later.",
            headers={"Retry-After": "60"},
        )
    if style is not None:
        write_style(job_dir, style)
    database.update_job_state(
        job_id,
        status="UPLOADED",
        stage="RENDER_QUEUED",
        progress=96,
    )
    try:
        await runner.enqueue(job_id)
    except QueueCapacityError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Processing queue is full. Try again later.",
            headers={"Retry-After": "60"},
        ) from exc
    return JobResponse.model_validate(database.get_job(job_id))


@router.get("/{job_id}/transcript", response_class=FileResponse)
def get_transcript(request: Request, job_id: str) -> FileResponse:
    return FileResponse(
        job_artifact(
            request,
            job_id,
            field="transcript_path",
            not_ready="转录尚未完成",
            missing="转录文件不存在",
        ),
        media_type="application/json",
        filename="transcript.json",
    )


@router.get("/{job_id}/lyrics", response_class=FileResponse)
def get_processed_lyrics(request: Request, job_id: str) -> FileResponse:
    return FileResponse(
        job_artifact(
            request,
            job_id,
            field="lyrics_processed_path",
            not_ready="歌词处理尚未完成",
            missing="歌词处理文件不存在",
        ),
        media_type="application/json",
        filename="lyrics_processed.json",
    )


@router.get("/{job_id}/timeline", response_class=FileResponse)
def get_timeline(request: Request, job_id: str) -> FileResponse:
    return FileResponse(
        job_artifact(
            request,
            job_id,
            field="timeline_path",
            not_ready="歌词时间轴尚未完成",
            missing="歌词时间轴文件不存在",
        ),
        media_type="application/json",
        filename="timeline.json",
    )


@router.get("/{job_id}/subtitle", response_class=FileResponse)
def get_subtitle(request: Request, job_id: str) -> FileResponse:
    return FileResponse(
        job_artifact(
            request,
            job_id,
            field="ass_path",
            not_ready="ASS 字幕尚未生成",
            missing="ASS 字幕文件不存在",
        ),
        media_type="text/x-ssa; charset=utf-8",
        filename="lyrics.ass",
    )


@router.get("/{job_id}/result", response_class=FileResponse)
def get_result_video(
    request: Request,
    job_id: str,
    vocal: Literal["on", "off"] = "on",
) -> FileResponse:
    return FileResponse(
        result_video_path(request, job_id, vocal),
        media_type="video/mp4",
    )


@router.get("/{job_id}/download", response_class=FileResponse)
def download_result_video(
    request: Request,
    job_id: str,
    vocal: Literal["on", "off"] = "on",
) -> FileResponse:
    return FileResponse(
        result_video_path(request, job_id, vocal),
        media_type="video/mp4",
        filename=(
            "final_karaoke_off_vocal.mp4" if vocal == "off" else "final_karaoke.mp4"
        ),
    )


def result_video_path(request: Request, job_id: str, vocal: str = "on") -> Path:
    return job_artifact(
        request,
        job_id,
        field="output_off_path" if vocal == "off" else "output_path",
        not_ready="最终视频尚未生成",
        missing="最终视频文件不存在",
    )


def validated_job_file(
    settings: Settings,
    job_id: str,
    path_value: str,
) -> Path:
    job_dir = (settings.storage_dir / job_id).resolve()
    candidate = Path(path_value).resolve()
    if candidate.parent != job_dir or not candidate.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Requested task file is no longer available.",
        )
    return candidate
