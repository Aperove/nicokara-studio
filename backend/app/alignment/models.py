from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AlignedMora:
    reading: str
    start_ms: int
    end_ms: int
    matched: bool
    confidence: float


@dataclass(frozen=True)
class AlignedToken:
    surface: str
    reading: str
    start_ms: int
    end_ms: int
    confidence: float
    moras: list[AlignedMora] = field(default_factory=list)


@dataclass(frozen=True)
class AlignedLine:
    surface: str
    reading: str
    start_ms: int
    end_ms: int
    confidence: float
    tokens: list[AlignedToken] = field(default_factory=list)


@dataclass(frozen=True)
class LyricTimeline:
    confidence: float
    lines: list[AlignedLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LyricTimeline:
        return cls(
            confidence=float(data["confidence"]),
            warnings=list(data.get("warnings", [])),
            lines=[
                AlignedLine(
                    surface=line["surface"],
                    reading=line["reading"],
                    start_ms=int(line["start_ms"]),
                    end_ms=int(line["end_ms"]),
                    confidence=float(line["confidence"]),
                    tokens=[
                        AlignedToken(
                            surface=token["surface"],
                            reading=token["reading"],
                            start_ms=int(token["start_ms"]),
                            end_ms=int(token["end_ms"]),
                            confidence=float(token["confidence"]),
                            moras=[
                                AlignedMora(**mora)
                                for mora in token.get("moras", [])
                            ],
                        )
                        for token in line.get("tokens", [])
                    ],
                )
                for line in data.get("lines", [])
            ],
        )
