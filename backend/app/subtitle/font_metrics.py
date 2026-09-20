"""Measure text the way the subtitle renderer will lay it out.

Ruby is placed at absolute coordinates above the word it belongs to, so the
width of the text before that word has to be known.  Guessing it from the
font size only works for the font the guess was calibrated on: a glyph of
Noto Sans CJK is 0.69 of the font size wide, one of BIZ UDGothic 1.0.

libass scales a face so that its ascent plus descent (the OS/2 "win"
metrics, falling back to hhea) equals the ASS font size; the em square is
whatever that leaves.  This module finds the installed font file, reads
those metrics and measures with Pillow at the resulting em size.
"""
from __future__ import annotations

import logging
import os
import struct
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable


logger = logging.getLogger(__name__)

Measure = Callable[[str, float], float]
"""(text, ASS font size) -> width in script pixels."""

_FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".otc"}
_FAMILY_NAME_IDS = {1, 4, 16}


@dataclass(frozen=True)
class FontFace:
    path: Path
    index: int
    bold: bool
    units_per_em: int
    line_units: int  # ascent + descent, in font units


def font_directories() -> list[Path]:
    if sys.platform == "win32":
        candidates = [
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts",
        ]
    elif sys.platform == "darwin":
        candidates = [
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path.home() / "Library/Fonts",
        ]
    else:
        candidates = [
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".fonts",
            Path.home() / ".local/share/fonts",
        ]
    return [path for path in candidates if path.is_dir()]


def _tables(data: bytes, offset: int) -> dict[bytes, tuple[int, int]]:
    count = struct.unpack_from(">H", data, offset + 4)[0]
    tables = {}
    for entry in range(count):
        tag, _, start, length = struct.unpack_from(
            ">4sIII", data, offset + 12 + entry * 16
        )
        tables[tag] = (start, length)
    return tables


def _names(data: bytes, start: int) -> tuple[set[str], bool]:
    """Family names in every language, and whether the face is a bold one."""
    _, count, strings = struct.unpack_from(">HHH", data, start)
    families: set[str] = set()
    bold = False
    for entry in range(count):
        platform, _, _, name_id, length, offset = struct.unpack_from(
            ">HHHHHH", data, start + 6 + entry * 12
        )
        if name_id not in _FAMILY_NAME_IDS and name_id != 2:
            continue
        raw = data[start + strings + offset : start + strings + offset + length]
        try:
            text = raw.decode("utf-16-be" if platform in (0, 3) else "mac_roman")
        except UnicodeDecodeError:
            continue
        text = text.strip().lower()
        if name_id == 2:
            bold = bold or "bold" in text
        elif text:
            families.add(text)
    return families, bold


def read_faces(path: Path) -> list[tuple[set[str], FontFace]]:
    """The faces of one font file, with the names they answer to."""
    data = path.read_bytes()
    if data[:4] == b"ttcf":
        count = struct.unpack_from(">I", data, 8)[0]
        offsets = struct.unpack_from(f">{count}I", data, 12)
    else:
        offsets = (0,)
    faces = []
    for index, offset in enumerate(offsets):
        tables = _tables(data, offset)
        if not {b"head", b"name", b"hhea"} <= tables.keys():
            continue
        units_per_em = struct.unpack_from(">H", data, tables[b"head"][0] + 18)[0]
        ascent, descent = struct.unpack_from(">hh", data, tables[b"hhea"][0] + 4)
        line_units = ascent - descent
        if b"OS/2" in tables and tables[b"OS/2"][1] >= 78:
            win_ascent, win_descent = struct.unpack_from(
                ">HH", data, tables[b"OS/2"][0] + 74
            )
            if win_ascent + win_descent:
                line_units = win_ascent + win_descent
        families, bold = _names(data, tables[b"name"][0])
        if families and units_per_em and line_units > 0:
            faces.append(
                (families, FontFace(path, index, bold, units_per_em, line_units))
            )
    return faces


@lru_cache(maxsize=1)
def installed_faces() -> dict[str, list[FontFace]]:
    by_family: dict[str, list[FontFace]] = {}
    for directory in font_directories():
        for path in directory.rglob("*"):
            if path.suffix.lower() not in _FONT_SUFFIXES:
                continue
            try:
                faces = read_faces(path)
            except (OSError, struct.error, IndexError):
                continue
            for families, face in faces:
                for family in families:
                    by_family.setdefault(family, []).append(face)
    return by_family


def find_face(font_name: str, *, bold: bool = True) -> FontFace | None:
    faces = installed_faces().get(font_name.strip().lower())
    if not faces:
        return None
    # the renderer asks for a bold face and takes a regular one if need be
    return next((face for face in faces if face.bold == bold), faces[0])


# Tried in this order when the chosen font is not on this machine.  Leaving
# the choice to the renderer would make the layout unpredictable.
FALLBACK_FONTS = (
    "Noto Sans CJK JP",
    "Noto Sans JP",
    "Yu Gothic",
    "Hiragino Sans",
    "Meiryo",
    "MS Gothic",
)


def installed_font_name(font_name: str) -> str:
    """The font itself when installed, else the first installed fallback."""
    faces = installed_faces()
    for candidate in (font_name, *FALLBACK_FONTS):
        if candidate.strip().lower() in faces:
            return candidate
    return font_name


@lru_cache(maxsize=64)
def _pillow_font(path: Path, index: int, em_px: float):
    from PIL import ImageFont

    return ImageFont.truetype(str(path), size=em_px, index=index)


def measure_with(face: FontFace) -> Measure:
    def measure(text: str, font_size: float) -> float:
        em_px = font_size * face.units_per_em / face.line_units
        # Pillow only takes whole and half sizes reliably: measure large and
        # scale, which also keeps the cache small.
        reference = 200.0
        font = _pillow_font(face.path, face.index, reference)
        return font.getlength(text) * em_px / reference

    return measure


@lru_cache(maxsize=32)
def measure_for(font_name: str, *, bold: bool = True) -> Measure | None:
    """A measuring function for an installed font, or None to estimate."""
    try:
        face = find_face(font_name, bold=bold)
        if face is None:
            logger.info("Font %r is not installed; ruby positions are estimated", font_name)
            return None
        measure = measure_with(face)
        measure("あ", 100)  # fails here rather than in the middle of a job
        return measure
    except Exception:
        logger.warning("Could not measure font %r", font_name, exc_info=True)
        return None
