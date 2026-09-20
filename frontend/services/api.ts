import type { Job } from "@/types/job";
import type { SubtitleStyle } from "@/types/style";
import type {
  LineEdit,
  ReadingEdit,
  Review,
  Timeline,
} from "@/types/timeline";
import {
  httpErrorFeedback,
  networkErrorFeedback,
  type ErrorContext,
  type ErrorFeedback,
} from "@/lib/error-feedback";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

type CreateJobInput = {
  /** Exactly one of `video` and `videoUrl` is given. */
  video?: File;
  videoUrl?: string;
  lyricsText?: string;
  lyricsFile?: File;
  vocalMode?: string;
  style?: SubtitleStyle;
  review?: boolean;
};

export class ApiRequestError extends Error {
  readonly feedback: ErrorFeedback;

  constructor(feedback: ErrorFeedback) {
    super(`${feedback.title}：${feedback.description}`);
    this.name = "ApiRequestError";
    this.feedback = feedback;
  }
}

function responseDetail(xhr: XMLHttpRequest): string | null {
  try {
    const body = JSON.parse(xhr.responseText) as { detail?: string };
    return typeof body.detail === "string" ? body.detail : null;
  } catch {
    return xhr.responseText?.trim() || null;
  }
}

function retryAfterSeconds(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number.parseInt(value, 10);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : undefined;
}

function xhrRequestError(xhr: XMLHttpRequest): ApiRequestError {
  return new ApiRequestError(
    httpErrorFeedback(
      "upload",
      xhr.status,
      responseDetail(xhr),
      retryAfterSeconds(xhr.getResponseHeader("Retry-After")),
    ),
  );
}

async function fetchResponseDetail(response: Response): Promise<string | null> {
  const text = await response.text();
  if (!text.trim()) return response.statusText || null;
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : text.trim();
  } catch {
    return text.trim();
  }
}

function connectionError(context: ErrorContext): ApiRequestError {
  return new ApiRequestError(networkErrorFeedback(context));
}

export function createJob(
  input: CreateJobInput,
  onProgress: (progress: number) => void,
): Promise<Job> {
  return new Promise((resolve, reject) => {
    const data = new FormData();
    if (input.video) {
      data.append("video", input.video);
    } else if (input.videoUrl?.trim()) {
      data.append("video_url", input.videoUrl.trim());
    }
    if (input.lyricsText?.trim()) {
      data.append("lyrics_text", input.lyricsText.trim());
    }
    if (input.lyricsFile) {
      data.append("lyrics_file", input.lyricsFile);
    }
    if (input.vocalMode) {
      data.append("vocal_mode", input.vocalMode);
    }
    if (input.style) {
      data.append("style", JSON.stringify(input.style));
    }
    if (input.review) {
      data.append("review", "true");
    }

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/jobs`);
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as Job);
      } else {
        reject(xhrRequestError(xhr));
      }
    });
    xhr.addEventListener("error", () => {
      reject(connectionError("upload"));
    });
    xhr.addEventListener("abort", () => {
      reject(connectionError("upload"));
    });
    xhr.send(data);
  });
}

export async function getJob(jobId: string): Promise<Job> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/jobs/${jobId}`, {
      cache: "no-store",
    });
  } catch {
    throw connectionError("job");
  }
  if (!response.ok) {
    throw new ApiRequestError(
      httpErrorFeedback(
        "job",
        response.status,
        await fetchResponseDetail(response),
        retryAfterSeconds(response.headers.get("Retry-After")),
      ),
    );
  }
  return (await response.json()) as Job;
}

async function jsonRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      cache: "no-store",
      ...init,
    });
  } catch {
    throw connectionError("job");
  }
  if (!response.ok) {
    throw new ApiRequestError(
      httpErrorFeedback(
        "job",
        response.status,
        await fetchResponseDetail(response),
        retryAfterSeconds(response.headers.get("Retry-After")),
      ),
    );
  }
  return (await response.json()) as T;
}

export type Capabilities = {
  /** Sites a job may be created from by link; empty when links are off. */
  video_link_hosts: string[];
  job_listing: boolean;
};

export function getCapabilities(): Promise<Capabilities> {
  return jsonRequest<Capabilities>("/capabilities");
}

export function listJobs(limit = 20): Promise<Job[]> {
  return jsonRequest<Job[]>(`/jobs?limit=${limit}`);
}

export function getJobStyle(jobId: string): Promise<SubtitleStyle> {
  return jsonRequest<SubtitleStyle>(`/jobs/${jobId}/style`);
}

export function restyleJob(
  jobId: string,
  style: SubtitleStyle,
): Promise<Job> {
  return jsonRequest<Job>(`/jobs/${jobId}/restyle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(style),
  });
}

export function getReview(jobId: string): Promise<Review> {
  return jsonRequest<Review>(`/jobs/${jobId}/review`);
}

export function saveTimeline(
  jobId: string,
  lines: LineEdit[],
): Promise<{ timeline: Timeline }> {
  return jsonRequest<{ timeline: Timeline }>(`/jobs/${jobId}/timeline`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lines }),
  });
}

export function saveReadings(
  jobId: string,
  edits: ReadingEdit[],
): Promise<{ timeline: Timeline; changed_lines: number[] }> {
  return jsonRequest<{ timeline: Timeline; changed_lines: number[] }>(
    `/jobs/${jobId}/readings`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ edits }),
    },
  );
}

export function refineTimelineLines(
  jobId: string,
  lines: number[],
): Promise<{ timeline: Timeline; refined_lines: number[] }> {
  return jsonRequest<{ timeline: Timeline; refined_lines: number[] }>(
    `/jobs/${jobId}/timeline/refine`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lines }),
    },
  );
}

export function retryForcedAlignment(
  jobId: string,
): Promise<{ timeline: Timeline }> {
  return jsonRequest<{ timeline: Timeline }>(`/jobs/${jobId}/timeline/forced`, {
    method: "POST",
  });
}

/** A frame drawn by the real renderer; the caller revokes the object URL. */
export async function previewFrame(
  jobId: string,
  style: SubtitleStyle,
  timeMs: number | null,
  signal?: AbortSignal,
): Promise<{ url: string; timeMs: number }> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/jobs/${jobId}/preview`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ style, time_ms: timeMs }),
      signal,
    });
  } catch {
    throw connectionError("job");
  }
  if (!response.ok) {
    throw new ApiRequestError(
      httpErrorFeedback("job", response.status, await fetchResponseDetail(response)),
    );
  }
  return {
    url: URL.createObjectURL(await response.blob()),
    timeMs: Number(response.headers.get("X-Preview-Time-Ms") ?? timeMs ?? 0),
  };
}

export function renderJob(jobId: string, style?: SubtitleStyle): Promise<Job> {
  return jsonRequest<Job>(`/jobs/${jobId}/render`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(style ?? null),
  });
}

export function sourceVideoUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/source`;
}

export function audioTrackUrl(jobId: string, track: "mix" | "vocals"): string {
  return `${API_BASE}/jobs/${jobId}/audio/${track}`;
}

export function transcriptUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/transcript`;
}

export function processedLyricsUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/lyrics`;
}

export function timelineUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/timeline`;
}

export function subtitleUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/subtitle`;
}

export type VocalVersion = "on" | "off";

export function resultVideoUrl(jobId: string, vocal: VocalVersion = "on"): string {
  // The default version keeps its plain, stable address.
  return `${API_BASE}/jobs/${jobId}/result${vocal === "off" ? "?vocal=off" : ""}`;
}

export function downloadVideoUrl(
  jobId: string,
  vocal: VocalVersion = "on",
): string {
  return `${API_BASE}/jobs/${jobId}/download${vocal === "off" ? "?vocal=off" : ""}`;
}
