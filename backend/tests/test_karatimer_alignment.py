from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import app.alignment.karatimer_aligner as karatimer_module
from app.ai.whisper import (
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
)
from app.alignment.aligner import LyricTimelineAligner
from app.alignment.karatimer_aligner import KaratimerAligner, line_units, romanize
from app.alignment.refiner import ForcedAlignmentError, transcript_from_units
from app.core.database import Database
from app.lyrics.models import LyricDocument, LyricLine, LyricToken
from app.subtitle.ass_generator import AssGenerator
from app.tasks.pipeline import TranscriptionPipeline


ROWS = ["あいうえお", "かきくけこ", "さしすせそ"]


def lyrics_of(rows: list[str]) -> LyricDocument:
    return LyricDocument(
        provider="local",
        source_text="\n".join(rows),
        lines=[LyricLine(row, row, row, [LyricToken(row, row)]) for row in rows],
    )


def test_readings_become_lowercase_hepburn_letters() -> None:
    assert romanize("かきくけこ") == "kakikukeko"
    assert romanize("しゃしん") == "shashin"
    assert romanize("きって") == "kitte"
    # a long-vowel mark repeats the vowel before it; katakana reads the same
    assert romanize("コーヒー") == "koohii"
    assert romanize("、！ ") == ""


def test_unsung_tokens_ride_along_with_the_next_sung_one() -> None:
    line = LyricLine(
        source="「あい」、うえ",
        surface="「あい」、うえ",
        reading="あいうえ",
        tokens=[
            LyricToken("「", ""),
            LyricToken("あい", "あい"),
            LyricToken("」、", ""),
            LyricToken("うえ", "うえ"),
        ],
    )

    assert line_units(line) == [
        {"text": "あい", "reading": "ai"},
        {"text": "うえ", "reading": "ue"},
    ]


def test_units_carry_the_lyric_reading_rather_than_the_written_form() -> None:
    # Reading the kanji again could give しょうがい; the lyrics say いきがい.
    line = LyricLine(
        source="生涯",
        surface="生涯",
        reading="いきがい",
        tokens=[LyricToken("生涯", "いきがい")],
    )

    assert line_units(line) == [{"text": "いきがい", "reading": "ikigai"}]


FAKE_WORKER = """
import json, sys
request = json.load(open(sys.argv[1], encoding="utf-8"))
units = []
for chunk in request["chunks"]:
    cursor = chunk["start_ms"] + 1000
    for line in chunk["lines"]:
        for unit in line["units"]:
            assert unit["reading"].isascii() and unit["reading"].islower()
            units.append({"line": line["index"], "text": unit["text"],
                          "start_ms": cursor, "end_ms": cursor + 2000})
            cursor += 2000
json.dump({"duration_ms": 60000, "units": units},
          open(sys.argv[2], "w", encoding="utf-8"))
"""


@pytest.fixture
def fake_worker(tmp_path: Path):
    worker = tmp_path / "fake_karatimer_worker.py"
    worker.write_text(FAKE_WORKER, encoding="utf-8")
    original = karatimer_module.WORKER_PATH
    karatimer_module.WORKER_PATH = worker
    yield worker
    karatimer_module.WORKER_PATH = original


def test_whole_song_alignment_returns_a_transcript_of_the_lyrics(
    tmp_path: Path, fake_worker: Path
) -> None:
    aligner = KaratimerAligner(python_command=(sys.executable,))
    media = tmp_path / "input.mp4"
    media.write_bytes(b"video")

    transcript = aligner.align_song(lyrics_of(ROWS), media, work_dir=tmp_path)

    assert transcript.duration_seconds == 60.0
    words = transcript.segments[0].words
    assert [(w.text, w.start_ms, w.end_ms) for w in words] == [
        (ROWS[0], 1_000, 3_000),
        (ROWS[1], 3_000, 5_000),
        (ROWS[2], 5_000, 7_000),
    ]
    timeline = LyricTimelineAligner().align(lyrics_of(ROWS), transcript)
    assert timeline.confidence == 1.0
    assert [line.start_ms for line in timeline.lines] == [1_000, 3_000, 5_000]
    assert not (tmp_path / "karatimer_request.json").exists()
    assert not (tmp_path / "karatimer_response.json").exists()


def test_single_lines_are_realigned_inside_their_windows(
    tmp_path: Path, fake_worker: Path
) -> None:
    aligner = KaratimerAligner(python_command=(sys.executable,))
    (tmp_path / "input.mp4").write_bytes(b"video")

    transcripts = aligner.refine_lines(
        lyrics_of(ROWS),
        {1: (20_000, 24_000)},
        tmp_path / "audio_vocals.wav",
        duration_seconds=60.0,
        work_dir=tmp_path,
    )

    assert list(transcripts) == [1]
    word = transcripts[1].segments[0].words[0]
    assert (word.text, word.start_ms) == (ROWS[1], 21_000)


def test_worker_failures_surface_as_alignment_errors(tmp_path: Path) -> None:
    aligner = KaratimerAligner(
        python_command=(str(tmp_path / "no-such-python.exe"),)
    )
    with pytest.raises(ForcedAlignmentError):
        aligner.align_song(lyrics_of(ROWS), tmp_path / "input.mp4", work_dir=tmp_path)
    with pytest.raises(ForcedAlignmentError):
        KaratimerAligner(python_command=(sys.executable,)).align_song(
            LyricDocument("local", "", [LyricLine("！", "！", "", [LyricToken("！", "")])]),
            tmp_path / "input.mp4",
            work_dir=tmp_path,
        )


class Steps:
    """Extractor, transcriber and lyric processor in one fake."""

    def __init__(self) -> None:
        self.transcribed = 0
        self.processed = 0

    def extract(self, video, audio) -> None:
        audio.write_bytes(b"wav")

    def transcribe(self, audio, **options) -> TranscriptDocument:
        self.transcribed += 1
        words = [
            TranscriptWord(kana, 30_000 + i * 400, 30_400 + i * 400, 0.9)
            for i, kana in enumerate("".join(ROWS))
        ]
        return TranscriptDocument(
            "ja", 1.0, 60.0, "",
            [TranscriptSegment(0, "", 30_000, 36_000, -0.1, 0.0, words)],
        )

    def process(self, text: str) -> LyricDocument:
        self.processed += 1
        return lyrics_of(ROWS)


class ForcedAligner:
    def __init__(self, *, fail: bool = False, garbage: bool = False) -> None:
        self.fail, self.garbage, self.calls = fail, garbage, 0

    def align_song(self, lyrics, media_path, *, work_dir):
        self.calls += 1
        if self.fail:
            raise ForcedAlignmentError("no gpu")
        return transcript_from_units(
            [
                {
                    "line": index,
                    "text": "んんんんん" if self.garbage else line.surface,
                    "start_ms": 5_000 + index * 3_000,
                    "end_ms": 7_000 + index * 3_000,
                }
                for index, line in enumerate(lyrics.lines)
            ],
            duration_seconds=60.0,
        )


class ForbiddenRefiner:
    def refine(self, *args, **kwargs):
        raise AssertionError("a forced transcript must not be refined again")


class Renderer:
    def render(self, video, subtitle, output, **options) -> None:
        output.write_bytes(b"rendered")


def run_job(tmp_path: Path, forced: ForcedAligner, steps: Steps):
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "storage" / "job"
    job_dir.mkdir(parents=True)
    video_path = job_dir / "input.mp4"
    video_path.write_bytes(b"video")
    lyrics_path = job_dir / "lyrics.txt"
    lyrics_path.write_text("\n".join(ROWS), encoding="utf-8")
    job_id = "f13ecf06-9ac4-486f-a5cd-b4959f02bc76"
    database.create_job(
        job_id=job_id,
        original_video_name="song.mp4",
        video_size_bytes=5,
        video_sha256="abc",
        video_path=video_path,
        lyrics_source="text",
        lyrics_path=lyrics_path,
    )
    pipeline = TranscriptionPipeline(
        database=database,
        extractor=steps,
        transcriber=steps,
        lyric_processor=steps,
        aligner=LyricTimelineAligner(),
        subtitle_generator=AssGenerator(),
        video_renderer=Renderer(),
        alignment_refiner=ForbiddenRefiner() if not (forced.fail or forced.garbage) else None,
        primary_aligner=forced,
    )
    pipeline.process(job_id)
    return pipeline, database, job_dir, job_id


def test_forced_alignment_replaces_recognition_entirely(tmp_path: Path) -> None:
    steps, forced = Steps(), ForcedAligner()

    _, database, job_dir, job_id = run_job(tmp_path, forced, steps)

    job = database.get_job(job_id)
    assert job is not None and job["status"] == "COMPLETED"
    assert steps.transcribed == 0
    assert steps.processed == 1
    assert (job_dir / "transcript.source").read_text("utf-8").strip() == "karatimer"
    timeline = json.loads((job_dir / "timeline.json").read_text("utf-8"))
    assert [line["start_ms"] for line in timeline["lines"]] == [5_000, 8_000, 11_000]
    # downstream consumers still find a transcript with the song's duration
    stored = json.loads((job_dir / "transcript.json").read_text("utf-8"))
    assert stored["duration_seconds"] == 60.0


@pytest.mark.parametrize("mode", ["fail", "garbage"])
def test_recognition_is_the_fallback_when_forced_alignment_goes_wrong(
    tmp_path: Path, mode: str
) -> None:
    steps = Steps()
    forced = ForcedAligner(fail=mode == "fail", garbage=mode == "garbage")

    _, database, job_dir, job_id = run_job(tmp_path, forced, steps)

    job = database.get_job(job_id)
    assert job is not None and job["status"] == "COMPLETED"
    assert forced.calls == 1
    assert steps.transcribed == 1
    assert steps.processed == 1
    assert not (job_dir / "transcript.source").exists()
    timeline = json.loads((job_dir / "timeline.json").read_text("utf-8"))
    assert timeline["lines"][0]["start_ms"] == 30_000


def test_regenerating_an_asr_job_upgrades_it_and_keeps_the_old_transcript(
    tmp_path: Path,
) -> None:
    steps = Steps()
    pipeline, database, job_dir, job_id = run_job(
        tmp_path, ForcedAligner(fail=True), steps
    )
    assert not (job_dir / "transcript.source").exists()

    pipeline.primary_aligner = ForcedAligner()
    database.update_job_state(
        job_id, status="UPLOADED", stage="RESTYLE_QUEUED", progress=90
    )
    pipeline.process(job_id)

    assert (job_dir / "transcript.source").read_text("utf-8").strip() == "karatimer"
    assert (job_dir / "transcript.asr.json").is_file()
    timeline = json.loads((job_dir / "timeline.json").read_text("utf-8"))
    assert [line["start_ms"] for line in timeline["lines"]] == [5_000, 8_000, 11_000]
    assert steps.transcribed == 1


def test_no_backend_module_shadows_a_package_the_workers_import() -> None:
    # A worker script runs with its own directory first on sys.path, so a
    # sibling module named like a third-party package would be imported
    # instead of it (this happened with a module called karatimer.py).
    import app.alignment
    import app.vocal

    third_party = {"karatimer", "qwen_asr", "audio_separator", "torch", "av"}
    for package in (app.alignment, app.vocal):
        directory = Path(package.__file__).parent
        names = {path.stem for path in directory.glob("*.py")} | {
            path.name for path in directory.iterdir() if path.is_dir()
        }
        assert not names & third_party, (directory, names & third_party)
