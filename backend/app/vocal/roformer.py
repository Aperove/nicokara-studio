from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Sequence

from app.video.audio import AudioExtractionError


WORKER_PATH = Path(__file__).with_name("roformer_worker.py")
DEFAULT_ROFORMER_MODEL = "vocals_mel_band_roformer.ckpt"


class RoformerVocalStemSeparator:
    """Isolate the vocals with a Roformer model in a separate interpreter.

    The stem is far cleaner than "mix minus MDX instrumental": interludes
    become quiet enough to be recognised as such, which the timeline
    alignment relies on.
    """

    def __init__(
        self,
        *,
        python_command: Sequence[str],
        model_dir: Path,
        model: str = DEFAULT_ROFORMER_MODEL,
        timeout_seconds: int = 1800,
    ) -> None:
        self.python_command = tuple(python_command)
        self.model_dir = model_dir
        self.model = model
        self.timeout_seconds = timeout_seconds

    def separate(self, stereo_path: Path, vocals_path: Path) -> None:
        vocals_path.parent.mkdir(parents=True, exist_ok=True)
        vocals_path.unlink(missing_ok=True)
        request_path = vocals_path.parent / "vocal_stem_request.json"
        request_path.write_text(
            json.dumps(
                {
                    "input": str(stereo_path.resolve()),
                    "output": str(vocals_path.resolve()),
                    "model": self.model,
                    "model_dir": str(self.model_dir.resolve()),
                }
            ),
            encoding="utf-8",
        )
        try:
            subprocess.run(
                [*self.python_command, str(WORKER_PATH), str(request_path)],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "worker exited with an error").strip()
            raise AudioExtractionError(detail[-2000:]) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AudioExtractionError(str(exc)) from exc
        finally:
            request_path.unlink(missing_ok=True)
        if not vocals_path.is_file() or vocals_path.stat().st_size == 0:
            raise AudioExtractionError("Roformer produced no vocal stem")
