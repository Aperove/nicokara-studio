"""Forced-alignment worker for Qwen3-ForcedAligner.

Runs as a standalone script under its own interpreter (one that has
``torch`` and ``qwen-asr`` installed), so the API process never imports
PyTorch and GPU memory is released as soon as a song is done.  It therefore
must not import anything from ``app``.

    python qwen_worker.py <request.json> <response.json>

Request:  {"audio": path, "model": name, "device": "cuda:0",
           "chunks": [{"start_ms": int, "end_ms": int,
                       "lines": [{"index": int, "text": str}]}]}
Response: {"units": [{"line": int, "text": str,
                      "start_ms": int, "end_ms": int}]}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(request_path: str, response_path: str) -> None:
    import soundfile as sf
    import torch
    from qwen_asr import Qwen3ForcedAligner

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    wave, sample_rate = sf.read(request["audio"], dtype="float32")
    if wave.ndim > 1:
        wave = wave.mean(axis=1)

    device = request.get("device", "cuda:0")
    if device.startswith("cuda") and not torch.cuda.is_available():
        device = "cpu"
    model = Qwen3ForcedAligner.from_pretrained(
        request["model"],
        dtype=torch.bfloat16 if device.startswith("cuda") else torch.float32,
        device_map=device,
    )
    processor = model.aligner_processor
    tokenize = processor.tokenize_japanese

    units: list[dict] = []
    for chunk in request["chunks"]:
        # The model is trained on word units; tokenise per line so every
        # unit keeps the index of the lyric line it belongs to.
        words = [
            (word, line["index"])
            for line in chunk["lines"]
            for word in tokenize(line["text"])
        ]
        if not words:
            continue
        start = int(chunk["start_ms"] * sample_rate / 1000)
        end = int(chunk["end_ms"] * sample_rate / 1000)
        processor.tokenize_japanese = lambda _text, w=words: [x for x, _ in w]
        try:
            result = model.align(
                audio=(wave[start:end], sample_rate),
                text="-",
                language="Japanese",
            )[0]
        finally:
            processor.tokenize_japanese = tokenize
        for item, (word, line_index) in zip(result, words, strict=True):
            units.append(
                {
                    "line": line_index,
                    "text": word,
                    "start_ms": chunk["start_ms"] + round(item.start_time * 1000),
                    "end_ms": chunk["start_ms"] + round(item.end_time * 1000),
                }
            )

    Path(response_path).write_text(
        json.dumps({"units": units}, ensure_ascii=False),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
