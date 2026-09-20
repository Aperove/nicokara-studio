from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


class VideoRenderingError(RuntimeError):
    """Raised when FFmpeg cannot render the karaoke video."""


class FFmpegVideoRenderer:
    def __init__(
        self,
        *,
        command: Sequence[str] = ("ffmpeg",),
        timeout_seconds: int = 7200,
        pad_to_16_9: bool = True,
        preset: str = "veryfast",
        crf: int = 20,
    ) -> None:
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds
        self.pad_to_16_9 = pad_to_16_9
        self.preset = preset
        self.crf = crf

    def render(
        self,
        input_path: Path,
        subtitle_path: Path,
        output_path: Path,
        *,
        vocal_mode: str = "on",
        instrumental_audio_path: Path | None = None,
    ) -> None:
        job_dir = input_path.parent.resolve()
        if (
            subtitle_path.parent.resolve() != job_dir
            or output_path.parent.resolve() != job_dir
        ):
            raise ValueError("Video, subtitle and output must share a directory")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            vf_parts = self._picture_filters(subtitle_path.name)
            cmd = [
                *self.command,
                "-y",
                "-i",
                input_path.name,
            ]
            use_instrumental = (
                vocal_mode == "off"
                and instrumental_audio_path is not None
            )
            if use_instrumental:
                cmd.extend(["-i", instrumental_audio_path.name])
            cmd.extend([
                "-vf",
                ",".join(vf_parts),
                "-map",
                "0:v:0",
            ])
            if use_instrumental:
                cmd.extend(["-map", "1:a:0"])
            else:
                cmd.extend(["-map", "0:a?"])
            cmd.extend([
                "-c:v",
                "libx264",
                "-preset",
                self.preset,
                "-crf",
                str(self.crf),
                "-pix_fmt",
                "yuv420p",
            ])
            if use_instrumental:
                cmd.extend([
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                ])
            else:
                cmd.extend(["-c:a", "copy"])
            cmd.extend(["-movflags", "+faststart", output_path.name])
            subprocess.run(
                cmd,
                cwd=job_dir,
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            if not output_path.is_file() or output_path.stat().st_size == 0:
                output_path.unlink(missing_ok=True)
                raise VideoRenderingError(
                    "FFmpeg did not produce a non-empty output video"
                )
        except subprocess.CalledProcessError as exc:
            output_path.unlink(missing_ok=True)
            detail = (exc.stderr or "FFmpeg exited with an error").strip()
            raise VideoRenderingError(detail[-2000:]) from exc
        except subprocess.TimeoutExpired as exc:
            output_path.unlink(missing_ok=True)
            raise VideoRenderingError(
                f"FFmpeg timed out after {self.timeout_seconds} seconds"
            ) from exc

    def _picture_filters(self, subtitle_name: str) -> list[str]:
        filters = []
        if self.pad_to_16_9:
            filters.append(
                "pad=w=ceil(max(iw\\,ih*16/9)/2)*2"
                ":h=ceil(max(ih\\,iw*9/16)/2)*2"
                ":x=(ow-iw)/2"
                ":y=(oh-ih)/2"
                ":color=black"
            )
        filters.append(f"subtitles=filename={subtitle_name}")
        return filters

    def render_frame(
        self,
        input_path: Path,
        subtitle_path: Path,
        output_path: Path,
        *,
        time_seconds: float,
        width: int = 1280,
        timeout_seconds: int = 60,
    ) -> None:
        """One frame of the video exactly as the full render would draw it.

        The picture goes through the same filters as the real render, so
        font, size, position and any font substitution are the real ones.
        """
        job_dir = input_path.parent.resolve()
        if (
            subtitle_path.parent.resolve() != job_dir
            or output_path.parent.resolve() != job_dir
        ):
            raise ValueError("Video, subtitle and output must share a directory")
        filters = [
            *self._picture_filters(subtitle_path.name),
            f"scale={width}:-2",
        ]
        try:
            subprocess.run(
                [
                    *self.command,
                    "-y",
                    "-loglevel",
                    "error",
                    # seek before decoding, but keep the timestamps: the
                    # subtitles are looked up by the time of the frame
                    "-ss",
                    f"{max(0.0, time_seconds):.3f}",
                    "-copyts",
                    "-i",
                    input_path.name,
                    "-vf",
                    ",".join(filters),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    output_path.name,
                ],
                cwd=job_dir,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise VideoRenderingError("FFmpeg did not produce a frame")
        except subprocess.CalledProcessError as exc:
            output_path.unlink(missing_ok=True)
            detail = (exc.stderr or "FFmpeg exited with an error").strip()
            raise VideoRenderingError(detail[-2000:]) from exc
        except subprocess.TimeoutExpired as exc:
            output_path.unlink(missing_ok=True)
            raise VideoRenderingError("FFmpeg timed out on a single frame") from exc

    def replace_audio(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
    ) -> None:
        """Copy the rendered picture and give it another soundtrack.

        The off-vocal version differs from the rendered video only in its
        audio, so the expensive subtitle burn-in is not repeated.
        """
        try:
            subprocess.run(
                [
                    *self.command,
                    "-y",
                    "-i",
                    str(video_path),
                    "-i",
                    str(audio_path),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-shortest",
                    "-movflags",
                    "+faststart",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise VideoRenderingError("FFmpeg did not produce the off-vocal video")
        except subprocess.CalledProcessError as exc:
            output_path.unlink(missing_ok=True)
            detail = (exc.stderr or "FFmpeg exited with an error").strip()
            raise VideoRenderingError(detail[-2000:]) from exc
        except (subprocess.TimeoutExpired, VideoRenderingError):
            output_path.unlink(missing_ok=True)
            raise
