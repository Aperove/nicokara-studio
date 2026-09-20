from __future__ import annotations

import pytest

from app.lyrics.processor import OpenJTalkLyricProcessor, openjtalk_available


def node(string: str, read: str) -> dict[str, str]:
    return {"string": string, "read": read}


def processor_with(nodes_by_line: dict[str, list[dict[str, str]]]):
    return OpenJTalkLyricProcessor(frontend=lambda line: nodes_by_line[line])


def test_analysed_words_become_tokens_with_hiragana_readings() -> None:
    document = processor_with(
        {"今日は晴れ": [node("今日", "キョウ"), node("は", "ハ"), node("晴れ", "ハレ")]}
    ).process("今日は晴れ")

    line = document.lines[0]
    assert document.provider == "openjtalk"
    assert [(t.surface, t.reading) for t in line.tokens] == [
        ("今日", "きょう"),
        ("は", "は"),
        ("晴れ", "はれ"),
    ]
    assert line.reading == "きょうははれ"


def test_tokens_always_rebuild_the_original_text() -> None:
    # The analyser writes ASCII full-width, spells numbers out, drops spaces
    # and reads punctuation as a symbol.
    text = "ABC 12、ねえ！"
    document = processor_with(
        {
            text: [
                node("ＡＢＣ", "エービーシー"),
                node("十", "ジュウ"),
                node("二", "ニ"),
                node("、", "、"),
                node("ねえ", "ネエ"),
                node("！", "！"),
            ]
        }
    ).process(text)

    tokens = document.lines[0].tokens
    assert "".join(token.surface for token in tokens) == text
    assert [(t.surface, t.reading) for t in tokens] == [
        ("ABC", "えーびーしー"),
        (" ", ""),
        ("12", "じゅうに"),
        ("、", ""),
        ("ねえ", "ねえ"),
        ("！", ""),
    ]


class RecordingFallback:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def process(self, text: str):
        from app.lyrics.processor import LocalJapaneseLyricProcessor

        self.lines.append(text)
        return LocalJapaneseLyricProcessor().process(text)


@pytest.mark.parametrize("problem", ["crash", "nonsense"])
def test_a_line_that_cannot_be_mapped_back_uses_the_dictionary(problem: str) -> None:
    def frontend(line: str):
        if line == "二行目":
            if problem == "crash":
                raise RuntimeError("analyser failed")
            return []  # nothing recognised: leftover text gets no reading
        return [node("一行目", "イチギョウメ")]

    fallback = RecordingFallback()
    document = OpenJTalkLyricProcessor(frontend=frontend, fallback=fallback).process(
        "一行目\n二行目"
    )

    assert [line.surface for line in document.lines] == ["一行目", "二行目"]
    assert document.lines[0].reading == "いちぎょうめ"
    if problem == "crash":
        assert fallback.lines == ["二行目"]
        assert "reading_fallback_for_some_lines" in document.warnings
        assert document.lines[1].reading
    else:
        # an empty analysis still rebuilds the line; it simply has no reading
        assert "".join(t.surface for t in document.lines[1].tokens) == "二行目"


@pytest.mark.skipif(not openjtalk_available(), reason="pyopenjtalk not installed")
def test_inflected_verbs_get_their_native_reading() -> None:
    # A per-character dictionary reads these kanji with their Sino-Japanese
    # reading; the analyser knows the verbs.
    document = OpenJTalkLyricProcessor().process("紡いで\n繋いで\n灯す明かり")

    assert [line.reading for line in document.lines] == [
        "つむいで",
        "つないで",
        "ともすあかり",
    ]
    for line in document.lines:
        assert "".join(token.surface for token in line.tokens) == line.surface
