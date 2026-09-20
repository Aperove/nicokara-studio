export type TimelineMora = {
  reading: string;
  start_ms: number;
  end_ms: number;
  matched: boolean;
  confidence: number;
};

export type TimelineToken = {
  surface: string;
  reading: string;
  start_ms: number;
  end_ms: number;
  confidence: number;
  moras: TimelineMora[];
};

export type TimelineLine = {
  surface: string;
  reading: string;
  start_ms: number;
  end_ms: number;
  confidence: number;
  tokens: TimelineToken[];
};

export type Timeline = {
  confidence: number;
  lines: TimelineLine[];
  warnings: string[];
};

export type Review = {
  timeline: Timeline;
  /** "local" readings come from a dictionary and are wrong more often. */
  lyrics_provider?: string | null;
  can_edit_readings?: boolean;
  /** [start_ms, end_ms] stretches in which nobody sings. */
  rests: [number, number][];
  /** Lines the aligner moved out of a rest; worth a second look. */
  moved_lines: number[];
  /** Lines still timed inside a rest because no plausible place was found. */
  unresolved_lines: number[];
  /** Lines moved to their LRC time because the aligner was far off. */
  lrc_adjusted_lines?: number[];
  duration_ms: number | null;
  has_vocals: boolean;
  can_refine: boolean;
};

export type LineEdit = { index: number; start_ms: number; end_ms: number };

export type ReadingEdit = { line: number; token: number; reading: string };
