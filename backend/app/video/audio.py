from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


class AudioExtractionError(RuntimeError):
    """Raised when FFmpeg cannot produce the analysis audio."""


class FFmpegAudioExtractor:
    def __init__(
        self,
        *,
        command: Sequence[str] = ("ffmpeg",),
        timeout_seconds: int = 900,
    ) -> None:
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds

    def extract(self, input_path: Path, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    *self.command,
                    "-y",
                    "-i",
                    str(input_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.CalledProcessError as exc:
            output_path.unlink(missing_ok=True)
            detail = (exc.stderr or "FFmpeg exited with an error").strip()
            raise AudioExtractionError(detail[-2000:]) from exc

    def extract_stereo(self, input_path: Path, output_path: Path) -> None:
        """Extract full-quality stereo audio for vocal removal."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    *self.command,
                    "-y",
                    "-i",
                    str(input_path),
                    "-vn",
                    "-ac",
                    "2",
                    "-ar",
                    "44100",
                    "-c:a",
                    "pcm_s16le",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.CalledProcessError as exc:
            output_path.unlink(missing_ok=True)
            detail = (exc.stderr or "FFmpeg exited with an error").strip()
            raise AudioExtractionError(detail[-2000:]) from exc

    def extract_vocal_stem(
        self,
        mix_path: Path,
        instrumental_path: Path,
        output_path: Path,
    ) -> None:
        """Derive a 16 kHz mono vocal stem as mix minus instrumental."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    *self.command,
                    "-y",
                    "-i",
                    str(mix_path),
                    "-i",
                    str(instrumental_path),
                    "-filter_complex",
                    "[0:a]aformat=sample_rates=44100:channel_layouts=stereo[mix];"
                    "[1:a]aformat=sample_rates=44100:channel_layouts=stereo,"
                    "aeval=-val(0)|-val(1)[inv];"
                    "[mix][inv]amix=inputs=2:normalize=0:duration=first[vocals]",
                    "-map",
                    "[vocals]",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.CalledProcessError as exc:
            output_path.unlink(missing_ok=True)
            detail = (exc.stderr or "FFmpeg exited with an error").strip()
            raise AudioExtractionError(detail[-2000:]) from exc

    def resample_mono(self, input_path: Path, output_path: Path) -> None:
        """Write a 16 kHz mono copy, the format the analysis stages expect."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                [
                    *self.command,
                    "-y",
                    "-i",
                    str(input_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.CalledProcessError as exc:
            output_path.unlink(missing_ok=True)
            detail = (exc.stderr or "FFmpeg exited with an error").strip()
            raise AudioExtractionError(detail[-2000:]) from exc
