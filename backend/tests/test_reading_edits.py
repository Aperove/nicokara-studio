from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.ai.whisper import (
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
)
from app.alignment.aligner import LyricTimelineAligner
from app.alignment.editing import MANUALLY_EDITED
from app.core.config import Settings
from app.lyrics.models import LyricDocument, LyricLine, LyricToken
from app.lyrics.readings import ReadingEditError, apply_reading_edits, clean_reading
from app.main import create_app


def sample_lyrics() -> LyricDocument:
    # The dictionary read 今日 as きょう although it is sung こんにち here.
    return LyricDocument(
        provider="local",
        source_text="今日は\n晴れ",
        lines=[
            LyricLine(
                "今日は",
                "今日は",
                "きょうは",
                [LyricToken("今日", "きょう"), LyricToken("は", "は")],
            ),
            LyricLine("晴れ", "晴れ", "はれ", [LyricToken("晴れ", "はれ")]),
        ],
    )


def sample_timeline(lyrics: LyricDocument):
    words = [
        TranscriptWord("きょう", 10_000, 11_200, 0.9),
        TranscriptWord("は", 11_200, 11_600, 0.9),
        TranscriptWord("はれ", 14_000, 15_000, 0.9),
    ]
    transcript = TranscriptDocument(
        "ja", 1.0, 30.0, "",
        [TranscriptSegment(0, "", 10_000, 15_000, -0.1, 0.0, words)],
    )
    return LyricTimelineAligner().align(lyrics, transcript)


def test_a_corrected_reading_rebuilds_the_moras_inside_the_same_span() -> None:
    lyrics = sample_lyrics()
    timeline = sample_timeline(lyrics)
    token_before = timeline.lines[0].tokens[0]

    new_lyrics, new_timeline, changed = apply_reading_edits(
        lyrics, timeline, {(0, 0): "こんにち"}
    )

    assert changed == [0]
    assert new_lyrics.lines[0].tokens[0].reading == "こんにち"
    assert new_lyrics.lines[0].reading == "こんにちは"
    token = new_timeline.lines[0].tokens[0]
    assert token.reading == "こんにち"
    assert (token.start_ms, token.end_ms) == (token_before.start_ms, token_before.end_ms)
    assert [mora.reading for mora in token.moras] == ["こ", "ん", "に", "ち"]
    assert token.moras[0].start_ms == token.start_ms
    assert token.moras[-1].end_ms == token.end_ms
    assert all(a.end_ms == b.start_ms for a, b in zip(token.moras, token.moras[1:]))
    assert new_timeline.lines[0].reading == "こんにちは"
    assert MANUALLY_EDITED in new_timeline.warnings
    # nothing else moves
    assert new_timeline.lines[0].tokens[1] == timeline.lines[0].tokens[1]
    assert new_timeline.lines[1] == timeline.lines[1]


def test_an_unchanged_reading_changes_nothing() -> None:
    lyrics = sample_lyrics()
    timeline = sample_timeline(lyrics)

    new_lyrics, new_timeline, changed = apply_reading_edits(
        lyrics, timeline, {(0, 0): "きょう"}
    )

    assert changed == []
    assert new_lyrics is lyrics and new_timeline is timeline


@pytest.mark.parametrize(
    "reading", ["", "   ", "kyou", "今日", "きょう!", "あ" * 65]
)
def test_readings_must_be_kana(reading: str) -> None:
    with pytest.raises(ReadingEditError):
        clean_reading(reading)


def test_kana_variants_are_accepted() -> None:
    assert clean_reading(" こん にち ") == "こんにち"
    assert clean_reading("コーヒー") == "コーヒー"


@pytest.mark.parametrize("position", [(5, 0), (0, 9)])
def test_edits_for_missing_tokens_are_rejected(position: tuple[int, int]) -> None:
    lyrics = sample_lyrics()
    with pytest.raises(ReadingEditError):
        apply_reading_edits(lyrics, sample_timeline(lyrics), {position: "あ"})


class IdleRunner:
    can_accept = True
    pipeline = None

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def enqueue(self, job_id: str, **_: object) -> None:
        pass


def test_readings_endpoint_updates_lyrics_and_timeline(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path / "data",
        storage_dir=tmp_path / "jobs",
        processing_enabled=False,
        cleanup_enabled=False,
    )
    mp4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isom" + b"video-data"
    with TestClient(create_app(settings, runner=IdleRunner())) as client:
        job_id = client.post(
            "/api/v1/jobs",
            files={"video": ("song.mp4", mp4, "video/mp4")},
            data={"lyrics_text": "今日は\n晴れ"},
        ).json()["id"]
        job_dir = tmp_path / "jobs" / job_id
        lyrics = sample_lyrics()
        timeline_path = job_dir / "timeline.json"
        timeline_path.write_text(
            json.dumps(sample_timeline(lyrics).to_dict()), encoding="utf-8"
        )
        (job_dir / "lyrics_processed.json").write_text(
            json.dumps(lyrics.to_dict()), encoding="utf-8"
        )
        client.app.state.database.update_job_state(
            job_id,
            status="AWAITING_REVIEW",
            stage="REVIEW_PENDING",
            progress=96,
            timeline_path=timeline_path,
        )
        base = f"/api/v1/jobs/{job_id}"

        review = client.get(f"{base}/review").json()
        assert review["lyrics_provider"] == "local"
        assert review["can_edit_readings"] is True

        rejected = client.put(
            f"{base}/readings",
            json={"edits": [{"line": 0, "token": 0, "reading": "kyou"}]},
        )
        assert rejected.status_code == 422

        saved = client.put(
            f"{base}/readings",
            json={"edits": [{"line": 0, "token": 0, "reading": "こんにち"}]},
        )
        assert saved.status_code == 200
        assert saved.json()["changed_lines"] == [0]

        stored_lyrics = json.loads((job_dir / "lyrics_processed.json").read_text("utf-8"))
        stored_timeline = json.loads(timeline_path.read_text("utf-8"))
        assert stored_lyrics["lines"][0]["tokens"][0]["reading"] == "こんにち"
        assert stored_timeline["lines"][0]["tokens"][0]["reading"] == "こんにち"
        assert MANUALLY_EDITED in stored_timeline["warnings"]
