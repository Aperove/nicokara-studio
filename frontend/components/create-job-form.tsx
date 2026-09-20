"use client";

import {
  CheckCircle2,
  FileText,
  Film,
  Link2,
  Music2,
  Palette,
  Sparkles,
  Upload,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useRef, useState } from "react";

import { ErrorFeedbackPanel } from "@/components/error-feedback";
import { StylePanel } from "@/components/style-panel";
import {
  networkErrorFeedback,
  validationErrorFeedback,
  type ErrorFeedback,
} from "@/lib/error-feedback";
import { CREATE_COPY, STYLE_COPY, UPLOAD_COPY } from "@/lib/ui-copy";
import { ApiRequestError, createJob } from "@/services/api";
import { DEFAULT_SUBTITLE_STYLE, type SubtitleStyle } from "@/types/style";

const MAX_VIDEO_BYTES = 1024 * 1024 * 1024;

type Source = "file" | "link";

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function SegmentButton({
  active,
  onClick,
  disabled,
  children,
}: {
  active: boolean;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      className={`focus-ring flex flex-1 items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition disabled:opacity-50 ${
        active
          ? "border-primary bg-primary/10 text-primary"
          : "bg-card text-muted-foreground hover:bg-muted"
      }`}
    >
      {children}
    </button>
  );
}

export function CreateJobForm() {
  const router = useRouter();
  const videoInput = useRef<HTMLInputElement>(null);
  const lyricsInput = useRef<HTMLInputElement>(null);
  const [source, setSource] = useState<Source>("file");
  const [video, setVideo] = useState<File | null>(null);
  const [videoUrl, setVideoUrl] = useState("");
  const [lyricsText, setLyricsText] = useState("");
  const [lyricsFile, setLyricsFile] = useState<File | null>(null);
  const [review, setReview] = useState(true);
  const [style, setStyle] = useState<SubtitleStyle>(DEFAULT_SUBTITLE_STYLE);
  const [styleOpen, setStyleOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<ErrorFeedback | null>(null);

  function fail(title: string) {
    setError({
      title,
      description: "",
      solutions: [],
      technicalDetails: [],
      retryable: false,
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    if (source === "file") {
      if (!video) return setError(validationErrorFeedback("video_required"));
      if (!video.name.toLowerCase().endsWith(".mp4")) {
        return setError(validationErrorFeedback("invalid_video_type"));
      }
      if (video.size > MAX_VIDEO_BYTES) {
        return setError(validationErrorFeedback("video_too_large"));
      }
    } else {
      if (!videoUrl.trim()) return fail(CREATE_COPY.linkRequired);
      if (!isHttpUrl(videoUrl.trim())) return fail(CREATE_COPY.invalidLink);
    }
    if (!lyricsText.trim() && !lyricsFile) {
      return setError(validationErrorFeedback("lyrics_required"));
    }
    if (lyricsText.trim() && lyricsFile) {
      return setError(validationErrorFeedback("lyrics_source_conflict"));
    }

    setSubmitting(true);
    try {
      const job = await createJob(
        {
          video: source === "file" ? (video ?? undefined) : undefined,
          videoUrl: source === "link" ? videoUrl : undefined,
          lyricsText,
          lyricsFile: lyricsFile ?? undefined,
          style,
          review,
        },
        setProgress,
      );
      router.push(`/jobs/${job.id}`);
    } catch (reason) {
      setError(
        reason instanceof ApiRequestError
          ? reason.feedback
          : networkErrorFeedback("upload"),
      );
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-6">
      <section aria-labelledby="source-heading">
        <h2 id="source-heading" className="mb-2.5 text-sm font-semibold">
          {CREATE_COPY.sourceTitle}
        </h2>
        <div className="mb-3 flex gap-2">
          <SegmentButton
            active={source === "file"}
            disabled={submitting}
            onClick={() => setSource("file")}
          >
            <Film className="size-4" />
            {CREATE_COPY.sourceFile}
          </SegmentButton>
          <SegmentButton
            active={source === "link"}
            disabled={submitting}
            onClick={() => setSource("link")}
          >
            <Link2 className="size-4" />
            {CREATE_COPY.sourceLink}
          </SegmentButton>
        </div>

        {source === "file" ? (
          <>
            <input
              ref={videoInput}
              type="file"
              accept="video/mp4,.mp4"
              className="sr-only"
              onChange={(event) => {
                setVideo(event.target.files?.[0] ?? null);
                setError(null);
              }}
            />
            <button
              type="button"
              disabled={submitting}
              onClick={() => videoInput.current?.click()}
              className="focus-ring group flex min-h-24 w-full items-center justify-center rounded-xl border border-dashed bg-card px-5 text-center transition hover:border-primary/60 hover:bg-accent/35"
            >
              {video ? (
                <span className="flex items-center gap-3 text-left">
                  <CheckCircle2 className="size-5 shrink-0 text-primary" />
                  <span>
                    <span className="block text-sm font-medium">{video.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {formatBytes(video.size)} · 点击重新选择
                    </span>
                  </span>
                </span>
              ) : (
                <span>
                  <span className="block text-sm font-medium">
                    {UPLOAD_COPY.videoPrompt}
                  </span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {UPLOAD_COPY.videoHelp}
                  </span>
                </span>
              )}
            </button>
          </>
        ) : (
          <div>
            <input
              type="url"
              inputMode="url"
              value={videoUrl}
              disabled={submitting}
              aria-label={CREATE_COPY.linkLabel}
              placeholder={CREATE_COPY.linkPlaceholder}
              onChange={(event) => {
                setVideoUrl(event.target.value);
                setError(null);
              }}
              className="focus-ring w-full rounded-xl border bg-card px-4 py-3 text-sm placeholder:text-muted-foreground/60 disabled:bg-muted"
            />
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              {CREATE_COPY.linkHelp}
              {CREATE_COPY.linkRights}
            </p>
          </div>
        )}
      </section>

      <section aria-labelledby="lyrics-heading">
        <h2 id="lyrics-heading" className="mb-2.5 text-sm font-semibold">
          {UPLOAD_COPY.lyricsSectionTitle}
        </h2>
        <textarea
          value={lyricsText}
          disabled={Boolean(lyricsFile) || submitting}
          onChange={(event) => setLyricsText(event.target.value)}
          rows={9}
          placeholder={CREATE_COPY.lyricsPlaceholder}
          className="focus-ring w-full resize-y rounded-xl border bg-card px-4 py-3 text-sm leading-7 placeholder:text-muted-foreground/60 disabled:cursor-not-allowed disabled:bg-muted"
        />
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <input
            ref={lyricsInput}
            type="file"
            accept=".txt,text/plain"
            className="sr-only"
            onChange={(event) => {
              setLyricsFile(event.target.files?.[0] ?? null);
              setLyricsText("");
              setError(null);
            }}
          />
          <button
            type="button"
            disabled={submitting}
            onClick={() => lyricsInput.current?.click()}
            className="focus-ring inline-flex items-center gap-2 rounded-lg border bg-card px-3 py-1.5 text-sm font-medium transition hover:bg-muted disabled:opacity-50"
          >
            <FileText className="size-4" />
            {lyricsFile ? lyricsFile.name : "选择 TXT 文件"}
          </button>
          {lyricsFile ? (
            <button
              type="button"
              onClick={() => {
                setLyricsFile(null);
                if (lyricsInput.current) lyricsInput.current.value = "";
              }}
              className="focus-ring rounded-sm text-sm text-muted-foreground underline-offset-4 hover:underline"
            >
              移除文件
            </button>
          ) : (
            <span className="text-xs text-muted-foreground">
              {UPLOAD_COPY.lyricsHint}
            </span>
          )}
        </div>
      </section>

      <section aria-labelledby="options-heading" className="space-y-3">
        <h2 id="options-heading" className="text-sm font-semibold">
          {CREATE_COPY.optionsTitle}
        </h2>
        <p className="flex items-start gap-2 rounded-xl border bg-card px-4 py-3 text-sm text-muted-foreground">
          <Music2 className="mt-0.5 size-4 shrink-0 text-primary" />
          {CREATE_COPY.bothVersions}
        </p>

        <label className="flex items-start gap-3 rounded-xl border bg-card px-4 py-3 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={review}
            disabled={submitting}
            onChange={(event) => setReview(event.target.checked)}
          />
          <span>
            <span className="font-medium">{UPLOAD_COPY.reviewLabel}</span>
            <span className="mt-0.5 block text-xs text-muted-foreground">
              {UPLOAD_COPY.reviewHint}
            </span>
          </span>
        </label>

        <div className="rounded-xl border bg-card px-4 py-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm">
              <span className="font-medium">{STYLE_COPY.sectionTitle}</span>
              {!styleOpen && (
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {STYLE_COPY.defaultSummary}
                </span>
              )}
            </span>
            <button
              type="button"
              aria-expanded={styleOpen}
              onClick={() => setStyleOpen((open) => !open)}
              className="focus-ring inline-flex shrink-0 items-center gap-2 rounded-lg border bg-card px-3 py-1.5 text-sm font-medium transition hover:bg-muted"
            >
              <Palette className="size-4" />
              {styleOpen ? STYLE_COPY.collapse : STYLE_COPY.expand}
            </button>
          </div>
          {styleOpen && (
            <div className="mt-4">
              <StylePanel value={style} onChange={setStyle} disabled={submitting} />
            </div>
          )}
        </div>
      </section>

      {error && <ErrorFeedbackPanel feedback={error} />}

      {submitting && source === "file" && (
        <div aria-live="polite">
          <div className="mb-2 flex justify-between text-sm">
            <span>{UPLOAD_COPY.uploadProgressTitle}</span>
            <span className="font-medium">{progress}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-[width]"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="focus-ring inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-5 py-3 font-semibold text-primary-foreground transition hover:brightness-95 disabled:cursor-wait disabled:opacity-60"
      >
        {submitting ? (
          <Upload className="size-5 animate-pulse" />
        ) : (
          <Sparkles className="size-5" />
        )}
        {submitting ? UPLOAD_COPY.uploadingButton : UPLOAD_COPY.submitButton}
      </button>
    </form>
  );
}
