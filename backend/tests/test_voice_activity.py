from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.ai.whisper import (
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
)
from app.alignment.aligner import LyricTimelineAligner
from app.alignment.voice_activity import detect_rests, move_lines_out_of_rests
from app.core.database import Database
from app.lyrics.models import LyricDocument, LyricLine, LyricToken
from app.tasks.pipeline import TranscriptionPipeline
from app.video.audio import AudioExtractionError
from app.vocal.roformer import RoformerVocalStemSeparator

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

ROWS = ["あいうえお", "かきくけこ", "さしすせそ", "たちつてと"]
SAMPLE_RATE = 16_000


def lyrics_of(rows: list[str]) -> LyricDocument:
    return LyricDocument(
        provider="local",
        source_text="\n".join(rows),
        lines=[LyricLine(row, row, row, [LyricToken(row, row)]) for row in rows],
    )


def transcript_of(timed_rows: list[tuple[str, int]], step_ms: int = 400):
    words = [
        TranscriptWord(kana, start + i * step_ms, start + (i + 1) * step_ms, 0.9)
        for row, start in timed_rows
        for i, kana in enumerate(row)
    ]
    return TranscriptDocument(
        language="ja",
        language_probability=1.0,
        duration_seconds=40.0,
        text="",
        segments=[
            TranscriptSegment(
                0, "", words[0].start_ms, words[-1].end_ms, -0.1, 0.0, words
            )
        ],
    )


def write_stem(
    path: Path,
    sung: list[tuple[float, float]],
    *,
    seconds: float = 40.0,
    floor: float = 0.0005,
) -> None:
    """A fake vocal stem: loud noise while "sung", a faint floor elsewhere."""
    rng = np.random.default_rng(7)
    wave = rng.normal(0, floor, int(seconds * SAMPLE_RATE)).astype("float32")
    for start, end in sung:
        a, b = int(start * SAMPLE_RATE), int(end * SAMPLE_RATE)
        wave[a:b] = rng.normal(0, 0.2, b - a).astype("float32")
    sf.write(path, wave, SAMPLE_RATE)


def test_long_silences_in_a_clean_stem_are_rests(tmp_path: Path) -> None:
    stem = tmp_path / "vocals.wav"
    # a short breath at 8.0-8.6 s must not count, the 10 s interlude must
    write_stem(stem, [(2.0, 8.0), (8.6, 14.0), (24.0, 36.0)])

    rests = detect_rests(stem)

    assert len(rests) == 3
    (intro, interlude, outro) = rests
    assert intro[0] == 0 and abs(intro[1] - 2_000) <= 400
    assert abs(interlude[0] - 14_000) <= 400
    assert abs(interlude[1] - 24_000) <= 400
    assert abs(outro[0] - 36_000) <= 400


def test_a_stem_that_still_carries_accompaniment_is_not_trusted(
    tmp_path: Path,
) -> None:
    stem = tmp_path / "vocals.wav"
    # the "silence" is only slightly quieter than the singing
    write_stem(stem, [(2.0, 14.0), (24.0, 36.0)], floor=0.12)

    assert detect_rests(stem) == []


def test_lines_timed_inside_an_interlude_move_to_the_sung_side() -> None:
    # Lines 3 and 4 were placed inside the 14-24 s interlude; line 4 reaches
    # into the sung part after it, where both of them really belong.
    timeline = LyricTimelineAligner().align(
        lyrics_of(ROWS),
        transcript_of(
            [(ROWS[0], 4_000), (ROWS[1], 8_000), (ROWS[2], 15_000)]
            + [(ROWS[3], 17_000)],
            step_ms=400,
        ),
    )
    lines = list(timeline.lines)
    from app.alignment.editing import retime_line

    lines[3] = retime_line(lines[3], 17_000, 30_000)
    timeline = type(timeline)(timeline.confidence, lines, timeline.warnings)

    repaired, moved, unresolved = move_lines_out_of_rests(
        timeline, [(14_000, 24_000)], duration_ms=40_000
    )

    assert moved == [2, 3]
    assert unresolved == []
    assert repaired.lines[1].end_ms <= 14_000
    assert repaired.lines[2].start_ms == 24_000
    assert repaired.lines[2].end_ms == repaired.lines[3].start_ms == 27_000
    assert repaired.lines[3].end_ms == 30_000
    # untouched lines keep their timing exactly
    assert repaired.lines[0] == timeline.lines[0]


def test_a_line_only_brushing_the_edge_of_a_rest_stays_put() -> None:
    timeline = LyricTimelineAligner().align(
        lyrics_of(ROWS[:2]),
        transcript_of([(ROWS[0], 4_000), (ROWS[1], 23_400)]),
    )

    # The soft onset of line 2 sits 0.6 s inside the detected rest.
    repaired, moved, unresolved = move_lines_out_of_rests(
        timeline, [(14_000, 24_000)], duration_ms=40_000
    )

    assert moved == [] and unresolved == []
    assert repaired.lines == timeline.lines


def test_a_neighbour_parked_at_the_rest_edge_makes_room_for_stuck_lines() -> None:
    from app.alignment.editing import retime_line

    timeline = LyricTimelineAligner().align(
        lyrics_of(ROWS),
        transcript_of(
            [(ROWS[0], 8_000), (ROWS[1], 15_000), (ROWS[2], 18_000)]
            + [(ROWS[3], 24_100)]
        ),
    )
    # Line 1 is sung right up to the 10-24 s interlude.  Lines 2 and 3 sit
    # wholly inside it, and line 4 starts right where the singing resumes,
    # leaving them no room of their own on either side.
    lines = list(timeline.lines)
    lines[3] = retime_line(lines[3], 24_100, 30_100)
    timeline = type(timeline)(timeline.confidence, lines, timeline.warnings)

    repaired, moved, unresolved = move_lines_out_of_rests(
        timeline, [(10_000, 24_000)], duration_ms=40_000
    )

    assert unresolved == []
    assert moved == [1, 2, 3]
    starts = [line.start_ms for line in repaired.lines]
    assert starts[1] == 24_000
    assert starts[1] < starts[2] < starts[3] < 30_100
    assert repaired.lines[3].end_ms == 30_100


def test_lines_that_fit_nowhere_are_reported_instead_of_dropped() -> None:
    from app.alignment.editing import retime_line

    timeline = LyricTimelineAligner().align(
        lyrics_of(ROWS[:3]),
        transcript_of([(ROWS[0], 4_000), (ROWS[1], 15_000), (ROWS[2], 24_000)]),
    )
    # Line 1 fills all the time before the rest and only a sliver remains
    # after it: making room would mean an unsingable pace for a neighbour.
    lines = [
        retime_line(timeline.lines[0], 0, 9_900),
        timeline.lines[1],
        retime_line(timeline.lines[2], 24_050, 24_150),
    ]
    timeline = type(timeline)(timeline.confidence, lines, timeline.warnings)

    repaired, moved, unresolved = move_lines_out_of_rests(
        timeline, [(10_000, 24_000)], duration_ms=24_200
    )

    assert moved == []
    assert unresolved == [1]
    assert repaired.lines[1] == timeline.lines[1]


def test_roformer_separator_runs_the_worker_and_reports_failures(
    tmp_path: Path,
) -> None:
    import app.vocal.roformer as roformer_module

    worker = tmp_path / "fake_worker.py"
    worker.write_text(
        "import json, sys\n"
        "request = json.load(open(sys.argv[1], encoding='utf-8'))\n"
        "assert request['model'] == 'vocals_mel_band_roformer.ckpt'\n"
        "open(request['output'], 'wb').write(b'RIFFvocals')\n",
        encoding="utf-8",
    )
    separator = RoformerVocalStemSeparator(
        python_command=(sys.executable,), model_dir=tmp_path / "models"
    )
    original = roformer_module.WORKER_PATH
    roformer_module.WORKER_PATH = worker
    try:
        separator.separate(tmp_path / "stereo.wav", tmp_path / "vocals.wav")
        assert (tmp_path / "vocals.wav").read_bytes() == b"RIFFvocals"
        assert not (tmp_path / "vocal_stem_request.json").exists()

        worker.write_text("raise SystemExit('cuda out of memory')\n", "utf-8")
        with pytest.raises(AudioExtractionError, match="cuda out of memory"):
            separator.separate(tmp_path / "stereo.wav", tmp_path / "vocals.wav")
    finally:
        roformer_module.WORKER_PATH = original


class StemExtractor:
    def extract(self, video, audio) -> None:
        audio.write_bytes(b"mix")

    def extract_stereo(self, video, stereo) -> None:
        stereo.write_bytes(b"stereo")

    def resample_mono(self, source, target) -> None:
        target.write_bytes(source.read_bytes())

    def extract_vocal_stem(self, stereo, instrumental, vocals) -> None:
        vocals.write_bytes(b"subtracted")


class FakeStemSeparator:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def separate(self, stereo: Path, vocals: Path) -> None:
        if self.fail:
            raise AudioExtractionError("no gpu")
        vocals.write_bytes(b"clean")


class RecordingRemover:
    def __init__(self) -> None:
        self.calls = 0

    def remove_vocals(self, stereo: Path, instrumental: Path) -> None:
        self.calls += 1
        instrumental.write_bytes(b"instrumental")


def make_pipeline(tmp_path: Path, **options) -> tuple[TranscriptionPipeline, Path]:
    database = Database(tmp_path / "jobs.sqlite3")
    database.initialize()
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "input.mp4").write_bytes(b"video")
    return (
        TranscriptionPipeline(
            database=database,
            extractor=StemExtractor(),
            transcriber=None,
            aligner=LyricTimelineAligner(),
            **options,
        ),
        job_dir,
    )


def test_clean_stem_is_kept_next_to_the_regular_stem(
    tmp_path: Path,
) -> None:
    remover = RecordingRemover()
    pipeline, job_dir = make_pipeline(
        tmp_path,
        vocal_remover=remover,
        vocal_stem_separator=FakeStemSeparator(),
        transcribe_vocal_stem=True,
    )

    audio = pipeline._separate(
        job_dir / "input.mp4",
        job_dir / "audio_instrumental.wav",
        job_dir / "audio_vocals.wav",
        required=False,
        fallback=job_dir / "audio.wav",
    )

    # Recognition and alignment keep the regular stem; the Roformer stem is
    # stored next to it for finding rests and for listening.
    assert audio == job_dir / "audio_vocals.wav"
    assert audio.read_bytes() == b"subtracted"
    assert (job_dir / "audio_vocals_clean.wav").read_bytes() == b"clean"
    assert remover.calls == 1
    assert pipeline._has_clean_stem(job_dir)
    assert not (job_dir / "audio_vocals_full.wav").exists()
    assert not (job_dir / "audio_stereo.wav").exists()


def test_failed_clean_stem_leaves_the_regular_stem_and_no_rest_detection(
    tmp_path: Path,
) -> None:
    remover = RecordingRemover()
    pipeline, job_dir = make_pipeline(
        tmp_path,
        vocal_remover=remover,
        vocal_stem_separator=FakeStemSeparator(fail=True),
        transcribe_vocal_stem=True,
    )

    audio = pipeline._separate(
        job_dir / "input.mp4",
        job_dir / "audio_instrumental.wav",
        job_dir / "audio_vocals.wav",
        required=False,
        fallback=job_dir / "audio.wav",
    )

    assert audio.read_bytes() == b"subtracted"
    assert remover.calls == 1
    assert not pipeline._has_clean_stem(job_dir)


def test_timeline_respects_rests_only_with_a_clean_stem(tmp_path: Path) -> None:
    pipeline, job_dir = make_pipeline(tmp_path)
    write_stem(job_dir / "audio_vocals.wav", [(2.0, 14.0), (24.0, 36.0)])
    lyrics = lyrics_of(ROWS[:3])
    # ASR put line 3 into the interlude although it is sung right after it.
    transcript = transcript_of(
        [(ROWS[0], 4_000), (ROWS[1], 8_000), (ROWS[2], 16_000)]
    )

    untrusted = pipeline._build_timeline(job_dir, lyrics, transcript)
    assert untrusted.lines[2].start_ms == 16_000
    assert not (job_dir / "alignment_notes.json").exists()

    # Only the dedicated Roformer stem is trusted for finding rests.
    (job_dir / "audio_vocals.wav").replace(job_dir / "audio_vocals_clean.wav")
    trusted = pipeline._build_timeline(job_dir, lyrics, transcript)

    assert abs(trusted.lines[2].start_ms - 24_000) <= 400
    notes = json.loads((job_dir / "alignment_notes.json").read_text("utf-8"))
    assert notes["moved_lines"] == [2]
    assert notes["unresolved_lines"] == []
    assert any(abs(start - 14_000) <= 400 for start, _ in notes["rests"])
