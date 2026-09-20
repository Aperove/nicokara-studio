"""Forced-alignment worker built on karatimer.

karatimer (https://github.com/Jerry-at-GH/karatimer, Apache-2.0) aligns known
Japanese lyrics to a whole song with a CTC model fine-tuned on karaoke
timing, NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn, and refines onsets
with a second wav2vec2 model.  Note that the NextFire model is licensed
CC-BY-NC-SA-4.0: non-commercial use only.

Runs as a standalone script under its own interpreter (one that has
``karatimer`` and its PyTorch stack installed), so the API process never
imports PyTorch.  It therefore must not import anything from ``app``.

    python karatimer_worker.py <request.json> <response.json>

Request:  {"media": path, "device": "cuda" | "cpu" | null,
           "chunks": [{"start_ms": int, "end_ms": int | null,
                       "lines": [{"index": int,
                                  "units": [{"text": str, "reading": str}]}]}]}
Response: {"duration_ms": int,
           "units": [{"line": int, "text": str,
                      "start_ms": int, "end_ms": int}]}
"""
from __future__ import annotations

import json
import sys
from itertools import chain
from pathlib import Path

SAMPLE_RATE = 16_000

# Python puts a script's own directory first on sys.path.  Nothing next to this
# file may shadow the third-party packages imported below.
_HERE = Path(__file__).resolve().parent
sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != _HERE]


def decode(media_path: str):
    """Mono 16 kHz samples and the offset of the audio track, as karatimer
    itself decodes media, so its timings refer to the media's own clock."""
    import av
    import numpy as np

    with av.open(media_path) as media:
        if not media.streams.audio:
            raise SystemExit("media has no audio track")
        stream = media.streams.audio[0]
        origin_ms = 1000 * (
            float((stream.start_time or 0) * stream.time_base)
            - (media.start_time or 0) / av.time_base
        )
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        samples = [
            output.to_ndarray().reshape(-1)
            for frame in chain(media.decode(stream), [None])
            for output in resampler.resample(frame)
        ]
    wave = np.concatenate(samples).astype(np.float32) / 32768
    return wave, origin_ms


def main(request_path: str, response_path: str) -> None:
    import torch
    from karatimer.alignment import align

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    device = request.get("device") or ("cuda" if torch.cuda.is_available() else "cpu")
    if device == "cuda" and not torch.cuda.is_available():
        device = "cpu"
    wave, origin_ms = decode(request["media"])
    duration_ms = round(len(wave) / SAMPLE_RATE * 1000)

    units: list[dict] = []
    for chunk in request["chunks"]:
        # Chunk bounds are on the media clock; samples start at origin_ms.
        start_ms = max(0, chunk["start_ms"] - origin_ms)
        end_ms = (
            duration_ms
            if chunk.get("end_ms") is None
            else min(duration_ms, chunk["end_ms"] - origin_ms)
        )
        piece = wave[
            int(start_ms * SAMPLE_RATE / 1000) : int(end_ms * SAMPLE_RATE / 1000)
        ]
        lines = [
            [
                {"line": line["index"], "text": unit["text"], "reading": unit["reading"]}
                for unit in line["units"]
            ]
            for line in chunk["lines"]
            if line["units"]
        ]
        if not lines or len(piece) < 400:
            continue
        align(piece, lines, device)
        for line in lines:
            for unit in line:
                units.append(
                    {
                        "line": unit["line"],
                        "text": unit["text"],
                        "start_ms": round(unit["start_ms"] + start_ms + origin_ms),
                        "end_ms": round(unit["end_ms"] + start_ms + origin_ms),
                    }
                )

    Path(response_path).write_text(
        json.dumps({"duration_ms": duration_ms, "units": units}, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
