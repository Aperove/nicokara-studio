from __future__ import annotations

from dataclasses import dataclass, replace

from app.alignment.models import AlignedLine, LyricTimeline
from app.subtitle.karaoke_effect import (
    escape_ass_text,
    line_chunks,
    render_karaoke,
)
from app.subtitle.ruby import ruby_placements, text_width_units

_CHAR_WIDTH_RATIO = 0.68


@dataclass(frozen=True)
class AssConfig:
    play_res_x: int = 1920
    play_res_y: int = 1080
    font_name: str = "Noto Sans CJK JP"
    base_font_size: int = 120
    ruby_font_size: int = 48
    upper_slot_x_ratio: float = 0.35
    upper_slot_y_ratio: float = 0.62
    lower_slot_x_ratio: float = 0.65
    lower_slot_y_ratio: float = 0.78
    fade_in_ms: int = 180
    fade_out_ms: int = 220
    section_lead_ms: int = 3000
    long_interlude_ms: int = 12000
    sung_color: str = "&H000000FF"
    unsung_color: str = "&H00000000"
    outline_color: str = "&H00FFFFFF"
    max_line_width_ratio: float = 0.92
    glow_color: str = "&H400000FF"
    show_ruby: bool = True
    glow: bool = True


@dataclass(frozen=True)
class FixedSlot:
    x: int
    y: int


def ass_time(milliseconds: int) -> str:
    centiseconds = max(0, round(milliseconds / 10))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


class AssGenerator:
    def __init__(self, *, config: AssConfig | None = None) -> None:
        self.config = config or AssConfig()
        self.slots = self._slots(self.config)

    @staticmethod
    def _slots(config: AssConfig) -> tuple[FixedSlot, FixedSlot]:
        return (
            FixedSlot(
                x=round(config.play_res_x * config.upper_slot_x_ratio),
                y=round(config.play_res_y * config.upper_slot_y_ratio),
            ),
            FixedSlot(
                x=round(config.play_res_x * config.lower_slot_x_ratio),
                y=round(config.play_res_y * config.lower_slot_y_ratio),
            ),
        )

    def _auto_font_size(self, timeline: LyricTimeline) -> tuple[int, int]:
        """Pick base_font_size so every line fits around its centred slot."""
        base = self.config.base_font_size
        for line_index, line in enumerate(timeline.lines):
            slot = self.slots[line_index % 2]
            # A line is centred on its slot, so the usable width is twice
            # the distance from the slot to the nearest frame edge.
            available_px = (
                2
                * min(slot.x, self.config.play_res_x - slot.x)
                * self.config.max_line_width_ratio
            )
            units = max(1.0, text_width_units(line.surface))
            base = min(base, int(available_px / (units * _CHAR_WIDTH_RATIO)))
        base = max(40, base)
        ruby = max(20, round(base * 0.40))
        return base, ruby

    def generate(
        self,
        timeline: LyricTimeline,
        *,
        config: AssConfig | None = None,
    ) -> str:
        if config is not None:
            return AssGenerator(config=config).generate(timeline)
        auto_base, auto_ruby = self._auto_font_size(timeline)
        sized = AssGenerator(
            config=replace(
                self.config,
                base_font_size=auto_base,
                ruby_font_size=auto_ruby,
            )
        )
        return sized._generate_events(timeline)

    def _generate_events(self, timeline: LyricTimeline) -> str:
        events: list[str] = []
        for line_index, line in enumerate(timeline.lines):
            slot = self.slots[line_index % 2]
            display_start_ms = self._display_start(
                timeline.lines,
                line_index,
            )
            display_end_ms = self._display_end(
                timeline.lines,
                line_index,
            )
            display_start = ass_time(display_start_ms)
            display_end = ass_time(display_end_ms)
            singing_start = ass_time(line.start_ms)

            events.append(
                self._dialogue(
                    layer=1,
                    start=display_start,
                    end=display_end,
                    style="LyricBase",
                    tags=self._fixed_tags(slot),
                    text=escape_ass_text(line.surface),
                )
            )
            if self.config.show_ruby:
                events.extend(
                    self._ruby_events(
                        line,
                        slot,
                        display_start,
                        display_end,
                    )
                )

            karaoke = render_karaoke(line_chunks(line))
            events.append(
                self._dialogue(
                    layer=3,
                    start=singing_start,
                    end=display_end,
                    style="Highlight",
                    tags=self._fixed_tags(slot),
                    text=karaoke,
                )
            )
            if not self.config.glow:
                continue
            events.append(
                self._dialogue(
                    layer=4,
                    start=singing_start,
                    end=display_end,
                    style="Glow",
                    tags=self._fixed_tags(
                        slot,
                        extra=r"\blur8\bord5",
                    ),
                    text=karaoke,
                )
            )
        return self._header() + "\n" + "\n".join(events) + "\n"

    def _display_start(
        self,
        lines: list[AlignedLine],
        line_index: int,
    ) -> int:
        line = lines[line_index]
        starts_section = (
            line_index == 0
            or line.start_ms - lines[line_index - 1].end_ms
            >= self.config.long_interlude_ms
        )
        if starts_section:
            return max(0, line.start_ms - self.config.section_lead_ms)
        return lines[line_index - 1].start_ms

    def _display_end(
        self,
        lines: list[AlignedLine],
        line_index: int,
    ) -> int:
        line = lines[line_index]
        if line_index + 1 >= len(lines):
            return line.end_ms
        next_line = lines[line_index + 1]
        if (
            next_line.start_ms - line.end_ms
            >= self.config.long_interlude_ms
        ):
            return line.end_ms
        return next_line.start_ms

    def _ruby_events(
        self,
        line: AlignedLine,
        slot: FixedSlot,
        start: str,
        end: str,
    ) -> list[str]:
        return [
            self._dialogue(
                layer=2,
                start=start,
                end=end,
                style="Ruby",
                tags=(
                    rf"\an2\pos({ruby.x},{ruby.y})"
                    rf"\fs{self.config.ruby_font_size}"
                    r"\fscx100\fscy100\fsp0"
                    rf"\fad({self.config.fade_in_ms},"
                    rf"{self.config.fade_out_ms})"
                ),
                text=escape_ass_text(ruby.text),
            )
            for ruby in ruby_placements(
                line,
                play_res_x=self.config.play_res_x,
                baseline_y=slot.y,
                base_font_size=self.config.base_font_size,
                ruby_font_size=self.config.ruby_font_size,
                center_x=slot.x,
            )
        ]

    def _fixed_tags(
        self,
        slot: FixedSlot,
        *,
        extra: str = "",
    ) -> str:
        return (
            rf"\an5\pos({slot.x},{slot.y})"
            rf"\fs{self.config.base_font_size}"
            r"\fscx100\fscy100\fsp0"
            rf"\fad({self.config.fade_in_ms},{self.config.fade_out_ms})"
            f"{extra}"
        )

    @staticmethod
    def _dialogue(
        *,
        layer: int,
        start: str,
        end: str,
        style: str,
        tags: str,
        text: str,
    ) -> str:
        return (
            f"Dialogue: {layer},{start},{end},{style},,0,0,0,,"
            f"{{{tags}}}{text}"
        )

    def _header(self) -> str:
        return f"""[Script Info]
Title: ニコカラ自動生成器
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {self.config.play_res_x}
PlayResY: {self.config.play_res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: LyricBase,{self.config.font_name},{self.config.base_font_size},{self.config.unsung_color},{self.config.unsung_color},{self.config.outline_color},&H60000000,-1,0,0,0,100,100,0,0,1,5,2,5,40,40,40,1
Style: Ruby,{self.config.font_name},{self.config.ruby_font_size},{self.config.unsung_color},{self.config.unsung_color},{self.config.outline_color},&H60000000,-1,0,0,0,100,100,0,0,1,3,1,5,20,20,20,1
Style: Highlight,{self.config.font_name},{self.config.base_font_size},{self.config.sung_color},&HFF000000,&HFF000000,&HFF000000,-1,0,0,0,100,100,0,0,1,0,0,5,40,40,40,1
Style: Glow,{self.config.font_name},{self.config.base_font_size},{self.config.glow_color},&HFF000000,{self.config.glow_color},&HFF000000,-1,0,0,0,100,100,0,0,1,4,0,5,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""
