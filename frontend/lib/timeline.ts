import type { TimelineLine, TimelineToken } from "@/types/timeline";

const SHORT_LINE_MS = 1000;
const LOW_CONFIDENCE = 0.5;

/** Move a line to a new window, keeping the rhythm inside it (mirrors the API). */
export function retimeLine(
  line: TimelineLine,
  startMs: number,
  endMs: number,
): TimelineLine {
  const oldSpan = line.end_ms - line.start_ms;
  const newSpan = endMs - startMs;
  const moraTotal = line.tokens.reduce(
    (total, token) => total + token.moras.length,
    0,
  );
  const scale = (value: number) =>
    startMs + Math.round(((value - line.start_ms) * newSpan) / oldSpan);

  let moraOffset = 0;
  const tokens: TimelineToken[] = [];
  for (const token of line.tokens) {
    const moras = token.moras.map((mora) => {
      const position = moraOffset++;
      return oldSpan > 0
        ? { ...mora, start_ms: scale(mora.start_ms), end_ms: scale(mora.end_ms) }
        : {
            ...mora,
            start_ms: startMs + Math.floor((newSpan * position) / moraTotal),
            end_ms: startMs + Math.floor((newSpan * (position + 1)) / moraTotal),
          };
    });
    const previousEnd = tokens.length ? tokens[tokens.length - 1].end_ms : startMs;
    tokens.push({
      ...token,
      moras,
      start_ms: moras.length
        ? moras[0].start_ms
        : oldSpan > 0
          ? scale(token.start_ms)
          : previousEnd,
      end_ms: moras.length
        ? moras[moras.length - 1].end_ms
        : oldSpan > 0
          ? scale(token.end_ms)
          : previousEnd,
    });
  }
  return { ...line, start_ms: startMs, end_ms: endMs, tokens };
}

/** How much of a token has been sung at `timeMs`, from 0 to 1. */
export function tokenProgress(token: TimelineToken, timeMs: number): number {
  if (timeMs >= token.end_ms) return 1;
  if (timeMs <= token.start_ms) return 0;
  if (!token.moras.length) {
    return (timeMs - token.start_ms) / (token.end_ms - token.start_ms);
  }
  let sung = 0;
  for (const mora of token.moras) {
    if (timeMs >= mora.end_ms) {
      sung += 1;
    } else if (timeMs > mora.start_ms) {
      sung += (timeMs - mora.start_ms) / (mora.end_ms - mora.start_ms);
    }
  }
  return sung / token.moras.length;
}

/** The line being sung at `timeMs`, else the next one coming up. */
export function activeLineIndex(lines: TimelineLine[], timeMs: number): number {
  for (let index = 0; index < lines.length; index++) {
    if (timeMs < lines[index].end_ms) return index;
  }
  return lines.length - 1;
}

export type LineConcern = "short" | "low_confidence" | "odd_pace";

function moraCount(line: TimelineLine): number {
  return Math.max(
    1,
    line.tokens.reduce((total, token) => total + token.moras.length, 0),
  );
}

/** Milliseconds per mora at which the song is usually sung. */
export function typicalPace(lines: TimelineLine[]): number {
  const paces = lines
    .map((line) => (line.end_ms - line.start_ms) / moraCount(line))
    .filter((pace) => pace >= 90 && pace <= 900)
    .sort((a, b) => a - b);
  return paces.length ? paces[Math.floor(paces.length / 2)] : 250;
}

/**
 * Why a line deserves a closer look during review, if at all.
 *
 * A wrongly placed boundary squeezes one line and stretches its neighbour,
 * so a line sung far faster or slower than the rest of the song is suspect.
 */
export function lineConcerns(line: TimelineLine, pace?: number): LineConcern[] {
  const concerns: LineConcern[] = [];
  const duration = line.end_ms - line.start_ms;
  if (duration < SHORT_LINE_MS) concerns.push("short");
  if (line.confidence < LOW_CONFIDENCE) concerns.push("low_confidence");
  if (pace) {
    const ratio = duration / moraCount(line) / pace;
    if (ratio < 0.45 || ratio > 2.2) concerns.push("odd_pace");
  }
  return concerns;
}

export function formatSeconds(ms: number): string {
  const minutes = Math.floor(ms / 60000);
  const seconds = (ms % 60000) / 1000;
  return `${minutes}:${seconds.toFixed(2).padStart(5, "0")}`;
}

/** Parse "1:29.08", "1:29" or plain seconds ("89.08") into milliseconds. */
export function parseTime(text: string): number | null {
  const match = /^\s*(?:(\d+):)?(\d+(?:\.\d*)?)\s*$/.exec(text);
  if (!match) return null;
  const minutes = match[1] ? Number(match[1]) : 0;
  const seconds = Number(match[2]);
  if (!Number.isFinite(seconds) || (match[1] && seconds >= 60)) return null;
  return Math.round((minutes * 60 + seconds) * 1000);
}

/** Loudest sample per bucket, for drawing a waveform. */
export function waveformPeaks(
  samples: Float32Array,
  sampleRate: number,
  bucketMs: number,
): Float32Array {
  const bucketSize = Math.max(1, Math.round((sampleRate * bucketMs) / 1000));
  const peaks = new Float32Array(Math.ceil(samples.length / bucketSize));
  for (let bucket = 0; bucket < peaks.length; bucket++) {
    const end = Math.min(samples.length, (bucket + 1) * bucketSize);
    let peak = 0;
    for (let index = bucket * bucketSize; index < end; index++) {
      const value = Math.abs(samples[index]);
      if (value > peak) peak = value;
    }
    peaks[bucket] = peak;
  }
  return peaks;
}
