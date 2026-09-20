from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator


class JobResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    status: str
    stage: str
    progress: int
    original_video_name: str
    video_size_bytes: int
    video_sha256: str
    lyrics_source: str | None = None
    vocal_mode: str = "on"
    # True when an instrumental (off-vocal) version was rendered as well.
    off_vocal_available: bool = False
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def derive_off_vocal(cls, data):
        if isinstance(data, dict) and "off_vocal_available" not in data:
            data = {**data, "off_vocal_available": bool(data.get("output_off_path"))}
        return data


class HealthResponse(BaseModel):
    status: str

