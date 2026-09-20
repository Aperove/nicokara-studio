import { describe, expect, it } from "vitest";

import { jobPresentation } from "./job-presentation";
import {
  activeLineIndex,
  formatSeconds,
  lineConcerns,
  parseTime,
  retimeLine,
  tokenProgress,
  typicalPace,
  waveformPeaks,
} from "./timeline";
import type { TimelineLine } from "@/types/timeline";

function lineOf(
  text: string,
  startMs: number,
  stepMs: number,
  confidence = 1,
): TimelineLine {
  const moras = [...text].map((reading, index) => ({
    reading,
    start_ms: startMs + index * stepMs,
    end_ms: startMs + (index + 1) * stepMs,
    matched: true,
    confidence: 1,
  }));
  const endMs = startMs + text.length * stepMs;
  return {
    surface: text,
    reading: text,
    start_ms: startMs,
    end_ms: endMs,
    confidence,
    tokens: [
      {
        surface: text,
        reading: text,
        start_ms: startMs,
        end_ms: endMs,
        confidence,
        moras,
      },
    ],
  };
}

describe("timeline review helpers", () => {
  it("retimes a line while keeping the rhythm inside it", () => {
    const moved = retimeLine(lineOf("あいうえお", 10_000, 400), 20_000, 24_000);

    expect([moved.start_ms, moved.end_ms]).toEqual([20_000, 24_000]);
    expect(moved.tokens[0].moras.map((mora) => mora.start_ms)).toEqual([
      20_000, 20_800, 21_600, 22_400, 23_200,
    ]);
    expect(moved.tokens[0].end_ms).toBe(24_000);
  });

  it("spreads a line that had no duration evenly over its moras", () => {
    const collapsed = lineOf("あいうえ", 5_000, 0);

    const moved = retimeLine(collapsed, 6_000, 8_000);

    expect(moved.tokens[0].moras.map((mora) => mora.start_ms)).toEqual([
      6_000, 6_500, 7_000, 7_500,
    ]);
  });

  it("reports how much of a token has been sung", () => {
    const token = lineOf("あいうえ", 1_000, 500).tokens[0];

    expect(tokenProgress(token, 500)).toBe(0);
    expect(tokenProgress(token, 1_750)).toBeCloseTo(0.375);
    expect(tokenProgress(token, 3_000)).toBe(1);
  });

  it("follows the playhead to the current or upcoming line", () => {
    const lines = [lineOf("あい", 1_000, 500), lineOf("うえ", 5_000, 500)];

    expect(activeLineIndex(lines, 0)).toBe(0);
    expect(activeLineIndex(lines, 1_500)).toBe(0);
    expect(activeLineIndex(lines, 3_000)).toBe(1);
    expect(activeLineIndex(lines, 99_000)).toBe(1);
  });

  it("flags lines that deserve a closer look", () => {
    expect(lineConcerns(lineOf("あいうえお", 0, 400))).toEqual([]);
    expect(lineConcerns(lineOf("あい", 0, 100))).toEqual(["short"]);
    expect(lineConcerns(lineOf("あいうえお", 0, 400, 0.2))).toEqual([
      "low_confidence",
    ]);
  });

  it("flags a squeezed line next to a stretched one by their pace", () => {
    // Four lines sung at 400 ms per mora; a misplaced boundary squeezes the
    // fifth to 100 ms per mora and stretches the sixth to 1200 ms per mora.
    const lines = [
      lineOf("あいうえお", 0, 400),
      lineOf("かきくけこ", 3_000, 400),
      lineOf("さしすせそ", 6_000, 400),
      lineOf("たちつてと", 9_000, 400),
      lineOf("なにぬねの", 12_000, 100),
      lineOf("はひふへほ", 12_500, 1_200),
    ];
    const pace = typicalPace(lines);

    expect(pace).toBe(400);
    expect(lines.map((line) => lineConcerns(line, pace))).toEqual([
      [],
      [],
      [],
      [],
      ["short", "odd_pace"],
      ["odd_pace"],
    ]);
  });

  it("formats playhead positions", () => {
    expect(formatSeconds(0)).toBe("0:00.00");
    expect(formatSeconds(83_450)).toBe("1:23.45");
  });

  it("reads times the way the player shows them", () => {
    expect(parseTime("1:29.08")).toBe(89_080);
    expect(parseTime("89.08")).toBe(89_080);
    expect(parseTime(" 2:05 ")).toBe(125_000);
    expect(parseTime(formatSeconds(95_840))).toBe(95_840);
    expect(parseTime("1:75")).toBeNull();
    expect(parseTime("abc")).toBeNull();
    expect(parseTime("")).toBeNull();
  });

  it("reduces samples to the loudest value per bucket", () => {
    const samples = new Float32Array([0.1, -0.5, 0.2, 0.0, -0.9, 0.3, 0.4]);

    // 1 kHz audio in 3 ms buckets: three samples per bucket.
    expect(Array.from(waveformPeaks(samples, 1000, 3))).toEqual([
      0.5,
      expect.closeTo(0.9),
      expect.closeTo(0.4),
    ]);
  });

  it("presents a job waiting for review as a paused, non-failing state", () => {
    expect(jobPresentation("AWAITING_REVIEW", "REVIEW_PENDING")).toMatchObject({
      terminal: true,
      tone: "pending",
      progressLabel: "等待核对",
    });
  });
});
