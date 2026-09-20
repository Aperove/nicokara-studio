from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="NICOKARA_",
        extra="ignore",
    )

    app_name: str = "ニコカラ自动生成器 API"
    api_prefix: str = "/api/v1"
    data_dir: Path = Field(default=Path("data"))
    storage_dir: Path = Field(default=Path("../storage/jobs"))
    max_video_bytes: int = 1024 * 1024 * 1024
    max_lyrics_bytes: int = 1024 * 1024
    max_pending_jobs: int = 4
    max_uploads_per_hour: int = 0
    cleanup_enabled: bool = True
    job_retention_hours: int = 24
    cleanup_interval_seconds: int = 3600
    allowed_origins: str = "http://localhost:3200"
    processing_enabled: bool = True
    ffmpeg_path: str = "ffmpeg"
    ffmpeg_timeout_seconds: int = 900
    video_render_timeout_seconds: int = 7200
    video_render_preset: str = "veryfast"
    video_render_crf: int = 20
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_lyrics_hint: bool = True
    transcribe_vocal_stem: bool = True
    # Optional forced alignment with Qwen3-ForcedAligner.  Set this to a
    # Python interpreter that has torch and qwen-asr installed to enable it.
    forced_aligner_python: Path | None = None
    forced_aligner_model: str = "Qwen/Qwen3-ForcedAligner-0.6B"
    forced_aligner_device: str = "cuda:0"
    forced_aligner_timeout_seconds: int = 900
    # Optional Roformer vocal stem, used for recognition, alignment and for
    # finding interludes.  Needs an interpreter with torch and audio-separator.
    vocal_stem_python: Path | None = None
    vocal_stem_model: str = "vocals_mel_band_roformer.ckpt"
    vocal_stem_timeout_seconds: int = 1800
    # Optional whole-song forced alignment with karatimer.  When set, lyrics
    # are aligned without any speech recognition; ASR is only the fallback.
    # Needs an interpreter with karatimer installed.  Its alignment model is
    # CC-BY-NC-SA-4.0: non-commercial use only.
    karatimer_python: Path | None = None
    karatimer_device: str | None = None
    karatimer_timeout_seconds: int = 1800
    # Sites a job may be created from by link instead of by upload.
    video_url_hosts: str = "youtube.com,youtu.be"
    # Optional: let yt-dlp read the login session of this browser (chrome,
    # edge, firefox, ...), for videos that need a signed-in viewer; off by default
    # because it reads that browser's cookies.
    video_cookies_from_browser: str | None = None
    video_download_timeout_seconds: int = 1800
    vocal_removal_backend: str = "mdx"
    vocal_removal_model: str = "UVR_MDXNET_KARA_2.onnx"
    vocal_removal_model_dir: Path = Field(
        default=Path("data/audio-separator-models")
    )
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_timeout_seconds: float = 60

    @field_validator(
        "forced_aligner_python",
        "vocal_stem_python",
        "karatimer_python",
        "karatimer_device",
        "video_cookies_from_browser",
        mode="before",
    )
    @classmethod
    def empty_forced_aligner_is_disabled(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("deepseek_api_key", mode="before")
    @classmethod
    def empty_deepseek_key_is_disabled(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "max_video_bytes",
        "max_lyrics_bytes",
        "max_pending_jobs",
        "job_retention_hours",
        "cleanup_interval_seconds",
        "video_render_timeout_seconds",
    )
    @classmethod
    def positive_limits(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value

    @field_validator("max_uploads_per_hour")
    @classmethod
    def non_negative_upload_limit(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must be zero or greater")
        return value

    @field_validator("video_render_crf")
    @classmethod
    def valid_crf(cls, value: int) -> int:
        if not 0 <= value <= 51:
            raise ValueError("must be between 0 and 51")
        return value

    @field_validator("video_render_preset")
    @classmethod
    def valid_video_preset(cls, value: str) -> str:
        allowed = {
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        }
        if value not in allowed:
            raise ValueError("unsupported x264 preset")
        return value

    @field_validator("vocal_removal_backend")
    @classmethod
    def valid_vocal_removal_backend(cls, value: str) -> str:
        if value not in {"mdx", "stft"}:
            raise ValueError("must be mdx or stft")
        return value

    @property
    def database_path(self) -> Path:
        return self.data_dir / "nicokara.sqlite3"

    @property
    def video_url_host_list(self) -> list[str]:
        return [
            host.strip().lower()
            for host in self.video_url_hosts.split(",")
            if host.strip()
        ]

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    def prepare_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.storage_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
