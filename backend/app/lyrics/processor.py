from __future__ import annotations

import json
import unicodedata
from dataclasses import replace
from typing import Any, Callable

from pykakasi import kakasi

from app.lyrics.models import LyricDocument, LyricLine, LyricToken


SYSTEM_PROMPT = """
你是日语歌词格式化器。只输出 JSON，不要输出 Markdown。
保持输入行顺序，为每行生成：
- surface：修正明显表记错误后的歌词
- reading：整行平假名读音
- tokens：用于 Ruby 注音的 surface/reading 数组
tokens 的 surface 拼接必须严格等于该行 surface。
输出格式：{"lines":[{"surface":"...","reading":"...","tokens":[...]}]}
""".strip()


def normalized_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


class LyricProcessingError(ValueError):
    """Raised when an AI lyric response cannot be safely consumed."""


class DeepSeekLyricProcessor:
    def __init__(self, *, client: Any) -> None:
        self.client = client

    def process(self, text: str) -> LyricDocument:
        source_lines = normalized_lines(text)
        source_text = "\n".join(source_lines)
        response = self.client.complete_json(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=json.dumps({"lines": source_lines}, ensure_ascii=False),
        )
        lines: list[LyricLine] = []
        for source, result in zip(source_lines, response["lines"], strict=True):
            tokens = [
                LyricToken(
                    surface=token["surface"],
                    reading=token["reading"],
                )
                for token in result["tokens"]
            ]
            if "".join(token.surface for token in tokens) != result["surface"]:
                raise LyricProcessingError("tokens do not reconstruct surface")
            lines.append(
                LyricLine(
                    source=source,
                    surface=result["surface"],
                    reading=result["reading"],
                    tokens=tokens,
                )
            )
        return LyricDocument(
            provider="deepseek",
            source_text=source_text,
            lines=lines,
        )


class LocalJapaneseLyricProcessor:
    def __init__(self) -> None:
        self.converter = kakasi()

    def process(self, text: str) -> LyricDocument:
        source_lines = normalized_lines(text)
        lines: list[LyricLine] = []
        for source in source_lines:
            converted = self.converter.convert(source)
            tokens = [
                LyricToken(surface=item["orig"], reading=item["hira"])
                for item in converted
            ]
            lines.append(
                LyricLine(
                    source=source,
                    surface=source,
                    reading="".join(token.reading for token in tokens),
                    tokens=tokens,
                )
            )
        return LyricDocument(
            provider="local",
            source_text="\n".join(source_lines),
            lines=lines,
            warnings=["local_reading_may_be_inaccurate"],
        )


def _kana_reading(read: str) -> str:
    """Hiragana of an analyser reading; empty for symbols and the like."""
    kana = "".join(
        chr(ord(character) - 0x60) if "\u30a1" <= character <= "\u30f6" else character
        for character in read
    )
    letters = [
        character
        for character in kana
        if "\u3041" <= character <= "\u3096" or character == "ー"
    ]
    # a reading made only of long-vowel marks is a symbol, not a word
    return "".join(letters) if any(c != "ー" for c in letters) else ""


def openjtalk_frontend(text: str) -> list[dict[str, str]]:
    import pyopenjtalk

    return pyopenjtalk.run_frontend(text)


def openjtalk_available() -> bool:
    try:
        import pyopenjtalk  # noqa: F401
    except ImportError:
        return False
    return True


class OpenJTalkLyricProcessor:
    """Readings from morphological analysis instead of per-character lookup.

    A dictionary lookup reads the kanji of an inflected verb or adjective
    with its Sino-Japanese reading; an analyser that knows the word does
    not.  The analyser normalises its input (full-width letters, numbers
    spelled out, spaces dropped), so its words are mapped back onto the
    original text: the token surfaces always rebuild the line exactly.
    """

    def __init__(
        self,
        *,
        frontend: Callable[[str], list[dict[str, str]]] = openjtalk_frontend,
        fallback: Any | None = None,
    ) -> None:
        self.frontend = frontend
        self.fallback = fallback or LocalJapaneseLyricProcessor()

    def process(self, text: str) -> LyricDocument:
        source_lines = normalized_lines(text)
        lines: list[LyricLine] = []
        warnings = ["local_reading_may_be_inaccurate"]
        for source in source_lines:
            tokens = self._tokens(source)
            if tokens is None:
                # could not be mapped back onto the text: use the dictionary
                tokens = self.fallback.process(source).lines[0].tokens
                if "reading_fallback_for_some_lines" not in warnings:
                    warnings.append("reading_fallback_for_some_lines")
            lines.append(
                LyricLine(
                    source=source,
                    surface=source,
                    reading="".join(token.reading for token in tokens),
                    tokens=tokens,
                )
            )
        return LyricDocument(
            provider="openjtalk",
            source_text="\n".join(source_lines),
            lines=lines,
            warnings=warnings,
        )

    def _tokens(self, line: str) -> list[LyricToken] | None:
        try:
            nodes = self.frontend(line)
        except Exception:
            return None
        # normalised text, remembering which original character each
        # normalised character came from
        normalised: list[str] = []
        origin: list[int] = []
        for index, character in enumerate(line):
            for piece in unicodedata.normalize("NFKC", character):
                normalised.append(piece)
                origin.append(index)
        haystack = "".join(normalised)

        tokens: list[LyricToken] = []
        cursor = 0  # position in the normalised text
        consumed = 0  # position in the original line
        unplaced: list[str] = []  # readings of words not found in the text

        def emit(until: int, reading: str) -> None:
            nonlocal consumed
            if until <= consumed:
                return
            surface = line[consumed:until]
            consumed = until
            core = surface.strip()
            if not core:
                tokens.append(LyricToken(surface, ""))
                return
            # spaces the analyser dropped are not part of the word
            lead = surface[: len(surface) - len(surface.lstrip())]
            tail = surface[len(surface.rstrip()) :]
            if lead:
                tokens.append(LyricToken(lead, ""))
            tokens.append(LyricToken(core, reading))
            if tail:
                tokens.append(LyricToken(tail, ""))

        for node in nodes:
            word = unicodedata.normalize("NFKC", node.get("string", ""))
            reading = _kana_reading(node.get("read", ""))
            position = haystack.find(word, cursor) if word else -1
            if position == -1:
                unplaced.append(reading)
                continue
            # text the analyser rewrote (spelled-out numbers) or dropped
            emit(origin[position], "".join(unplaced))
            unplaced = []
            end = position + len(word)
            emit(origin[end - 1] + 1, reading)
            cursor = end
        emit(len(line), "".join(unplaced))

        if "".join(token.surface for token in tokens) != line:
            return None
        return tokens


class ResilientLyricProcessor:
    def __init__(self, *, primary: Any, fallback: Any) -> None:
        self.primary = primary
        self.fallback = fallback

    def process(self, text: str) -> LyricDocument:
        try:
            return self.primary.process(text)
        except Exception as exc:
            document = self.fallback.process(text)
            return replace(
                document,
                warnings=[
                    *document.warnings,
                    f"deepseek_fallback:{type(exc).__name__}",
                ],
            )
