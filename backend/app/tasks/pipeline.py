from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.ai.whisper import TranscriptDocument
from app.alignment.editing import MANUALLY_EDITED, retime_line, trim_overlaps
from app.alignment.models import LyricTimeline
from app.alignment.refiner import realign_lines
from app.alignment.voice_activity import detect_rests, move_lines_out_of_rests
from app.core.database import Database
from app.lyrics.models import LyricDocument


logger = logging.getLogger(__name__)

PUBLIC_ERROR_MESSAGES = {
    "DOWNLOADING_VIDEO": (
        "Processing failed while downloading the video. "
        "Check server logs with this job ID."
    ),
    "REMOVING_VOCALS": (
        "Processing failed during vocal removal. "
        "Check server logs with this job ID."
    ),
    "EXTRACTING_AUDIO": (
        "Processing failed during audio extraction. "
        "Check server logs with this job ID."
    ),
    "TRANSCRIBING": (
        "Processing failed during audio transcription. "
        "Check server logs with this job ID."
    ),
    "PROCESSING_LYRICS": (
        "Processing failed during lyric processing. "
        "Check server logs with this job ID."
    ),
    "ALIGNING": (
        "Processing failed during lyric alignment. "
        "Check server logs with this job ID."
    ),
    "GENERATING_SUBTITLE": (
        "Processing failed during subtitle generation. "
        "Check server logs with this job ID."
    ),
    "RENDERING_VIDEO": (
        "Processing failed during video rendering. "
        "Check server logs with this job ID."
    ),
}


class TranscriptionPipeline:
    def __init__(
        self,
        *,
        database: Database,
        extractor: Any,
        transcriber: Any,
        vocal_remover: Any | None = None,
        lyric_processor: Any | None = None,
        aligner: Any | None = None,
        subtitle_generator: Any | None = None,
        video_renderer: Any | None = None,
        transcribe_vocal_stem: bool = False,
        lyrics_hint: bool = False,
        alignment_refiner: Any | None = None,
        vocal_stem_separator: Any | None = None,
        primary_aligner: Any | None = None,
        video_downloader: Any | None = None,
    ) -> None:
        self.database = database
        self.extractor = extractor
        self.transcriber = transcriber
        self.vocal_remover = vocal_remover
        self.lyric_processor = lyric_processor
        self.aligner = aligner
        self.subtitle_generator = subtitle_generator
        self.video_renderer = video_renderer
        self.transcribe_vocal_stem = transcribe_vocal_stem
        self.lyrics_hint = lyrics_hint
        self.alignment_refiner = alignment_refiner
        self.vocal_stem_separator = vocal_stem_separator
        self.primary_aligner = primary_aligner
        self.video_downloader = video_downloader

    # The Roformer stem.  It is quiet between phrases, so it shows where
    # nobody sings; recognition and alignment measured better on the regular
    # stem, which therefore stays in audio_vocals.wav.
    _CLEAN_STEM_FILE = "audio_vocals_clean.wav"

    def _separate(
        self,
        video_path: Path,
        instrumental_path: Path,
        vocals_path: Path,
        *,
        required: bool,
        fallback: Path,
    ) -> Path:
        """Split the mix; return the best audio to transcribe.

        The instrumental is mandatory only when the job asked for vocals
        off.  The vocal stem merely improves recognition and alignment, so
        any failure producing it falls back to the original mix.
        """
        job_dir = video_path.parent
        stereo_path = job_dir / "audio_stereo.wav"
        try:
            try:
                self.extractor.extract_stereo(video_path, stereo_path)
                if self.vocal_remover is not None:
                    self.vocal_remover.remove_vocals(
                        stereo_path, instrumental_path
                    )
            except Exception:
                if required:
                    raise
                logger.warning(
                    "Vocal separation failed; transcribing the full mix",
                    exc_info=True,
                )
                return fallback
            self._clean_vocal_stem(stereo_path, job_dir)
            if not self.transcribe_vocal_stem or self.vocal_remover is None:
                return fallback
            try:
                self.extractor.extract_vocal_stem(
                    stereo_path, instrumental_path, vocals_path
                )
            except Exception:
                logger.warning(
                    "Vocal stem extraction failed; transcribing the full mix",
                    exc_info=True,
                )
                return fallback
            return vocals_path if vocals_path.is_file() else fallback
        finally:
            stereo_path.unlink(missing_ok=True)

    def _clean_vocal_stem(self, stereo_path: Path, job_dir: Path) -> bool:
        """Isolate the vocals with the dedicated separation model, if any."""
        if self.vocal_stem_separator is None:
            return False
        clean_path = job_dir / self._CLEAN_STEM_FILE
        full_path = job_dir / "audio_vocals_full.wav"
        try:
            self.vocal_stem_separator.separate(stereo_path, full_path)
            self.extractor.resample_mono(full_path, clean_path)
        except Exception:
            logger.warning(
                "Roformer vocal separation failed; rests will not be detected",
                exc_info=True,
            )
            clean_path.unlink(missing_ok=True)
            return False
        finally:
            full_path.unlink(missing_ok=True)
        return clean_path.is_file()

    def _has_clean_stem(self, job_dir: Path) -> bool:
        return (job_dir / self._CLEAN_STEM_FILE).is_file()

    # Says which tool produced transcript.json.  A transcript that already
    # is a forced alignment of the lyrics needs no second refinement pass.
    _TRANSCRIPT_SOURCE_FILE = "transcript.source"
    _FORCED_SOURCE = "karatimer"
    _MIN_FORCED_CONFIDENCE = 0.6

    def _forced_transcript(
        self,
        job_dir: Path,
        media_path: Path,
        lyrics: Any,
    ) -> Any | None:
        """Align the known lyrics to the whole song, without recognition.

        Returns None when no forced aligner is configured or it fails, in
        which case the caller falls back to ASR.
        """
        source_path = job_dir / self._TRANSCRIPT_SOURCE_FILE
        if self.primary_aligner is None or self.aligner is None:
            return None
        try:
            transcript = self.primary_aligner.align_song(
                lyrics, media_path, work_dir=job_dir
            )
            confidence = self.aligner.align(lyrics, transcript).confidence
        except Exception:
            logger.warning(
                "Forced alignment of the whole song failed; using ASR instead",
                exc_info=True,
            )
            return None
        if confidence < self._MIN_FORCED_CONFIDENCE:
            logger.warning(
                "Forced alignment explained only %.0f%% of the lyrics; "
                "using ASR instead",
                confidence * 100,
            )
            return None
        source_path.write_text(self._FORCED_SOURCE + "\n", encoding="utf-8")
        return transcript

    def _is_forced_transcript(self, job_dir: Path) -> bool:
        source_path = job_dir / self._TRANSCRIPT_SOURCE_FILE
        return (
            source_path.is_file()
            and source_path.read_text(encoding="utf-8").strip()
            == self._FORCED_SOURCE
        )

    def _upgrade_transcript(self, job_dir: Path) -> None:
        """Re-align a job that was made with ASR, keeping the old transcript."""
        media_path = job_dir / "input.mp4"
        lyrics_path = job_dir / "lyrics_processed.json"
        transcript_path = job_dir / "transcript.json"
        if (
            self.primary_aligner is None
            or self._is_forced_transcript(job_dir)
            or not media_path.is_file()
            or not lyrics_path.is_file()
        ):
            return
        lyrics = LyricDocument.from_dict(
            json.loads(lyrics_path.read_text(encoding="utf-8"))
        )
        transcript = self._forced_transcript(job_dir, media_path, lyrics)
        if transcript is None:
            return
        if transcript_path.is_file():
            transcript_path.replace(job_dir / "transcript.asr.json")
        transcript_path.write_text(
            json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    _SOURCE_URL_FILE = "source_url.txt"

    def _download_video(self, job_id: str, video_path: Path) -> None:
        """Fetch the video of a job that was created from a link."""
        url_path = video_path.parent / self._SOURCE_URL_FILE
        if video_path.is_file() or not url_path.is_file():
            return
        if self.video_downloader is None:
            raise RuntimeError("Creating jobs from a link is not enabled")
        downloaded = self.video_downloader.download(
            url_path.read_text(encoding="utf-8").strip(), video_path
        )
        digest = hashlib.sha256()
        with video_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        title = "".join(
            character
            for character in downloaded.title
            if character.isprintable() and character not in '\\/:*?"<>|'
        ).strip()[:200]
        self.database.update_job_video(
            job_id,
            original_video_name=f"{title or '在线视频'}.mp4",
            video_size_bytes=video_path.stat().st_size,
            video_sha256=digest.hexdigest(),
        )

    def _transcribe(
        self,
        job_id: str,
        audio_path: Path,
        lyrics_path_value: str | None,
    ) -> Any:
        last_progress = 40

        def on_progress(fraction: float) -> None:
            nonlocal last_progress
            progress = 40 + int(34 * fraction)
            if progress > last_progress:
                last_progress = progress
                self.database.update_job_state(
                    job_id,
                    status="PROCESSING",
                    stage="TRANSCRIBING",
                    progress=progress,
                )

        options: dict[str, Any] = {"on_progress": on_progress}
        if self.lyrics_hint and lyrics_path_value:
            lyrics = Path(lyrics_path_value).read_text(encoding="utf-8")
            options["hotwords"] = " ".join(lyrics.split())
        return self.transcriber.transcribe(audio_path, **options)

    @staticmethod
    def _review_requested(job_dir: Path) -> bool:
        options_path = job_dir / "options.json"
        if not options_path.is_file():
            return False
        try:
            options = json.loads(options_path.read_text(encoding="utf-8"))
        except ValueError:
            return False
        return bool(options.get("review_before_render"))

    def _generate_subtitles(self, job_dir: Path, timeline: Any) -> str:
        """Render the ASS text, honouring the job's style.json if any."""
        style_path = job_dir / "style.json"
        base_config = getattr(self.subtitle_generator, "config", None)
        if not style_path.is_file() or base_config is None:
            return self.subtitle_generator.generate(timeline)
        from app.subtitle.style import SubtitleStyle

        style = SubtitleStyle.model_validate_json(
            style_path.read_text(encoding="utf-8")
        )
        styled = self.subtitle_generator.__class__(
            config=style.apply_to(base_config)
        )
        return styled.generate(timeline)

    # A refined timeline must still explain most of the lyrics; otherwise
    # the forced aligner went astray and the ASR-based timeline is kept.
    _MIN_REFINED_CONFIDENCE = 0.6

    def _build_timeline(
        self,
        job_dir: Path,
        lyrics: Any,
        transcript: Any,
    ) -> Any:
        """Align lyrics to the ASR output, then refine with forced alignment.

        ASR only has to place each line roughly; when a forced aligner is
        configured it re-times short excerpts against the known lyrics and
        the result goes through the same aligner.  Refinement is strictly
        optional: any failure keeps the ASR-based timeline.
        """
        timeline = self._respect_rests(
            job_dir,
            lyrics,
            self._refined_timeline(job_dir, lyrics, transcript),
            transcript.duration_seconds,
        )
        return self._respect_lrc(
            job_dir, lyrics, timeline, transcript.duration_seconds
        )

    def _refined_timeline(
        self,
        job_dir: Path,
        lyrics: Any,
        transcript: Any,
    ) -> Any:
        timeline = self.aligner.align(lyrics, transcript)
        if self.alignment_refiner is None or self._is_forced_transcript(job_dir):
            return timeline
        vocals_path = job_dir / "audio_vocals.wav"
        audio_path = vocals_path if vocals_path.is_file() else job_dir / "audio.wav"
        try:
            refined_transcript = self.alignment_refiner.refine(
                lyrics,
                timeline,
                audio_path,
                duration_seconds=transcript.duration_seconds,
                work_dir=job_dir,
            )
            refined = self.aligner.align(lyrics, refined_transcript)
        except Exception:
            logger.warning(
                "Forced alignment failed; keeping the ASR-based timeline",
                exc_info=True,
            )
            return timeline
        if refined.confidence < self._MIN_REFINED_CONFIDENCE:
            logger.warning(
                "Forced alignment matched only %.0f%% of the lyrics; "
                "keeping the ASR-based timeline",
                refined.confidence * 100,
            )
            return timeline
        return refined

    _NOTES_FILE = "alignment_notes.json"
    _LRC_STARTS_FILE = "lyrics_lrc.json"
    # LRC files are line-level and usually a little early, so they only
    # overrule the aligner when it is off by more than this.
    _LRC_TOLERANCE_MS = 2_000

    def _respect_lrc(
        self,
        job_dir: Path,
        lyrics: Any,
        timeline: Any,
        duration_seconds: float,
    ) -> Any:
        """Use LRC line times as a guard against grossly misplaced lines."""
        starts_path = job_dir / self._LRC_STARTS_FILE
        if not starts_path.is_file():
            return timeline
        try:
            starts = json.loads(starts_path.read_text(encoding="utf-8"))[
                "line_starts_ms"
            ]
        except (ValueError, KeyError):
            return timeline
        lines = list(timeline.lines)
        if len(starts) != len(lines):
            logger.warning(
                "LRC has %d timed lines but the lyrics have %d; ignoring it",
                len(starts),
                len(lines),
            )
            return timeline

        adjusted: list[int] = []
        for index, lrc_start in enumerate(starts):
            line = lines[index]
            if abs(line.start_ms - lrc_start) <= self._LRC_TOLERANCE_MS:
                continue
            ceiling = (
                starts[index + 1]
                if index + 1 < len(starts)
                else round(duration_seconds * 1000)
            )
            length = max(500, line.end_ms - line.start_ms)
            end_ms = max(lrc_start + 1, min(lrc_start + length, ceiling))
            lines[index] = retime_line(line, lrc_start, end_ms)
            adjusted.append(index)
        if not adjusted:
            return timeline

        repaired = replace(timeline, lines=lines)
        forced = self.primary_aligner or self.alignment_refiner
        if forced is not None:
            vocals_path = job_dir / "audio_vocals.wav"
            try:
                repaired, _ = realign_lines(
                    self.aligner,
                    forced,
                    lyrics,
                    repaired,
                    adjusted,
                    vocals_path if vocals_path.is_file() else job_dir / "audio.wav",
                    duration_seconds=duration_seconds,
                    work_dir=job_dir,
                )
            except Exception:
                logger.warning(
                    "Could not re-align the lines moved to their LRC time",
                    exc_info=True,
                )
        repaired = trim_overlaps(repaired)

        notes_path = job_dir / self._NOTES_FILE
        notes = (
            json.loads(notes_path.read_text(encoding="utf-8"))
            if notes_path.is_file()
            else {}
        )
        notes["lrc_adjusted_lines"] = adjusted
        notes_path.write_text(json.dumps(notes) + "\n", encoding="utf-8")
        return repaired

    def _respect_rests(
        self,
        job_dir: Path,
        lyrics: Any,
        timeline: Any,
        duration_seconds: float,
    ) -> Any:
        """Move lyrics out of stretches in which nobody sings.

        Both ASR and forced alignment will happily time words inside an
        instrumental interlude when their guide window was wrong.  A clean
        vocal stem shows where the interludes are; lines caught in one are
        handed to the sung time next to it and, when possible, re-aligned
        there.  The findings are kept for the review screen.
        """
        notes_path = job_dir / self._NOTES_FILE
        notes_path.unlink(missing_ok=True)
        if not self._has_clean_stem(job_dir):
            return timeline
        vocals_path = job_dir / "audio_vocals.wav"
        if not vocals_path.is_file():
            vocals_path = job_dir / "audio.wav"
        try:
            rests = detect_rests(job_dir / self._CLEAN_STEM_FILE)
            repaired, moved, unresolved = move_lines_out_of_rests(
                timeline, rests, duration_ms=round(duration_seconds * 1000)
            )
        except Exception:
            logger.warning(
                "Rest detection failed; keeping the timeline as aligned",
                exc_info=True,
            )
            return timeline
        if moved and self.alignment_refiner is not None:
            try:
                repaired, _ = realign_lines(
                    self.aligner,
                    self.alignment_refiner,
                    lyrics,
                    repaired,
                    moved,
                    vocals_path,
                    duration_seconds=duration_seconds,
                    work_dir=job_dir,
                )
            except Exception:
                logger.warning(
                    "Could not re-align the lines moved out of rests",
                    exc_info=True,
                )
        repaired = trim_overlaps(repaired)
        notes_path.write_text(
            json.dumps(
                {
                    "rests": rests,
                    "moved_lines": moved,
                    "unresolved_lines": unresolved,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return repaired

    def _ensure_clean_stem(self, job_dir: Path) -> None:
        """Give jobs made before the separation model existed a clean stem."""
        video_path = job_dir / "input.mp4"
        if (
            self.vocal_stem_separator is None
            or self._has_clean_stem(job_dir)
            or not video_path.is_file()
        ):
            return
        stereo_path = job_dir / "audio_stereo.wav"
        try:
            self.extractor.extract_stereo(video_path, stereo_path)
            self._clean_vocal_stem(stereo_path, job_dir)
        except Exception:
            logger.warning("Could not prepare a clean vocal stem", exc_info=True)
        finally:
            stereo_path.unlink(missing_ok=True)

    def _realign(self, job_dir: Path) -> Any | None:
        """Recompute the timeline from stored ASR output and lyrics.

        Alignment takes well under a second, so regenerating a job also
        picks up aligner improvements without transcribing again.  Any
        failure keeps the timeline that already produced a result.
        """
        transcript_path = job_dir / "transcript.json"
        lyrics_path = job_dir / "lyrics_processed.json"
        if (
            self.aligner is None
            or not transcript_path.is_file()
            or not lyrics_path.is_file()
        ):
            return None
        self._ensure_clean_stem(job_dir)
        self._upgrade_transcript(job_dir)
        timeline_path = job_dir / "timeline.json"
        if timeline_path.is_file() and MANUALLY_EDITED in json.loads(
            timeline_path.read_text(encoding="utf-8")
        ).get("warnings", []):
            # Never overwrite corrections a person made by hand.
            return None
        try:
            timeline = self._build_timeline(
                job_dir,
                LyricDocument.from_dict(
                    json.loads(lyrics_path.read_text(encoding="utf-8"))
                ),
                TranscriptDocument.from_dict(
                    json.loads(transcript_path.read_text(encoding="utf-8"))
                ),
            )
        except Exception:
            logger.warning(
                "Realignment failed; keeping the stored timeline",
                exc_info=True,
            )
            return None
        (job_dir / "timeline.json").write_text(
            json.dumps(timeline.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return timeline

    def _render_outputs(
        self,
        job: dict,
        video_path: Path,
        ass_path: Path,
        output_path: Path,
        instrumental_path: Path,
    ) -> Path | None:
        """Render the video; return the off-vocal version when one was made.

        "both" renders the original soundtrack and then swaps in the
        instrumental without burning the subtitles again.  "on" and "off"
        are the older single-output modes.
        """
        mode = job.get("vocal_mode") or "on"
        off_path = output_path.with_name("final_karaoke_off.mp4")
        off_path.unlink(missing_ok=True)
        single_off = mode == "off" and instrumental_path.exists()
        self.video_renderer.render(
            video_path,
            ass_path,
            output_path,
            vocal_mode="off" if single_off else "on",
            instrumental_audio_path=instrumental_path if single_off else None,
        )
        if (
            mode != "both"
            or not instrumental_path.exists()
            or not hasattr(self.video_renderer, "replace_audio")
        ):
            return None
        try:
            self.video_renderer.replace_audio(
                output_path, instrumental_path, off_path
            )
        except Exception:
            logger.warning(
                "Could not produce the off-vocal version; keeping the "
                "on-vocal video only",
                exc_info=True,
            )
            off_path.unlink(missing_ok=True)
            return None
        return off_path if off_path.is_file() else None

    def _restyle(
        self,
        job_id: str,
        job: dict,
        *,
        realign: bool = True,
    ) -> None:
        """Rebuild subtitles and video from the stored timeline only."""
        video_path = Path(job["video_path"])
        job_dir = video_path.parent
        timeline_path = job_dir / "timeline.json"
        instrumental_path = job_dir / "audio_instrumental.wav"
        ass_path = job_dir / "lyrics.ass"
        output_path = job_dir / "final_karaoke.mp4"
        stage = "GENERATING_SUBTITLE"
        try:
            self.database.update_job_state(
                job_id, status="PROCESSING", stage=stage, progress=95
            )
            timeline = self._realign(job_dir) if realign else None
            if timeline is None:
                timeline = LyricTimeline.from_dict(
                    json.loads(timeline_path.read_text(encoding="utf-8"))
                )
            ass_path.write_text(
                self._generate_subtitles(job_dir, timeline),
                encoding="utf-8-sig",
            )
            if self.video_renderer is None:
                self.database.update_job_state(
                    job_id,
                    status="SUBTITLE_GENERATED",
                    stage="SUBTITLE_GENERATION_COMPLETE",
                    progress=100,
                    ass_path=ass_path,
                )
                return
            stage = "RENDERING_VIDEO"
            self.database.update_job_state(
                job_id,
                status="PROCESSING",
                stage=stage,
                progress=98,
                ass_path=ass_path,
            )
            output_off_path = self._render_outputs(
                job, video_path, ass_path, output_path, instrumental_path
            )
            self.database.update_job_state(
                job_id,
                status="COMPLETED",
                stage="VIDEO_RENDERING_COMPLETE",
                progress=100,
                ass_path=ass_path,
                output_path=output_path,
                output_off_path=output_off_path,
            )
        except Exception:
            output_path.unlink(missing_ok=True)
            logger.exception(
                "Job %s failed while restyling during stage %s", job_id, stage
            )
            self.database.update_job_state(
                job_id,
                status="FAILED",
                stage=stage,
                progress=95 if stage == "GENERATING_SUBTITLE" else 98,
                error_code=(
                    "SUBTITLE_GENERATION_FAILED"
                    if stage == "GENERATING_SUBTITLE"
                    else "VIDEO_RENDERING_FAILED"
                ),
                error_message=PUBLIC_ERROR_MESSAGES[stage],
            )
            raise

    def process(self, job_id: str) -> None:
        job = self.database.get_job(job_id)
        if job is None:
            raise KeyError(f"Job not found: {job_id}")

        if job.get("stage") in ("RESTYLE_QUEUED", "RENDER_QUEUED"):
            self._restyle(
                job_id, job, realign=job["stage"] == "RESTYLE_QUEUED"
            )
            return

        video_path = Path(job["video_path"])
        job_dir = video_path.parent
        audio_path = job_dir / "audio.wav"
        instrumental_path = job_dir / "audio_instrumental.wav"
        vocals_path = job_dir / "audio_vocals.wav"
        transcript_path = job_dir / "transcript.json"
        lyrics_processed_path = job_dir / "lyrics_processed.json"
        timeline_path = job_dir / "timeline.json"
        ass_path = job_dir / "lyrics.ass"
        output_path = job_dir / "final_karaoke.mp4"

        stage = "DOWNLOADING_VIDEO"
        try:
            if not video_path.is_file():
                self.database.update_job_state(
                    job_id,
                    status="PROCESSING",
                    stage=stage,
                    progress=5,
                )
                self._download_video(job_id, video_path)
            stage = "EXTRACTING_AUDIO"
            self.database.update_job_state(
                job_id,
                status="PROCESSING",
                stage=stage,
                progress=15,
            )
            self.extractor.extract(video_path, audio_path)
            vocal_mode = job.get("vocal_mode", "on")
            needs_instrumental = vocal_mode in ("off", "both")
            separate = self.vocal_stem_separator is not None or (
                self.vocal_remover is not None
                and (needs_instrumental or self.transcribe_vocal_stem)
            )
            transcription_audio_path = audio_path
            if needs_instrumental or separate:
                stage = "REMOVING_VOCALS"
                self.database.update_job_state(
                    job_id,
                    status="PROCESSING",
                    stage=stage,
                    progress=25,
                    audio_path=audio_path,
                )
            if separate:
                transcription_audio_path = self._separate(
                    video_path,
                    instrumental_path,
                    vocals_path,
                    required=vocal_mode == "off",
                    fallback=audio_path,
                )
            lyrics_path_value = job.get("lyrics_path")
            processed_lyrics = None
            transcript = None
            (job_dir / self._TRANSCRIPT_SOURCE_FILE).unlink(missing_ok=True)
            if (
                self.primary_aligner is not None
                and self.lyric_processor is not None
                and self.aligner is not None
                and lyrics_path_value
            ):
                # With a forced aligner the lyrics are all that is needed:
                # no recognition pass, which is the slowest and least
                # reliable stage on sung audio.
                stage = "PROCESSING_LYRICS"
                self.database.update_job_state(
                    job_id,
                    status="PROCESSING",
                    stage=stage,
                    progress=40,
                    audio_path=audio_path,
                )
                processed_lyrics = self.lyric_processor.process(
                    Path(lyrics_path_value).read_text(encoding="utf-8")
                )
                stage = "ALIGNING"
                self.database.update_job_state(
                    job_id,
                    status="PROCESSING",
                    stage=stage,
                    progress=55,
                    audio_path=audio_path,
                )
                transcript = self._forced_transcript(
                    job_dir, video_path, processed_lyrics
                )
            if transcript is None:
                stage = "TRANSCRIBING"
                self.database.update_job_state(
                    job_id,
                    status="PROCESSING",
                    stage=stage,
                    progress=40 if processed_lyrics is None else 60,
                    audio_path=audio_path,
                )
                transcript = self._transcribe(
                    job_id,
                    transcription_audio_path,
                    lyrics_path_value,
                )
            transcript_path.write_text(
                json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if self.lyric_processor is not None and lyrics_path_value:
                stage = "PROCESSING_LYRICS"
                self.database.update_job_state(
                    job_id,
                    status="PROCESSING",
                    stage=stage,
                    progress=75,
                    audio_path=audio_path,
                    transcript_path=transcript_path,
                )
                if processed_lyrics is None:
                    processed_lyrics = self.lyric_processor.process(
                        Path(lyrics_path_value).read_text(encoding="utf-8")
                    )
                lyrics_processed_path.write_text(
                    json.dumps(
                        processed_lyrics.to_dict(),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                if self.aligner is not None:
                    stage = "ALIGNING"
                    self.database.update_job_state(
                        job_id,
                        status="PROCESSING",
                        stage=stage,
                        progress=90,
                        audio_path=audio_path,
                        transcript_path=transcript_path,
                        lyrics_processed_path=lyrics_processed_path,
                    )
                    timeline = self._build_timeline(
                        job_dir, processed_lyrics, transcript
                    )
                    timeline_path.write_text(
                        json.dumps(
                            timeline.to_dict(),
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    if self.subtitle_generator is not None:
                        stage = "GENERATING_SUBTITLE"
                        self.database.update_job_state(
                            job_id,
                            status="PROCESSING",
                            stage=stage,
                            progress=95,
                            audio_path=audio_path,
                            transcript_path=transcript_path,
                            lyrics_processed_path=lyrics_processed_path,
                            timeline_path=timeline_path,
                        )
                        ass_content = self._generate_subtitles(
                            job_dir, timeline
                        )
                        ass_path.write_text(
                            ass_content,
                            encoding="utf-8-sig",
                        )
                        if (
                            self.video_renderer is not None
                            and self._review_requested(job_dir)
                        ):
                            self.database.update_job_state(
                                job_id,
                                status="AWAITING_REVIEW",
                                stage="REVIEW_PENDING",
                                progress=96,
                                audio_path=audio_path,
                                transcript_path=transcript_path,
                                lyrics_processed_path=lyrics_processed_path,
                                timeline_path=timeline_path,
                                ass_path=ass_path,
                            )
                            return
                        if self.video_renderer is not None:
                            stage = "RENDERING_VIDEO"
                            self.database.update_job_state(
                                job_id,
                                status="PROCESSING",
                                stage=stage,
                                progress=98,
                                audio_path=audio_path,
                                transcript_path=transcript_path,
                                lyrics_processed_path=lyrics_processed_path,
                                timeline_path=timeline_path,
                                ass_path=ass_path,
                            )
                            output_off_path = self._render_outputs(
                                job,
                                video_path,
                                ass_path,
                                output_path,
                                instrumental_path,
                            )
                            self.database.update_job_state(
                                job_id,
                                status="COMPLETED",
                                stage="VIDEO_RENDERING_COMPLETE",
                                progress=100,
                                audio_path=audio_path,
                                transcript_path=transcript_path,
                                lyrics_processed_path=lyrics_processed_path,
                                timeline_path=timeline_path,
                                ass_path=ass_path,
                                output_path=output_path,
                                output_off_path=output_off_path,
                            )
                        else:
                            self.database.update_job_state(
                                job_id,
                                status="SUBTITLE_GENERATED",
                                stage="SUBTITLE_GENERATION_COMPLETE",
                                progress=100,
                                audio_path=audio_path,
                                transcript_path=transcript_path,
                                lyrics_processed_path=lyrics_processed_path,
                                timeline_path=timeline_path,
                                ass_path=ass_path,
                            )
                    else:
                        self.database.update_job_state(
                            job_id,
                            status="ALIGNED",
                            stage="ALIGNMENT_COMPLETE",
                            progress=100,
                            audio_path=audio_path,
                            transcript_path=transcript_path,
                            lyrics_processed_path=lyrics_processed_path,
                            timeline_path=timeline_path,
                        )
                else:
                    self.database.update_job_state(
                        job_id,
                        status="LYRICS_PROCESSED",
                        stage="LYRIC_PROCESSING_COMPLETE",
                        progress=100,
                        audio_path=audio_path,
                        transcript_path=transcript_path,
                        lyrics_processed_path=lyrics_processed_path,
                    )
            else:
                self.database.update_job_state(
                    job_id,
                    status="TRANSCRIBED",
                    stage="TRANSCRIPTION_COMPLETE",
                    progress=100,
                    audio_path=audio_path,
                    transcript_path=transcript_path,
                )
        except Exception:
            # Never leave a partially rendered video behind a failed job.
            output_path.unlink(missing_ok=True)
            logger.exception(
                "Job %s failed during stage %s",
                job_id,
                stage,
            )
            error_code = {
                "DOWNLOADING_VIDEO": "VIDEO_DOWNLOAD_FAILED",
                "REMOVING_VOCALS": "VOCAL_REMOVAL_FAILED",
                "EXTRACTING_AUDIO": "AUDIO_EXTRACTION_FAILED",
                "TRANSCRIBING": "TRANSCRIPTION_FAILED",
                "PROCESSING_LYRICS": "LYRIC_PROCESSING_FAILED",
                "ALIGNING": "ALIGNMENT_FAILED",
                "GENERATING_SUBTITLE": "SUBTITLE_GENERATION_FAILED",
                "RENDERING_VIDEO": "VIDEO_RENDERING_FAILED",
            }[stage]
            progress = {
                "DOWNLOADING_VIDEO": 5,
                "REMOVING_VOCALS": 25,
                "EXTRACTING_AUDIO": 15,
                "TRANSCRIBING": 40,
                "PROCESSING_LYRICS": 75,
                "ALIGNING": 90,
                "GENERATING_SUBTITLE": 95,
                "RENDERING_VIDEO": 98,
            }[stage]
            self.database.update_job_state(
                job_id,
                status="FAILED",
                stage=stage,
                progress=progress,
                audio_path=audio_path if audio_path.exists() else None,
                transcript_path=(
                    transcript_path if transcript_path.exists() else None
                ),
                lyrics_processed_path=(
                    lyrics_processed_path
                    if lyrics_processed_path.exists()
                    else None
                ),
                timeline_path=(
                    timeline_path if timeline_path.exists() else None
                ),
                ass_path=ass_path if ass_path.exists() else None,
                error_code=error_code,
                error_message=PUBLIC_ERROR_MESSAGES[stage],
            )
            raise
