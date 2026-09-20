from __future__ import annotations

import re
from dataclasses import replace
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.subtitle.ass_generator import AssConfig


_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
# Font names end up inside a comma-separated ASS style line.
_FONT_NAME = re.compile(r"^[^,{}\\\r\n\x00-\x1f]{1,64}$")

_VERTICAL_SLOTS = {
    "bottom": (0.62, 0.78),
    "middle": (0.42, 0.58),
    "top": (0.16, 0.32),
}
_HORIZONTAL_SLOTS = {
    "staggered": (0.35, 0.65),
    "centered": (0.5, 0.5),
}


def ass_color(hex_color: str, *, alpha: int = 0) -> str:
    """Convert #RRGGBB to the ASS &HAABBGGRR form."""
    red, green, blue = hex_color[1:3], hex_color[3:5], hex_color[5:7]
    return f"&H{alpha:02X}{blue}{green}{red}".upper()


class SubtitleStyle(BaseModel):
    """User-facing karaoke subtitle options for a single job."""

    model_config = ConfigDict(extra="forbid")

    font_name: str = "Noto Sans CJK JP"
    font_size: int = Field(default=120, ge=40, le=160)
    sung_color: str = "#FF0000"
    unsung_color: str = "#000000"
    outline_color: str = "#FFFFFF"
    show_ruby: bool = True
    glow: bool = True
    layout: Literal["staggered", "centered"] = "staggered"
    vertical_position: Literal["bottom", "middle", "top"] = "bottom"
    lead_in_ms: int = Field(default=3000, ge=0, le=10000)

    @field_validator("font_name")
    @classmethod
    def safe_font_name(cls, value: str) -> str:
        value = value.strip()
        if not _FONT_NAME.fullmatch(value):
            raise ValueError("unsupported font name")
        return value

    @field_validator("sung_color", "unsung_color", "outline_color")
    @classmethod
    def hex_color(cls, value: str) -> str:
        if not _HEX_COLOR.fullmatch(value):
            raise ValueError("colors must use the #RRGGBB form")
        return value.upper()

    def apply_to(self, config: AssConfig) -> AssConfig:
        upper_y, lower_y = _VERTICAL_SLOTS[self.vertical_position]
        upper_x, lower_x = _HORIZONTAL_SLOTS[self.layout]
        return replace(
            config,
            font_name=self.font_name,
            base_font_size=self.font_size,
            sung_color=ass_color(self.sung_color),
            unsung_color=ass_color(self.unsung_color),
            outline_color=ass_color(self.outline_color),
            glow_color=ass_color(self.sung_color, alpha=0x40),
            show_ruby=self.show_ruby,
            glow=self.glow,
            upper_slot_x_ratio=upper_x,
            upper_slot_y_ratio=upper_y,
            lower_slot_x_ratio=lower_x,
            lower_slot_y_ratio=lower_y,
            section_lead_ms=self.lead_in_ms,
        )
