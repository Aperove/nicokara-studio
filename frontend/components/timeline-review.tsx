"use client";

import {
  AlertTriangle,
  BookOpenText,
  Clapperboard,
  LoaderCircle,
  Maximize2,
  Minimize2,
  Palette,
  Play,
  RotateCcw,
  Save,
  Sparkles,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { createPortal } from "react-dom";

import { ErrorFeedbackPanel } from "@/components/error-feedback";
import { TimelineTrack } from "@/components/timeline-track";
import {
  networkErrorFeedback,
  type ErrorFeedback,
} from "@/lib/error-feedback";
import {
  activeLineIndex,
  formatSeconds,
  hasCheckableReading,
  isKanaReading,
  lineConcerns,
  parseTime,
  retimeLine,
  tokenProgress,
  typicalPace,
} from "@/lib/timeline";
import { REVIEW_COPY } from "@/lib/ui-copy";
import { StylePanel, outlineShadow } from "@/components/style-panel";
import {
  ApiRequestError,
  audioTrackUrl,
  getJobStyle,
  getReview,
  refineTimelineLines,
  retryForcedAlignment,
  renderJob,
  saveReadings,
  saveTimeline,
  sourceVideoUrl,
} from "@/services/api";
import { DEFAULT_SUBTITLE_STYLE, type SubtitleStyle } from "@/types/style";
import type { Review, TimelineLine } from "@/types/timeline";

type Draft = { start_ms: number; end_ms: number };
type Busy = "save" | "refine" | "render" | "forced" | null;

const PREROLL_MS = 500;

function feedbackOf(reason: unknown): ErrorFeedback {
  return reason instanceof ApiRequestError
    ? reason.feedback
    : networkErrorFeedback("job");
}

function TimeInput({
  valueMs,
  label,
  invalid,
  onCommit,
}: {
  valueMs: number;
  label: string;
  invalid: boolean;
  onCommit: (ms: number) => void;
}) {
  const [text, setText] = useState<string | null>(null);
  const parsed = text === null ? valueMs : parseTime(text);
  const bad = invalid || parsed === null;

  function commit() {
    if (text !== null && parsed !== null) onCommit(parsed);
    setText(null);
  }

  return (
    <input
      type="text"
      inputMode="decimal"
      value={text ?? formatSeconds(valueMs)}
      aria-label={label}
      aria-invalid={bad}
      title={bad && parsed === null ? REVIEW_COPY.invalidTime : undefined}
      onFocus={(event) => event.currentTarget.select()}
      onChange={(event) => setText(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
        if (event.key === "Escape") setText(null);
      }}
      className={`focus-ring w-20 rounded border bg-card px-1.5 py-1 text-right font-mono ${
        bad ? "border-destructive" : ""
      }`}
    />
  );
}

const KANJI = /[\u3400-\u9fff\uf900-\ufaff々〆ヶ]/;

function KaraokePreview({
  line,
  timeMs,
  style,
}: {
  line: TimelineLine | null;
  timeMs: number;
  style: SubtitleStyle;
}) {
  const visible =
    line &&
    timeMs >= line.start_ms - style.lead_in_ms &&
    timeMs <= line.end_ms + 400;
  // the video is 1080 lines tall; the preview strip shows text at ~30%
  const size = Math.max(16, Math.round(style.font_size * 0.3));
  const outline = outlineShadow(style.outline_color, Math.max(1, size / 14));
  const fontFamily = `"${style.font_name}", sans-serif`;

  // A long line is scaled down to the strip, the way the renderer shrinks
  // the font so a line fits the frame.
  const stripRef = useRef<HTMLDivElement | null>(null);
  const textRef = useRef<HTMLSpanElement | null>(null);
  useLayoutEffect(() => {
    const strip = stripRef.current;
    const text = textRef.current;
    if (!strip || !text) return;
    const fit = () => {
      text.style.transform = "none";
      const room = strip.clientWidth - 32;
      const scale = Math.min(1, room / Math.max(1, text.scrollWidth));
      text.style.transform = `scale(${scale})`;
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(strip);
    return () => observer.disconnect();
  }, [line, visible, size, fontFamily, style.show_ruby]);

  return (
    <div
      ref={stripRef}
      aria-hidden
      className="flex min-h-24 items-center justify-center overflow-hidden rounded-xl px-4 py-3 text-center font-bold leading-tight"
      style={{
        background:
          "linear-gradient(135deg, #334155 0%, #64748b 50%, #cbd5e1 100%)",
      }}
    >
      {visible && line ? (
        <span
          ref={textRef}
          className="inline-block"
          style={{ fontFamily, fontSize: size, whiteSpace: "nowrap" }}
        >
          {line.tokens.map((token, index) => {
            const width = `${tokenProgress(token, timeMs) * 100}%`;
            const ruby =
              style.show_ruby && token.reading && KANJI.test(token.surface)
                ? token.reading
                : null;
            return (
              <span
                key={index}
                className="relative inline-block whitespace-pre align-bottom"
                style={{ paddingTop: style.show_ruby ? size * 0.5 : 0 }}
              >
                {ruby && (
                  <span
                    className="absolute inset-x-0 top-0 text-center leading-none"
                    style={{
                      color: style.unsung_color,
                      fontSize: size * 0.4,
                      textShadow: outline,
                    }}
                  >
                    {ruby}
                  </span>
                )}
                <span style={{ color: style.unsung_color, textShadow: outline }}>
                  {token.surface}
                </span>
                <span
                  className="absolute bottom-0 left-0 overflow-hidden"
                  style={{
                    width,
                    color: style.sung_color,
                    textShadow: style.glow
                      ? `0 0 ${size / 3}px ${style.sung_color}`
                      : "none",
                  }}
                >
                  {token.surface}
                </span>
              </span>
            );
          })}
        </span>
      ) : (
        <span className="text-base font-normal text-slate-200">
          {REVIEW_COPY.previewIdle}
        </span>
      )}
    </div>
  );
}

// Wide enough for the player and the lyric list to sit side by side.
const WORKBENCH_QUERY = "(min-width: 1000px) and (min-height: 480px)";

function subscribeToWorkbenchQuery(onChange: () => void) {
  const query = window.matchMedia(WORKBENCH_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

export function TimelineReview({
  jobId,
  onRenderQueued,
}: {
  jobId: string;
  onRenderQueued: () => void;
}) {
  const [review, setReview] = useState<Review | null>(null);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [track, setTrack] = useState<"video" | "vocals">("video");
  const [timeMs, setTimeMs] = useState(0);
  const [concernsOnly, setConcernsOnly] = useState(false);
  const [openReadings, setOpenReadings] = useState<number | null>(null);
  // corrected readings not saved yet, keyed "line:token"
  const [readingDrafts, setReadingDrafts] = useState<Record<string, string>>({});
  // lines whose reading changed since they were last re-aligned
  const [rereadLines, setRereadLines] = useState<number[]>([]);
  const [busy, setBusy] = useState<Busy>(null);
  const [style, setStyle] = useState<SubtitleStyle>(DEFAULT_SUBTITLE_STYLE);
  const [styleDirty, setStyleDirty] = useState(false);
  const [styleOpen, setStyleOpen] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const canExpand = useSyncExternalStore(
    subscribeToWorkbenchQuery,
    () => window.matchMedia(WORKBENCH_QUERY).matches,
    () => false,
  );
  const wide = expanded && canExpand && review !== null;
  const listRef = useRef<HTMLOListElement | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<ErrorFeedback | null>(null);
  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const stopAtRef = useRef<number | null>(null);
  const resumeAtRef = useRef(0);

  useEffect(() => {
    let active = true;
    getReview(jobId)
      .then((value) => {
        if (active) setReview(value);
      })
      .catch((reason) => {
        if (active) setError(feedbackOf(reason));
      });
    getJobStyle(jobId)
      .then((value) => {
        if (active) setStyle(value);
      })
      .catch(() => {
        // the preview falls back to the default style
      });
    return () => {
      active = false;
    };
  }, [jobId]);

  // Follow the playhead every frame: karaoke fills need finer steps than
  // the ~4 Hz `timeupdate` event provides.
  useEffect(() => {
    let frame = 0;
    const tick = () => {
      const media = mediaRef.current;
      if (media) {
        const now = media.currentTime * 1000;
        if (stopAtRef.current !== null && now >= stopAtRef.current) {
          stopAtRef.current = null;
          media.pause();
        }
        setTimeMs((previous) =>
          Math.abs(previous - now) >= 15 ? now : previous,
        );
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  const lines = useMemo(() => {
    if (!review) return [];
    const moved = review.timeline.lines.map((line, index) => {
      const draft = drafts[index];
      return draft && draft.end_ms > draft.start_ms
        ? retimeLine(line, draft.start_ms, draft.end_ms)
        : line;
    });
    // A late ending gives way to the next line, exactly as it will be saved.
    return moved.map((line, index) => {
      const next = moved[index + 1];
      return next && line.end_ms > next.start_ms && next.start_ms > line.start_ms
        ? retimeLine(line, line.start_ms, next.start_ms)
        : line;
    });
  }, [review, drafts]);

  const dirtyIndexes = useMemo(
    () => Object.keys(drafts).map(Number).sort((a, b) => a - b),
    [drafts],
  );
  const invalidIndexes = dirtyIndexes.filter(
    (index) => drafts[index].end_ms <= drafts[index].start_ms,
  );
  const readingKeys = Object.keys(readingDrafts);
  const invalidReadings = readingKeys.filter(
    (key) => !isKanaReading(readingDrafts[key]),
  );
  const unsavedCount = dirtyIndexes.length + readingKeys.length;
  const blocked = invalidIndexes.length > 0 || invalidReadings.length > 0;
  const pace = useMemo(() => typicalPace(lines), [lines]);
  const movedLines = review?.moved_lines ?? [];
  const stuckLines = review?.unresolved_lines ?? [];
  const lrcLines = review?.lrc_adjusted_lines ?? [];
  const concernCount = useMemo(
    () =>
      lines.filter(
        (line, index) =>
          lineConcerns(line, pace).length > 0 ||
          (review?.moved_lines ?? []).includes(index) ||
          (review?.unresolved_lines ?? []).includes(index) ||
          (review?.lrc_adjusted_lines ?? []).includes(index),
      ).length,
    [lines, pace, review],
  );
  const current = lines.length ? activeLineIndex(lines, timeMs) : -1;

  // The workbench covers the page, which must not scroll behind it.
  useEffect(() => {
    if (!wide) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [wide]);

  // Keep the line being sung in view while the list scrolls on its own.
  useEffect(() => {
    if (!wide || current < 0) return;
    listRef.current
      ?.querySelector(`[data-line="${current}"]`)
      ?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [wide, current]);

  const setDraft = useCallback(
    (index: number, patch: Partial<Draft>) => {
      if (!review) return;
      setNotice(null);
      setDrafts((previous) => {
        const base = previous[index] ?? {
          start_ms: review.timeline.lines[index].start_ms,
          end_ms: review.timeline.lines[index].end_ms,
        };
        const next = { ...base, ...patch };
        const original = review.timeline.lines[index];
        const copy = { ...previous };
        if (
          next.start_ms === original.start_ms &&
          next.end_ms === original.end_ms
        ) {
          delete copy[index];
        } else {
          copy[index] = next;
        }
        return copy;
      });
    },
    [review],
  );

  function playLine(index: number) {
    const media = mediaRef.current;
    if (!media) return;
    const line = lines[index];
    media.currentTime = Math.max(0, line.start_ms - PREROLL_MS) / 1000;
    stopAtRef.current = line.end_ms + 300;
    void media.play();
  }

  function switchTrack(next: "video" | "vocals") {
    if (next === track) return;
    resumeAtRef.current = mediaRef.current?.currentTime ?? 0;
    stopAtRef.current = null;
    setTrack(next);
  }

  async function persist(): Promise<number[]> {
    let reread = rereadLines;
    if (readingKeys.length) {
      const saved = await saveReadings(
        jobId,
        readingKeys.map((key) => {
          const [line, token] = key.split(":").map(Number);
          return { line, token, reading: readingDrafts[key].trim() };
        }),
      );
      setReview((previous) =>
        previous ? { ...previous, timeline: saved.timeline } : previous,
      );
      setReadingDrafts({});
      reread = [...new Set([...reread, ...saved.changed_lines])];
      setRereadLines(reread);
    }
    if (!dirtyIndexes.length) return reread;
    const result = await saveTimeline(
      jobId,
      dirtyIndexes.map((index) => ({ index, ...drafts[index] })),
    );
    setReview((previous) =>
      previous ? { ...previous, timeline: result.timeline } : previous,
    );
    setDrafts({});
    return reread;
  }

  async function retryForced() {
    if (!review || busy !== null) return;
    const edited =
      review.timeline.warnings.includes("manually_edited") ||
      dirtyIndexes.length > 0;
    if (edited && !window.confirm(REVIEW_COPY.fallbackConfirm)) return;
    setBusy("forced");
    setError(null);
    setNotice(null);
    try {
      await retryForcedAlignment(jobId);
      // rests and moved lines change along with the timeline
      setReview(await getReview(jobId));
      setDrafts({});
      setRereadLines([]);
      setNotice(REVIEW_COPY.fallbackDone);
    } catch (reason) {
      setError(feedbackOf(reason));
    }
    setBusy(null);
  }

  async function run(kind: Exclude<Busy, "forced" | null>) {
    if (blocked) return;
    setBusy(kind);
    setError(null);
    setNotice(null);
    try {
      const moved = dirtyIndexes;
      const reread = await persist();
      const targets = [...new Set([...moved, ...reread])].sort((a, b) => a - b);
      if (kind === "refine" && targets.length) {
        const result = await refineTimelineLines(jobId, targets);
        setReview((previous) =>
          previous ? { ...previous, timeline: result.timeline } : previous,
        );
        setRereadLines([]);
        setNotice(
          REVIEW_COPY.refinedResult(result.refined_lines.length, targets.length),
        );
      }
      if (kind === "render") {
        await renderJob(jobId, styleDirty ? style : undefined);
        onRenderQueued();
        return;
      }
    } catch (reason) {
      setError(feedbackOf(reason));
    }
    setBusy(null);
  }

  if (!review) {
    return (
      <section className="rounded-3xl border bg-card p-6 sm:p-9">
        {error ? (
          <ErrorFeedbackPanel feedback={error} />
        ) : (
          <p className="flex items-center gap-3 text-sm text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" />
            {REVIEW_COPY.loading}
          </p>
        )}
      </section>
    );
  }

  const editReading = (lineIndex: number, tokenIndex: number) => {
    setOpenReadings(lineIndex);
    // the editor of that line is rendered by the state change above
    requestAnimationFrame(() => {
      const input = document.querySelector<HTMLInputElement>(
        `[data-reading="${lineIndex}:${tokenIndex}"]`,
      );
      input?.focus();
      input?.select();
    });
  };

  // The player is rebuilt in the other layout; it picks up where it was.
  const toggleWorkbench = (next: boolean) => {
    resumeAtRef.current = mediaRef.current?.currentTime ?? 0;
    setExpanded(next);
  };

  const mediaProps = {
    controls: true,
    preload: "metadata" as const,
    onLoadedMetadata: (event: React.SyntheticEvent<HTMLMediaElement>) => {
      event.currentTarget.currentTime = resumeAtRef.current;
    },
  };

  const trackSwitch = (
    <div className="flex gap-2 text-sm">
      {(
        [
          ["video", REVIEW_COPY.sourceVideo],
          ["vocals", REVIEW_COPY.vocalsOnly],
        ] as const
      ).map(([value, label]) =>
        value === "vocals" && !review.has_vocals ? null : (
          <button
            key={value}
            type="button"
            aria-pressed={track === value}
            onClick={() => switchTrack(value)}
            className={`focus-ring rounded-lg border px-3 py-1.5 font-medium transition ${
              track === value
                ? "border-primary bg-primary/10 text-primary"
                : "bg-card text-muted-foreground hover:bg-muted"
            }`}
          >
            {label}
          </button>
        ),
      )}
      <span className="ml-auto self-center font-mono text-xs text-muted-foreground">
        {formatSeconds(timeMs)}
      </span>
    </div>
  );

  const media =
    track === "video" ? (
              <video
                key="video"
                ref={(element) => {
                  mediaRef.current = element;
                }}
                className={
                  wide
                    ? "min-h-0 w-full flex-1 rounded-xl bg-black object-contain"
                    : "max-h-56 w-full rounded-xl bg-black"
                }
                playsInline
                src={sourceVideoUrl(jobId)}
                {...mediaProps}
              />
            ) : (
              <audio
                key="vocals"
                ref={(element) => {
                  mediaRef.current = element;
                }}
                className="w-full"
                src={audioTrackUrl(jobId, "vocals")}
                {...mediaProps}
              />
            );

  const preview = (
    <KaraokePreview
      line={current >= 0 ? lines[current] : null}
      timeMs={timeMs}
      style={style}
    />
  );

  const styleEditor = (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">{REVIEW_COPY.styleHint}</p>
      <StylePanel
        value={style}
        onChange={(next) => {
          setStyle(next);
          setStyleDirty(true);
        }}
        disabled={busy !== null}
        showPreview={false}
      />
    </div>
  );

  const waveform = (
    <TimelineTrack
      lines={lines}
      rests={review.rests}
      editedIndexes={dirtyIndexes}
      currentIndex={current}
      timeMs={timeMs}
      durationMs={
        review.duration_ms ??
        (lines.length ? lines[lines.length - 1].end_ms + 5_000 : 0)
      }
      audioUrl={audioTrackUrl(jobId, review.has_vocals ? "vocals" : "mix")}
      onSeek={(ms) => {
        stopAtRef.current = null;
        if (mediaRef.current) mediaRef.current.currentTime = ms / 1000;
      }}
      onChange={(index, start_ms, end_ms) =>
        setDraft(index, { start_ms, end_ms })
      }
    />
  );

  const summary = (
    <div className="mt-2 flex flex-wrap items-center justify-between gap-3 text-sm">
      <span
        className={`inline-flex items-center gap-1.5 ${
          concernCount ? "text-amber-600" : "text-muted-foreground"
        }`}
      >
        {concernCount > 0 && <AlertTriangle className="size-4" />}
        {REVIEW_COPY.concernSummary(concernCount)}
      </span>
      <label className="flex items-center gap-2 text-muted-foreground">
        <input
          type="checkbox"
          checked={concernsOnly}
          onChange={(event) => setConcernsOnly(event.target.checked)}
        />
        {REVIEW_COPY.showConcernsOnly}
      </label>
    </div>
  );

  const banners = (
    <>
      {review.can_retry_forced_alignment && (
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
          <p className="min-w-0 flex-1">
            <span className="font-semibold">{REVIEW_COPY.fallbackTitle}</span>
            <br />
            {review.forced_alignment_failure
              ? REVIEW_COPY.fallbackReason(review.forced_alignment_failure)
              : REVIEW_COPY.fallbackUnknown}
          </p>
          <button
            type="button"
            disabled={busy !== null}
            onClick={retryForced}
            className="focus-ring rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-semibold transition hover:bg-amber-100 disabled:opacity-50"
          >
            {busy === "forced"
              ? REVIEW_COPY.fallbackRetrying
              : REVIEW_COPY.fallbackRetry}
          </button>
        </div>
      )}

      {review.lyrics_provider === "local" && review.can_edit_readings && (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
          {REVIEW_COPY.readingsLocalWarning}
        </p>
      )}
    </>
  );

  const lineList = (
    <ol
      ref={listRef}
      className={
        wide
          ? "min-h-0 flex-1 space-y-1.5 overflow-y-auto overscroll-contain pr-1"
          : "mt-3 space-y-1.5"
      }
    >
      {lines.map((line, index) => {
        const concerns = lineConcerns(line, pace);
        const draft = drafts[index];
        const wasMoved = movedLines.includes(index);
        const isStuck = stuckLines.includes(index);
        const byLrc = lrcLines.includes(index);
        if (
          concernsOnly &&
          !concerns.length &&
          !draft &&
          !wasMoved &&
          !isStuck &&
          !byLrc
        )
          return null;
        const invalid = invalidIndexes.includes(index);
        const startMs = draft?.start_ms ?? line.start_ms;
        const endMs = draft?.end_ms ?? line.end_ms;
        return (
          <li
            key={index}
            data-line={index}
            className={`rounded-xl border px-3 py-2 transition ${
              index === current
                ? "border-primary bg-primary/5"
                : "bg-card"
            }`}
          >
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <button
                type="button"
                onClick={() => playLine(index)}
                title={REVIEW_COPY.playLine}
                aria-label={`${REVIEW_COPY.playLine} ${index + 1}`}
                className="focus-ring flex size-8 shrink-0 items-center justify-center rounded-full border bg-card transition hover:bg-muted"
              >
                <Play className="size-3.5" />
              </button>
              <span className="w-6 shrink-0 text-right font-mono text-xs text-muted-foreground">
                {index + 1}
              </span>
              <span className="min-w-40 flex-1 text-sm leading-loose">
                {review.can_edit_readings
                  ? line.tokens.map((token, tokenIndex) => {
                      if (!KANJI.test(token.surface) || !token.reading) {
                        return <span key={tokenIndex}>{token.surface}</span>;
                      }
                      // The reading is shown where it will be rendered, so
                      // a wrong one is seen without opening anything.
                      const key = `${index}:${tokenIndex}`;
                      const changed = key in readingDrafts;
                      return (
                        <ruby
                          key={tokenIndex}
                          role="button"
                          tabIndex={0}
                          title={REVIEW_COPY.readingClickHint}
                          onClick={() => editReading(index, tokenIndex)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              editReading(index, tokenIndex);
                            }
                          }}
                          className={`focus-ring cursor-pointer rounded-sm transition hover:bg-primary/10 ${
                            changed ? "text-primary" : ""
                          }`}
                        >
                          {token.surface}
                          <rt className="select-none text-[0.6em] text-muted-foreground">
                            {changed ? readingDrafts[key] : token.reading}
                          </rt>
                        </ruby>
                      );
                    })
                  : line.surface}
              </span>
              {concerns.includes("short") && (
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">
                  {REVIEW_COPY.concernShort}
                </span>
              )}
              {concerns.includes("low_confidence") && (
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">
                  {REVIEW_COPY.concernLowConfidence}
                </span>
              )}
              {concerns.includes("odd_pace") && (
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">
                  {REVIEW_COPY.concernOddPace}
                </span>
              )}
              {isStuck && (
                <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-800">
                  {REVIEW_COPY.stuckInRest}
                </span>
              )}
              {byLrc && (
                <span className="rounded bg-sky-100 px-1.5 py-0.5 text-xs text-sky-800">
                  {REVIEW_COPY.lrcAdjusted}
                </span>
              )}
              {wasMoved && (
                <span className="rounded bg-sky-100 px-1.5 py-0.5 text-xs text-sky-800">
                  {REVIEW_COPY.movedOutOfRest}
                </span>
              )}
              {draft && (
                <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary">
                  {REVIEW_COPY.edited}
                </span>
              )}
              {review.can_edit_readings && (
                <button
                  type="button"
                  aria-expanded={openReadings === index}
                  title={REVIEW_COPY.readingsTitle}
                  aria-label={`${REVIEW_COPY.readings} ${index + 1}`}
                  onClick={() =>
                    setOpenReadings((open) => (open === index ? null : index))
                  }
                  className={`focus-ring inline-flex items-center gap-1 rounded border px-1.5 py-1 text-xs font-medium transition ${
                    openReadings === index ||
                    readingKeys.some((key) => key.startsWith(`${index}:`))
                      ? "border-primary bg-primary/10 text-primary"
                      : "bg-card text-muted-foreground hover:bg-muted"
                  }`}
                >
                  <BookOpenText className="size-3.5" />
                  {REVIEW_COPY.readings}
                </button>
              )}
              <div className="flex items-center gap-1.5 text-xs">
                {(
                  [
                    ["start_ms", REVIEW_COPY.lineStart, startMs, REVIEW_COPY.setStart],
                    ["end_ms", REVIEW_COPY.lineEnd, endMs, REVIEW_COPY.setEnd],
                  ] as const
                ).map(([field, label, value, hint]) => (
                  <span key={field} className="flex items-center gap-1">
                    <button
                      type="button"
                      title={hint}
                      aria-label={`${hint} ${index + 1}`}
                      onClick={() =>
                        setDraft(index, {
                          [field]: Math.round(
                            (mediaRef.current?.currentTime ?? 0) * 1000,
                          ),
                        })
                      }
                      className="focus-ring rounded border bg-card px-1.5 py-1 font-medium transition hover:bg-muted"
                    >
                      {label}
                    </button>
                    <TimeInput
                      valueMs={value}
                      label={`${label} ${index + 1}`}
                      invalid={invalid}
                      onCommit={(ms) => setDraft(index, { [field]: ms })}
                    />
                  </span>
                ))}
                {draft && (
                  <button
                    type="button"
                    title={REVIEW_COPY.resetLine}
                    aria-label={`${REVIEW_COPY.resetLine} ${index + 1}`}
                    onClick={() =>
                      setDrafts((previous) => {
                        const copy = { ...previous };
                        delete copy[index];
                        return copy;
                      })
                    }
                    className="focus-ring rounded p-1 text-muted-foreground transition hover:bg-muted"
                  >
                    <RotateCcw className="size-3.5" />
                  </button>
                )}
              </div>
            </div>
            {invalid && (
              <p className="mt-1 text-xs text-destructive">
                {REVIEW_COPY.invalidRange}
              </p>
            )}
            {openReadings === index && (
              <div className="mt-2 border-t pt-2">
                <div className="flex flex-wrap gap-2">
                  {line.tokens.map((token, tokenIndex) => {
                    if (!hasCheckableReading(token.surface, token.reading)) {
                      return null;
                    }
                    const key = `${index}:${tokenIndex}`;
                    const value = readingDrafts[key] ?? token.reading;
                    const bad = key in readingDrafts && !isKanaReading(value);
                    return (
                      <label
                        key={key}
                        className="flex items-center gap-1.5 rounded-lg border bg-card px-2 py-1 text-sm"
                      >
                        <span className="font-medium">{token.surface}</span>
                        <input
                          type="text"
                          value={value}
                          maxLength={64}
                          aria-invalid={bad}
                          aria-label={`${token.surface} ${REVIEW_COPY.readings}`}
                          data-reading={key}
                          title={bad ? REVIEW_COPY.readingInvalid : undefined}
                          onChange={(event) => {
                            const next = event.target.value;
                            setNotice(null);
                            setReadingDrafts((previous) => {
                              const copy = { ...previous };
                              if (next === token.reading) delete copy[key];
                              else copy[key] = next;
                              return copy;
                            });
                          }}
                          className={`focus-ring w-28 rounded border bg-card px-1.5 py-0.5 text-sm ${
                            bad ? "border-destructive" : ""
                          }`}
                        />
                      </label>
                    );
                  })}
                  {!line.tokens.some((token) =>
                    hasCheckableReading(token.surface, token.reading),
                  ) && (
                    <span className="text-xs text-muted-foreground">
                      {REVIEW_COPY.readingsNone}
                    </span>
                  )}
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  {REVIEW_COPY.readingsHint}
                </p>
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );

  const actions = (
    <div className={wide ? "space-y-2 border-t pt-3" : "mt-5 space-y-3"}>
      {error && <ErrorFeedbackPanel feedback={error} />}
      {notice && (
        <p className="rounded-lg bg-primary/10 px-3 py-2 text-sm text-primary">
          {notice}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={busy !== null || blocked || !unsavedCount}
          onClick={() => run("save")}
          className="focus-ring inline-flex items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm font-semibold transition hover:bg-muted disabled:opacity-50"
        >
          <Save className="size-4" />
          {busy === "save" ? REVIEW_COPY.saving : REVIEW_COPY.save}
        </button>
        {review.can_refine && (
          <button
            type="button"
            disabled={busy !== null || blocked || (!unsavedCount && !rereadLines.length)}
            onClick={() => run("refine")}
            title={REVIEW_COPY.refineHint}
            className="focus-ring inline-flex items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm font-semibold transition hover:bg-muted disabled:opacity-50"
          >
            {busy === "refine" ? (
              <LoaderCircle className="size-4 animate-spin" />
            ) : (
              <Sparkles className="size-4" />
            )}
            {busy === "refine" ? REVIEW_COPY.refining : REVIEW_COPY.refine}
          </button>
        )}
        <button
          type="button"
          disabled={busy !== null || blocked}
          onClick={() => run("render")}
          className="focus-ring inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground transition hover:brightness-95 disabled:cursor-wait disabled:opacity-60"
        >
          <Clapperboard className="size-4" />
          {busy === "render" ? REVIEW_COPY.rendering : REVIEW_COPY.render}
        </button>
        {unsavedCount > 0 && (
          <span className="text-xs text-muted-foreground">
            {REVIEW_COPY.unsavedCount(unsavedCount)}
          </span>
        )}
      </div>
      {review.can_refine && (
        <p className="text-xs text-muted-foreground">{REVIEW_COPY.refineHint}</p>
      )}
    </div>
  );

  const heading = (
    <h2
      id="review-panel-heading"
      className="flex items-center gap-2 font-display text-xl font-bold"
    >
      <Clapperboard className="size-5 text-primary" />
      {REVIEW_COPY.heading}
    </h2>
  );

  if (wide) {
    // A workbench that fills the window: what is watched stays on the left,
    // what is edited scrolls on the right, and nothing else moves.  It is
    // mounted on the body so no ancestor can confine a fixed element.
    return createPortal(
      <section
        className="fixed inset-0 z-40 flex flex-col bg-background"
        aria-labelledby="review-panel-heading"
      >
        <div className="flex items-center gap-4 border-b bg-card px-5 py-2.5">
          {heading}
          <p className="hidden min-w-0 flex-1 truncate text-xs text-muted-foreground 2xl:block">
            {REVIEW_COPY.description}
          </p>
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              aria-expanded={styleOpen}
              onClick={() => setStyleOpen((open) => !open)}
              className={`focus-ring inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-semibold transition ${
                styleOpen
                  ? "border-primary bg-primary/10 text-primary"
                  : "bg-card hover:bg-muted"
              }`}
            >
              <Palette className="size-4" />
              {REVIEW_COPY.styleTitle}
            </button>
            <button
              type="button"
              onClick={() => toggleWorkbench(false)}
              title={REVIEW_COPY.workbenchExitHint}
              className="focus-ring inline-flex items-center gap-1.5 rounded-lg border bg-card px-3 py-1.5 text-sm font-semibold transition hover:bg-muted"
            >
              <Minimize2 className="size-4" />
              {REVIEW_COPY.workbenchExit}
            </button>
          </div>
        </div>

        <div className="relative grid min-h-0 flex-1 grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] gap-5 px-5 py-4">
          <div className="flex min-h-0 flex-col gap-3">
            {trackSwitch}
            {media}
            {preview}
            {waveform}
          </div>

          <div className="flex min-h-0 flex-col gap-3">
            {summary}
            {banners}
            {lineList}
            {actions}
          </div>

          {styleOpen && (
            <aside
              aria-label={REVIEW_COPY.styleTitle}
              className="absolute inset-y-0 right-0 z-10 flex w-[30rem] max-w-full flex-col border-l bg-card shadow-xl"
            >
              <div className="flex items-center justify-between border-b px-4 py-2.5">
                <p className="text-sm font-semibold">{REVIEW_COPY.styleTitle}</p>
                <button
                  type="button"
                  aria-label={REVIEW_COPY.styleClose}
                  onClick={() => setStyleOpen(false)}
                  className="focus-ring rounded p-1 text-muted-foreground transition hover:bg-muted"
                >
                  <X className="size-4" />
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">
                {styleEditor}
              </div>
            </aside>
          )}
        </div>
      </section>,
      document.body,
    );
  }

  return (
    <section
      className="rounded-3xl border bg-card p-6 sm:p-9"
      aria-labelledby="review-panel-heading"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        {heading}
        {canExpand && (
          <button
            type="button"
            onClick={() => toggleWorkbench(true)}
            className="focus-ring inline-flex items-center gap-1.5 rounded-lg border bg-card px-3 py-1.5 text-sm font-semibold transition hover:bg-muted"
          >
            <Maximize2 className="size-4" />
            {REVIEW_COPY.workbenchEnter}
          </button>
        )}
      </div>
      <p className="mt-2 text-sm text-muted-foreground">
        {REVIEW_COPY.description}
      </p>

      <div className="sticky top-0 z-10 -mx-2 mt-5 space-y-3 bg-card px-2 pb-3 pt-1">
        {trackSwitch}
        {media}
        {preview}
        <div className="rounded-xl border bg-card/60 px-3 py-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold">{REVIEW_COPY.styleTitle}</p>
            <button
              type="button"
              aria-expanded={styleOpen}
              onClick={() => setStyleOpen((open) => !open)}
              className="focus-ring rounded-lg border bg-card px-3 py-1.5 text-xs font-semibold transition hover:bg-muted"
            >
              {styleOpen ? REVIEW_COPY.styleClose : REVIEW_COPY.styleOpen}
            </button>
          </div>
          {styleOpen && <div className="mt-3">{styleEditor}</div>}
        </div>
        {waveform}
      </div>

      {summary}
      {banners}
      {lineList}
      {actions}
    </section>
  );
}
