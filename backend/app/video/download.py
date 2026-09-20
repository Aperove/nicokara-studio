from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from urllib.parse import urlsplit


# H.264 + AAC in an MP4 container is what the rest of the pipeline and
# browsers handle best; fall back to whatever single MP4 the site offers.
_FORMAT = "bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]/b[ext=mp4]/b"
_MAX_URL_LENGTH = 2048
# Browsers yt-dlp can borrow a login session from.  Some sites only serve
# certain videos, or full quality, to signed-in users.
COOKIE_BROWSERS = frozenset(
    {"brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi"}
)


class VideoDownloadError(RuntimeError):
    """Raised when a video cannot be fetched from its link."""


class UnsupportedVideoUrl(ValueError):
    """Raised for links that are malformed or point to a site not allowed."""


@dataclass(frozen=True)
class DownloadedVideo:
    path: Path
    title: str


def validate_video_url(url: str, allowed_hosts: Sequence[str]) -> str:
    """Return the cleaned link, or raise UnsupportedVideoUrl.

    Only plain http(s) links to explicitly allowed sites are accepted, so the
    service can never be pointed at arbitrary or internal addresses.
    """
    cleaned = (url or "").strip()
    if not cleaned or len(cleaned) > _MAX_URL_LENGTH:
        raise UnsupportedVideoUrl("empty or overlong link")
    if any(character.isspace() or ord(character) < 0x20 for character in cleaned):
        raise UnsupportedVideoUrl("link contains whitespace")
    parts = urlsplit(cleaned)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http", "https") or not host:
        raise UnsupportedVideoUrl("only http(s) links are supported")
    if parts.username or parts.password:
        raise UnsupportedVideoUrl("links with credentials are not supported")
    allowed = [entry.lower().strip().lstrip(".") for entry in allowed_hosts]
    if not any(host == entry or host.endswith("." + entry) for entry in allowed if entry):
        raise UnsupportedVideoUrl(f"site not allowed: {host}")
    return cleaned


class YtDlpVideoDownloader:
    """Fetch a video as MP4 with yt-dlp, run as a subprocess."""

    def __init__(
        self,
        *,
        allowed_hosts: Sequence[str],
        ffmpeg_path: str = "ffmpeg",
        max_bytes: int = 1024 * 1024 * 1024,
        timeout_seconds: int = 1800,
        cookies_from_browser: str | None = None,
        command: Sequence[str] | None = None,
    ) -> None:
        self.allowed_hosts = tuple(allowed_hosts)
        self.ffmpeg_path = ffmpeg_path
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
        browser = (cookies_from_browser or "").strip().lower()
        if browser and browser not in COOKIE_BROWSERS:
            raise ValueError(f"unsupported browser for cookies: {browser}")
        self.cookies_from_browser = browser or None
        self.command = tuple(command or (sys.executable, "-m", "yt_dlp"))

    def download(self, url: str, destination: Path) -> DownloadedVideo:
        url = validate_video_url(url, self.allowed_hosts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.unlink(missing_ok=True)
        arguments = [
            *self.command,
            "--no-playlist",
            "--no-progress",
            "--no-part",
            "--format",
            _FORMAT,
            "--merge-output-format",
            "mp4",
            "--max-filesize",
            str(self.max_bytes),
            "--print",
            "after_move:%(title)s",
            "--output",
            str(destination),
        ]
        if Path(self.ffmpeg_path).is_file():
            arguments += ["--ffmpeg-location", self.ffmpeg_path]
        if self.cookies_from_browser:
            arguments += ["--cookies-from-browser", self.cookies_from_browser]
        # "--" ends the options: the link can never be read as a flag.
        arguments += ["--", url]
        try:
            completed = subprocess.run(
                arguments,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
        except subprocess.CalledProcessError as exc:
            destination.unlink(missing_ok=True)
            detail = (exc.stderr or "yt-dlp exited with an error").strip()
            raise VideoDownloadError(detail[-2000:]) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            destination.unlink(missing_ok=True)
            raise VideoDownloadError(str(exc)) from exc
        if not destination.is_file() or destination.stat().st_size == 0:
            raise VideoDownloadError("yt-dlp produced no video file")
        if destination.stat().st_size > self.max_bytes:
            destination.unlink(missing_ok=True)
            raise VideoDownloadError("the downloaded video exceeds the size limit")
        title = next(
            (line.strip() for line in completed.stdout.splitlines() if line.strip()),
            "",
        )
        return DownloadedVideo(path=destination, title=title)
