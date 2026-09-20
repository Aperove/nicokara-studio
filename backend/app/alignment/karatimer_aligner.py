from __future__ import annotations

import json
import subprocess
import unicodedata
from pathlib import Path
from typing import Sequence

from pykakasi import kakasi

from app.ai.whisper import TranscriptDocument
from app.alignment.refiner import ForcedAlignmentError, transcript_from_units
from app.lyrics.models import LyricDocument, LyricLine


WORKER_PATH = Path(__file__).with_name("karatimer_worker.py")

_CONVERTER = kakasi()
_VOWELS = "aiueo"
_LONG_VOWEL_MARKS = "-ー―~〜"
# Slack after a hand-picked line window: phrase endings are marked roughly.
_LINE_TAIL_PAD_MS = 300


def romanize(reading: str) -> str:
    """Lowercase Hepburn letters only, the form the CTC vocabulary expects."""
    text = unicodedata.normalize("NFKC", reading)
    roman = "".join(item["hepburn"] for item in _CONVERTER.convert(text)).lower()
    letters: list[str] = []
    for character in roman:
        if character in _LONG_VOWEL_MARKS:
            # a long-vowel mark repeats the vowel before it
            previous = next((c for c in reversed(letters) if c in _VOWELS), None)
            if previous:
                letters.append(previous)
        elif "a" <= character <= "z":
            letters.append(character)
    return "".join(letters)


def line_units(line: LyricLine) -> list[dict[str, str]]:
    """One unit per lyric token that is actually sung.

    Tokens without a reading (punctuation, spaces) cannot be aligned; their
    text rides along with the next sung token so nothing is lost.
    """
    units: list[dict[str, str]] = []
    pending = ""
    for token in line.tokens:
        reading = romanize(token.reading)
        if not reading:
            pending += token.surface
            continue
        units.append({"text": pending + token.surface, "reading": reading})
        pending = ""
    return units


class KaratimerAligner:
    """Align known lyrics to the whole song with karatimer.

    Unlike ASR followed by matching, a CTC forced aligner scores every audio
    frame against the lyrics and takes the single best monotonic path, so it
    needs no recognition pass, no windows, and does not drift on long songs.
    The result comes back as a transcript whose words are the lyrics
    themselves, ready for the regular timeline aligner.
    """

    def __init__(
        self,
        *,
        python_command: Sequence[str],
        device: str | None = None,
        timeout_seconds: int = 1800,
    ) -> None:
        self.python_command = tuple(python_command)
        self.device = device
        self.timeout_seconds = timeout_seconds

    def align_song(
        self,
        lyrics: LyricDocument,
        media_path: Path,
        *,
        work_dir: Path,
    ) -> TranscriptDocument:
        response = self._run(
            media_path,
            [
                {
                    "start_ms": 0,
                    "end_ms": None,
                    "lines": self._lines(lyrics, range(len(lyrics.lines))),
                }
            ],
            work_dir,
        )
        return transcript_from_units(
            response["units"],
            duration_seconds=response["duration_ms"] / 1000,
        )

    def refine_lines(
        self,
        lyrics: LyricDocument,
        windows: dict[int, tuple[int, int]],
        audio_path: Path,
        *,
        duration_seconds: float,
        work_dir: Path,
    ) -> dict[int, TranscriptDocument]:
        """Re-time individual lines inside windows chosen by a person.

        Same contract as the Qwen refiner, so either can serve the review
        screen.  The media file next to the stems is used, not `audio_path`:
        the model was trained on full mixes.
        """
        media_path = work_dir / "input.mp4"
        if not media_path.is_file():
            media_path = audio_path
        chunks = [
            {
                "start_ms": max(0, start_ms),
                "end_ms": end_ms + _LINE_TAIL_PAD_MS,
                "lines": self._lines(lyrics, [index]),
            }
            for index, (start_ms, end_ms) in sorted(windows.items())
        ]
        if not chunks:
            return {}
        response = self._run(media_path, chunks, work_dir)
        by_line: dict[int, list[dict]] = {}
        for unit in response["units"]:
            by_line.setdefault(int(unit["line"]), []).append(unit)
        return {
            index: transcript_from_units(units, duration_seconds=duration_seconds)
            for index, units in by_line.items()
        }

    @staticmethod
    def _lines(lyrics: LyricDocument, indexes) -> list[dict]:
        return [
            {"index": index, "units": line_units(lyrics.lines[index])}
            for index in indexes
        ]

    def _run(self, media_path: Path, chunks: list[dict], work_dir: Path) -> dict:
        if not any(line["units"] for chunk in chunks for line in chunk["lines"]):
            raise ForcedAlignmentError("No lyric line has a reading to align")
        request_path = work_dir / "karatimer_request.json"
        response_path = work_dir / "karatimer_response.json"
        request_path.write_text(
            json.dumps(
                {
                    "media": str(media_path.resolve()),
                    "device": self.device,
                    "chunks": chunks,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        response_path.unlink(missing_ok=True)
        try:
            subprocess.run(
                [
                    *self.python_command,
                    str(WORKER_PATH),
                    str(request_path),
                    str(response_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "worker exited with an error").strip()
            raise ForcedAlignmentError(detail[-2000:]) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ForcedAlignmentError(str(exc)) from exc
        finally:
            request_path.unlink(missing_ok=True)
        if not response_path.is_file():
            raise ForcedAlignmentError("karatimer produced no output")
        try:
            return json.loads(response_path.read_text(encoding="utf-8"))
        finally:
            response_path.unlink(missing_ok=True)
