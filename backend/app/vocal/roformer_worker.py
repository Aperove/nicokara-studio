"""Vocal stem worker for Roformer separation models.

Runs as a standalone script under its own interpreter (one that has
``torch`` and ``audio-separator`` installed), so the API process never
imports PyTorch.  It therefore must not import anything from ``app``.

    python roformer_worker.py <request.json>

Request: {"input": stereo wav path, "output": vocals wav path,
          "model": model filename, "model_dir": directory for model files}
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path


def main(request_path: str) -> None:
    from audio_separator.separator import Separator

    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    output = Path(request["output"])
    model_dir = Path(request["model_dir"])
    model_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as scratch:
        separator = Separator(
            log_level=logging.WARNING,
            model_file_dir=str(model_dir),
            output_dir=scratch,
            output_format="WAV",
            output_single_stem="Vocals",
        )
        separator.load_model(model_filename=request["model"])
        produced = separator.separate(request["input"], {"Vocals": "vocals"})
        candidates = [Path(scratch) / Path(name).name for name in produced]
        vocals = next(
            (path for path in candidates if path.is_file() and path.stat().st_size),
            None,
        )
        if vocals is None:
            raise SystemExit("The separation model produced no vocal stem")
        shutil.move(str(vocals), str(output))


if __name__ == "__main__":
    main(sys.argv[1])
