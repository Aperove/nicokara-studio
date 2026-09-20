from __future__ import annotations

import pytest

from app.alignment.models import AlignedLine, AlignedToken
from app.subtitle import font_metrics
from app.subtitle.ass_generator import AssConfig, AssGenerator
from app.subtitle.ruby import ruby_placements


def line_of(*tokens: tuple[str, str]) -> AlignedLine:
    surface = "".join(surface for surface, _ in tokens)
    return AlignedLine(
        surface=surface,
        reading="".join(reading for _, reading in tokens),
        start_ms=0,
        end_ms=4_000,
        confidence=1.0,
        tokens=[
            AlignedToken(surface, reading, index * 1_000, (index + 1) * 1_000, 1.0)
            for index, (surface, reading) in enumerate(tokens)
        ],
    )


LINE = line_of(("あ", "あ"), ("山", "やま"), ("の", "の"), ("川", "かわ"))


def test_ruby_is_centred_with_the_measured_width_of_the_text_before_it() -> None:
    # a font whose glyphs are exactly as wide as the font size
    placements = ruby_placements(
        LINE,
        play_res_x=1920,
        baseline_y=800,
        base_font_size=100,
        center_x=960,
        measure=lambda text: 100.0 * len(text),
    )

    # the line is 400 wide and starts at 760; 山 spans 860-960, 川 1060-1160
    assert [(ruby.text, ruby.x) for ruby in placements] == [
        ("やま", 910),
        ("かわ", 1110),
    ]


def test_the_estimate_pulls_ruby_towards_the_centre_for_a_wide_font() -> None:
    estimated = ruby_placements(
        LINE, play_res_x=1920, baseline_y=800, base_font_size=100, center_x=960
    )

    # 0.68 of the font size per glyph: right for Noto Sans CJK, not here
    assert [ruby.x for ruby in estimated] == [926, 1062]


def test_a_wide_font_is_shrunk_until_the_line_really_fits() -> None:
    generator = AssGenerator(config=AssConfig(base_font_size=120))
    estimated_size, _ = generator._auto_font_size(_timeline(24))

    generator._measure = lambda text, size: size * len(text)
    measured_size, _ = generator._auto_font_size(_timeline(24))

    assert measured_size < estimated_size
    # the narrower slot leaves 2 * 0.35 * 1920 * 0.92 pixels
    assert 24 * measured_size <= 2 * 0.35 * 1920 * 0.92


def _timeline(characters: int):
    from app.alignment.models import LyricTimeline

    return LyricTimeline(1.0, [line_of(("あ" * characters, "あ" * characters))], [])


def test_a_font_that_is_not_installed_is_replaced_by_one_that_is(monkeypatch) -> None:
    monkeypatch.setattr(
        font_metrics, "installed_faces", lambda: {"meiryo": [], "ms gothic": []}
    )

    assert font_metrics.installed_font_name("Nonexistent Sans") == "Meiryo"
    assert font_metrics.installed_font_name("MS Gothic") == "MS Gothic"
    monkeypatch.setattr(font_metrics, "installed_faces", lambda: {})
    assert font_metrics.installed_font_name("Nonexistent Sans") == "Nonexistent Sans"


def test_installed_fonts_are_measured_in_proportion_to_the_font_size() -> None:
    pytest.importorskip("PIL")
    font_metrics.installed_faces.cache_clear()
    family = next(
        (
            name
            for name in ("noto sans cjk jp", "yu gothic", "meiryo", "ms gothic")
            if name in font_metrics.installed_faces()
        ),
        None,
    )
    if family is None:
        pytest.skip("no Japanese font installed")
    measure = font_metrics.measure_for(family)

    assert measure is not None
    width = measure("漢字", 100)
    # two full-width glyphs, each between 0.6 and 1.0 of the font size
    assert 120 <= width <= 200
    assert measure("漢字", 50) == pytest.approx(width / 2)
    assert font_metrics.measure_for("no such font anywhere") is None
