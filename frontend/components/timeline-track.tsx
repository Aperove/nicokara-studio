"use client";

import { ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { formatSeconds, waveformPeaks } from "@/lib/timeline";
import { REVIEW_COPY } from "@/lib/ui-copy";
import type { TimelineLine } from "@/types/timeline";

const PEAK_BUCKET_MS = 10;
const ZOOM_LEVELS_MS = [8_000, 15_000, 30_000, 60_000, 120_000];
const MIN_LINE_MS = 200;
const TRACK_HEIGHT = 112;

type DragMode = "move" | "start" | "end";
type Drag = {
  index: number;
  mode: DragMode;
  pointerX: number;
  startMs: number;
  endMs: number;
};

type Props = {
  lines: TimelineLine[];
  rests: [number, number][];
  editedIndexes: number[];
  currentIndex: number;
  timeMs: number;
  durationMs: number;
  audioUrl: string;
  onSeek: (ms: number) => void;
  onChange: (index: number, startMs: number, endMs: number) => void;
};

export function TimelineTrack({
  lines,
  rests,
  editedIndexes,
  currentIndex,
  timeMs,
  durationMs,
  audioUrl,
  onSeek,
  onChange,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dragRef = useRef<Drag | null>(null);
  const [loaded, setLoaded] = useState<{
    url: string;
    peaks: Float32Array;
  } | null>(null);
  const peaks = loaded?.url === audioUrl ? loaded.peaks : null;
  const [zoom, setZoom] = useState(1);
  const [viewStart, setViewStart] = useState(0);
  const [follow, setFollow] = useState(true);
  const [width, setWidth] = useState(0);
  // While a block is being dragged the view must not move under the pointer.
  const [frozenStart, setFrozenStart] = useState<number | null>(null);

  const span = Math.min(ZOOM_LEVELS_MS[zoom], Math.max(durationMs, 1_000));
  const maxStart = Math.max(0, durationMs - span);
  // Following the playhead turns the view page by page, so blocks hold still
  // long enough to be grabbed.
  const page = span * 0.8;
  const wanted =
    frozenStart ??
    (follow ? Math.floor(timeMs / page) * page - span * 0.05 : viewStart);
  const start = Math.min(Math.max(0, wanted), maxStart);
  const toX = (ms: number) => ((ms - start) / span) * width;

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver(() => setWidth(element.clientWidth));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const response = await fetch(audioUrl);
        const context = new AudioContext();
        const audio = await context.decodeAudioData(await response.arrayBuffer());
        void context.close();
        if (active) {
          setLoaded({
            url: audioUrl,
            peaks: waveformPeaks(
              audio.getChannelData(0),
              audio.sampleRate,
              PEAK_BUCKET_MS,
            ),
          });
        }
      } catch {
        // The track stays usable without a waveform.
      }
    })();
    return () => {
      active = false;
    };
  }, [audioUrl]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !width) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(TRACK_HEIGHT * ratio);
    const context = canvas.getContext("2d");
    if (!context) return;
    context.scale(ratio, ratio);
    context.clearRect(0, 0, width, TRACK_HEIGHT);
    context.fillStyle = "#0f172a";
    context.fillRect(0, 0, width, TRACK_HEIGHT);

    // second ticks
    const tickMs = span <= 15_000 ? 1_000 : span <= 60_000 ? 5_000 : 10_000;
    context.font = "10px ui-monospace, monospace";
    for (
      let tick = Math.ceil(start / tickMs) * tickMs;
      tick <= start + span;
      tick += tickMs
    ) {
      const x = ((tick - start) / span) * width;
      context.fillStyle = "#334155";
      context.fillRect(x, 0, 1, TRACK_HEIGHT);
      context.fillStyle = "#94a3b8";
      context.fillText(formatSeconds(tick).slice(0, -3), x + 3, 10);
    }

    if (peaks) {
      const middle = TRACK_HEIGHT / 2 + 6;
      const reach = TRACK_HEIGHT / 2 - 10;
      // Dim enough for the white block labels on top to stay readable.
      context.fillStyle = "rgba(56, 189, 248, 0.45)";
      for (let x = 0; x < width; x++) {
        const from = Math.floor((start + (x / width) * span) / PEAK_BUCKET_MS);
        const to = Math.max(
          from + 1,
          Math.floor((start + ((x + 1) / width) * span) / PEAK_BUCKET_MS),
        );
        let peak = 0;
        for (let bucket = from; bucket < to && bucket < peaks.length; bucket++) {
          if (peaks[bucket] > peak) peak = peaks[bucket];
        }
        const height = Math.max(1, Math.sqrt(peak) * reach);
        context.fillRect(x, middle - height, 1, height * 2);
      }
    }
  }, [peaks, start, span, width]);

  function msAt(clientX: number): number {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect || !rect.width) return 0;
    return start + ((clientX - rect.left) / rect.width) * span;
  }

  function beginDrag(
    event: React.PointerEvent,
    index: number,
    mode: DragMode,
  ) {
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      index,
      mode,
      pointerX: event.clientX,
      startMs: lines[index].start_ms,
      endMs: lines[index].end_ms,
    };
    setFrozenStart(start);
  }

  function moveDrag(event: React.PointerEvent) {
    const drag = dragRef.current;
    if (!drag || !width) return;
    const delta = ((event.clientX - drag.pointerX) / width) * span;
    const previousStart = drag.index > 0 ? lines[drag.index - 1].start_ms : -1;
    const nextStart =
      drag.index + 1 < lines.length
        ? lines[drag.index + 1].start_ms
        : durationMs + 1;
    // A line has to stay between the starts of its neighbours.
    const lowest = Math.max(0, previousStart + MIN_LINE_MS);
    let startMs = drag.startMs;
    let endMs = drag.endMs;
    if (drag.mode === "move") {
      const length = drag.endMs - drag.startMs;
      startMs = Math.min(
        Math.max(lowest, drag.startMs + delta),
        Math.min(durationMs, nextStart - 1) - length,
      );
      endMs = startMs + length;
    } else if (drag.mode === "start") {
      startMs = Math.min(
        Math.max(lowest, drag.startMs + delta),
        drag.endMs - MIN_LINE_MS,
      );
    } else {
      endMs = Math.max(
        drag.startMs + MIN_LINE_MS,
        Math.min(drag.endMs + delta, durationMs, nextStart - 1),
      );
    }
    onChange(drag.index, Math.round(startMs), Math.round(endMs));
  }

  function endDrag() {
    dragRef.current = null;
    // Stay where the person was working instead of jumping to the playhead.
    setViewStart(start);
    setFollow(false);
    setFrozenStart(null);
  }

  return (
    <div className="space-y-1.5">
      <div
        ref={containerRef}
        className="relative cursor-crosshair touch-none select-none overflow-hidden rounded-xl"
        style={{ height: TRACK_HEIGHT }}
        onPointerDown={(event) => onSeek(Math.max(0, msAt(event.clientX)))}
      >
        <canvas
          ref={canvasRef}
          className="absolute inset-0 size-full"
          aria-hidden
        />
        {rests.map(([restStart, restEnd]) => {
          const left = Math.max(0, toX(restStart));
          const right = Math.min(width, toX(restEnd));
          if (right <= 0 || left >= width) return null;
          return (
            <div
              key={restStart}
              aria-hidden
              className="pointer-events-none absolute inset-y-0 border-x border-dashed border-slate-500 bg-slate-950/70"
              style={{ left, width: right - left }}
            >
              <span className="absolute bottom-1 left-1.5 text-[10px] text-slate-400">
                {REVIEW_COPY.restLabel}
              </span>
            </div>
          );
        })}
        {lines.map((line, index) => {
          const left = toX(line.start_ms);
          const right = toX(line.end_ms);
          if (right < -2 || left > width + 2) return null;
          const edited = editedIndexes.includes(index);
          return (
            <div
              key={index}
              role="slider"
              tabIndex={-1}
              aria-label={`${REVIEW_COPY.trackLine} ${index + 1}`}
              aria-valuemin={0}
              aria-valuemax={durationMs}
              aria-valuenow={line.start_ms}
              aria-valuetext={`${formatSeconds(line.start_ms)} – ${formatSeconds(line.end_ms)}`}
              title={`${index + 1}  ${formatSeconds(line.start_ms)} – ${formatSeconds(line.end_ms)}`}
              className={`absolute bottom-1.5 top-4 cursor-grab overflow-hidden rounded-md border text-xs active:cursor-grabbing ${
                index === currentIndex
                  ? "border-[#FF6B6B] bg-[#FF6B6B]/35"
                  : edited
                    ? "border-amber-300 bg-amber-300/25"
                    : "border-white/60 bg-white/15"
              }`}
              style={{ left, width: Math.max(4, right - left) }}
              onPointerDown={(event) => beginDrag(event, index, "move")}
              onPointerMove={moveDrag}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
            >
              <span
                className="absolute inset-y-0 left-0 w-2 cursor-ew-resize bg-white/70"
                onPointerDown={(event) => beginDrag(event, index, "start")}
                onPointerMove={moveDrag}
                onPointerUp={endDrag}
                onPointerCancel={endDrag}
              />
              <span
                className="absolute inset-y-0 right-0 w-2 cursor-ew-resize bg-white/70"
                onPointerDown={(event) => beginDrag(event, index, "end")}
                onPointerMove={moveDrag}
                onPointerUp={endDrag}
                onPointerCancel={endDrag}
              />
              <span className="pointer-events-none block truncate px-3 pt-0.5 font-medium text-white [text-shadow:0_1px_2px_rgb(15_23_42)]">
                <span className="mr-1.5 font-mono opacity-80">{index + 1}</span>
                {line.surface}
              </span>
            </div>
          );
        })}
        {timeMs >= start && timeMs <= start + span && (
          <div
            aria-hidden
            className="pointer-events-none absolute inset-y-0 w-0.5 bg-[#FF6B6B]"
            style={{ left: toX(timeMs) }}
          />
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <button
          type="button"
          disabled={zoom === 0}
          onClick={() => setZoom((level) => Math.max(0, level - 1))}
          aria-label={REVIEW_COPY.zoomIn}
          title={REVIEW_COPY.zoomIn}
          className="focus-ring rounded border bg-card p-1 transition hover:bg-muted disabled:opacity-40"
        >
          <ZoomIn className="size-3.5" />
        </button>
        <button
          type="button"
          disabled={zoom === ZOOM_LEVELS_MS.length - 1}
          onClick={() =>
            setZoom((level) => Math.min(ZOOM_LEVELS_MS.length - 1, level + 1))
          }
          aria-label={REVIEW_COPY.zoomOut}
          title={REVIEW_COPY.zoomOut}
          className="focus-ring rounded border bg-card p-1 transition hover:bg-muted disabled:opacity-40"
        >
          <ZoomOut className="size-3.5" />
        </button>
        <span className="font-mono">
          {formatSeconds(start).slice(0, -3)} –{" "}
          {formatSeconds(start + span).slice(0, -3)}
        </span>
        <input
          type="range"
          min={0}
          max={Math.max(1, maxStart)}
          step={100}
          value={start}
          aria-label={REVIEW_COPY.trackScroll}
          onChange={(event) => {
            setFollow(false);
            setViewStart(Number(event.target.value));
          }}
          className="min-w-32 flex-1 accent-[var(--color-primary)]"
        />
        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={follow}
            onChange={(event) => {
              setViewStart(start);
              setFollow(event.target.checked);
            }}
          />
          {REVIEW_COPY.followPlayhead}
        </label>
      </div>
      <p className="text-xs text-muted-foreground">{REVIEW_COPY.trackHint}</p>
    </div>
  );
}
