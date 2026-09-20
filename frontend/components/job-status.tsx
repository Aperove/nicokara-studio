"use client";

import {
  AlertCircle,
  Clapperboard,
  CheckCircle2,
  Clock3,
  Download,
  FileVideo,
  Hash,
  LoaderCircle,
  Palette,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ErrorFeedbackPanel } from "@/components/error-feedback";
import { StylePanel } from "@/components/style-panel";
import { TimelineReview } from "@/components/timeline-review";
import {
  jobFailureFeedback,
  networkErrorFeedback,
  type ErrorFeedback,
} from "@/lib/error-feedback";
import { jobPresentation } from "@/lib/job-presentation";
import { JOB_COPY, REVIEW_COPY, STYLE_COPY, UPLOAD_COPY } from "@/lib/ui-copy";
import {
  ApiRequestError,
  downloadVideoUrl,
  getJob,
  getJobStyle,
  processedLyricsUrl,
  restyleJob,
  resultVideoUrl,
  subtitleUrl,
  timelineUrl,
  transcriptUrl,
  type VocalVersion,
} from "@/services/api";
import type { Job } from "@/types/job";
import type { SubtitleStyle } from "@/types/style";

function formatBytes(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function ResultVideos({ job }: { job: Job }) {
  const [version, setVersion] = useState<VocalVersion>("on");
  const offAvailable = Boolean(job.off_vocal_available);
  const shown: VocalVersion = offAvailable ? version : "on";

  return (
    <section className="mt-8" aria-labelledby="result-video-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="result-video-heading" className="font-display text-xl font-bold">
          {JOB_COPY.resultHeading}
        </h2>
        {offAvailable && (
          <div className="flex gap-2 text-sm">
            {(
              [
                ["on", UPLOAD_COPY.vocalOnLabel],
                ["off", UPLOAD_COPY.vocalOffLabel],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={shown === value}
                onClick={() => setVersion(value)}
                className={`focus-ring rounded-lg border px-3 py-1.5 font-medium transition ${
                  shown === value
                    ? "border-primary bg-primary/10 text-primary"
                    : "bg-card text-muted-foreground hover:bg-muted"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>
      <video
        key={`${shown}-${job.updated_at}`}
        className="mt-4 aspect-video w-full rounded-2xl bg-black"
        controls
        playsInline
        preload="metadata"
        src={resultVideoUrl(job.id, shown)}
      >
        {JOB_COPY.unsupportedVideo}
      </video>
      <div className="mt-4 flex flex-wrap gap-3">
        <a
          href={downloadVideoUrl(job.id, "on")}
          className="focus-ring inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground"
        >
          <Download className="size-4" />
          {offAvailable ? JOB_COPY.downloadOnVocal : JOB_COPY.downloadVideo}
        </a>
        {offAvailable && (
          <a
            href={downloadVideoUrl(job.id, "off")}
            className="focus-ring inline-flex items-center gap-2 rounded-lg border bg-card px-5 py-3 text-sm font-semibold transition hover:bg-muted"
          >
            <Download className="size-4" />
            {JOB_COPY.downloadOffVocal}
          </a>
        )}
      </div>
      {!offAvailable && job.vocal_mode === "both" && (
        <p className="mt-3 text-xs text-muted-foreground">
          {JOB_COPY.offVocalMissing}
        </p>
      )}
    </section>
  );
}

function RestylePanel({
  jobId,
  onQueued,
}: {
  jobId: string;
  onQueued: () => void;
}) {
  const [style, setStyle] = useState<SubtitleStyle | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ErrorFeedback | null>(null);

  useEffect(() => {
    let active = true;
    getJobStyle(jobId)
      .then((value) => {
        if (active) setStyle(value);
      })
      .catch((reason) => {
        if (active) {
          setError(
            reason instanceof ApiRequestError
              ? reason.feedback
              : networkErrorFeedback("job"),
          );
        }
      });
    return () => {
      active = false;
    };
  }, [jobId]);

  async function submit() {
    if (!style) return;
    setSubmitting(true);
    setError(null);
    try {
      await restyleJob(jobId, style);
      onQueued();
    } catch (reason) {
      setError(
        reason instanceof ApiRequestError
          ? reason.feedback
          : networkErrorFeedback("job"),
      );
      setSubmitting(false);
    }
  }

  return (
    <section
      className="rounded-3xl border bg-card p-6 sm:p-9"
      aria-labelledby="restyle-heading"
    >
      <h2
        id="restyle-heading"
        className="flex items-center gap-2 font-display text-xl font-bold"
      >
        <Palette className="size-5 text-primary" />
        {STYLE_COPY.restyleHeading}
      </h2>
      <p className="mt-2 text-sm text-muted-foreground">
        {STYLE_COPY.restyleDescription}
      </p>
      <div className="mt-5 space-y-4">
        {error && <ErrorFeedbackPanel feedback={error} />}
        {style && (
          <>
            <StylePanel
              value={style}
              onChange={setStyle}
              disabled={submitting}
            />
            <button
              type="button"
              disabled={submitting}
              onClick={submit}
              className="focus-ring inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground transition hover:brightness-95 disabled:cursor-wait disabled:opacity-60"
            >
              <Palette className="size-4" />
              {submitting ? STYLE_COPY.restyling : STYLE_COPY.restyleButton}
            </button>
          </>
        )}
      </div>
    </section>
  );
}

export function JobStatus({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [requestError, setRequestError] = useState<ErrorFeedback | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [reviewOpen, setReviewOpen] = useState(false);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      try {
        const value = await getJob(jobId);
        if (!active) return;
        setJob(value);
        setRequestError(null);
        if (!jobPresentation(value.status, value.stage).terminal) {
          timer = setTimeout(poll, 1500);
        }
      } catch (reason) {
        if (active) {
          const feedback =
            reason instanceof ApiRequestError
              ? reason.feedback
              : networkErrorFeedback("job");
          setRequestError(feedback);
          if (feedback.retryable) {
            timer = setTimeout(poll, 5000);
          }
        }
      }
    }

    poll();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, refreshKey]);

  if (requestError && !job) {
    return (
      <div className="space-y-5 rounded-2xl border bg-card p-5 sm:p-8">
        <ErrorFeedbackPanel
          feedback={requestError}
          onRetry={
            requestError.retryable
              ? () => {
                  setRequestError(null);
                  setRefreshKey((value) => value + 1);
                }
              : undefined
          }
        />
        <Link
          href="/"
          className="focus-ring inline-block rounded-lg border px-4 py-2 text-sm font-medium"
        >
          {JOB_COPY.backToUpload}
        </Link>
      </div>
    );
  }

  if (!job) {
    return (
      <div className="flex items-center justify-center gap-3 py-24 text-muted-foreground">
        <LoaderCircle className="size-5 animate-spin" />
        {JOB_COPY.loading}
      </div>
    );
  }

  const presentation = jobPresentation(job.status, job.stage);
  const StatusIcon =
    presentation.tone === "success"
      ? CheckCircle2
      : presentation.tone === "error"
        ? AlertCircle
        : presentation.tone === "pending"
          ? Clock3
          : LoaderCircle;

  return (
    <div className="space-y-6">
      {requestError && (
        <ErrorFeedbackPanel
          feedback={requestError}
          onRetry={() => {
            setRequestError(null);
            setRefreshKey((value) => value + 1);
          }}
        />
      )}
      <div className="rounded-3xl border bg-card p-6 sm:p-9">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-medium tracking-[0.18em] text-primary">
              {presentation.eyebrow}
            </p>
            <h1 className="mt-3 font-display text-3xl font-bold">
              {presentation.title}
            </h1>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              {presentation.description}
            </p>
          </div>
          <div
            className={`flex size-14 shrink-0 items-center justify-center rounded-full ${
              presentation.tone === "error"
                ? "bg-destructive/10 text-destructive"
                : "bg-primary/10 text-primary"
            }`}
          >
            <StatusIcon
              className={`size-7 ${
                presentation.tone === "active" ? "animate-spin" : ""
              }`}
            />
          </div>
        </div>

        <div className="mt-8 h-2 overflow-hidden rounded-full bg-muted">
          <div
            className={`h-full rounded-full transition-[width] ${
              presentation.tone === "error" ? "bg-destructive" : "bg-primary"
            }`}
            style={{ width: `${job.progress}%` }}
          />
        </div>
        <div className="mt-2 flex items-start justify-between gap-4 text-xs text-muted-foreground">
          <span>
            {JOB_COPY.currentProgress}：{presentation.progressLabel}
          </span>
          <span>{job.progress}%</span>
        </div>

        <dl className="mt-8 grid gap-4 sm:grid-cols-2">
          <div className="rounded-xl bg-muted/65 p-4">
            <dt className="flex items-center gap-2 text-xs text-muted-foreground">
              <FileVideo className="size-4" />
              {JOB_COPY.submittedVideo}
            </dt>
            <dd className="mt-2 truncate text-sm font-medium">
              {job.original_video_name}
            </dd>
            <dd className="mt-1 text-xs text-muted-foreground">
              {formatBytes(job.video_size_bytes)}
            </dd>
          </div>
          <div className="rounded-xl bg-muted/65 p-4">
            <dt className="flex items-center gap-2 text-xs text-muted-foreground">
              <Hash className="size-4" />
              {JOB_COPY.taskId}
            </dt>
            <dd className="mt-2 break-all font-mono text-xs">{job.id}</dd>
            <dd className="mt-1 text-xs text-muted-foreground">
              {JOB_COPY.lyricsSource}：
              {job.lyrics_source === "file"
                ? JOB_COPY.textFileLyrics
                : JOB_COPY.pastedLyrics}
            </dd>
          </div>
        </dl>

        {job.status === "FAILED" && (
          <div className="mt-6">
            <ErrorFeedbackPanel
              feedback={jobFailureFeedback(
                job.error_code,
                job.stage,
                job.error_message,
                job.id,
              )}
            />
          </div>
        )}

        {(job.status === "TRANSCRIBED" ||
          job.status === "LYRICS_PROCESSED" ||
          job.status === "ALIGNED" ||
          job.status === "SUBTITLE_GENERATED" ||
          job.status === "COMPLETED") && (
          <div className="mt-6 flex flex-wrap gap-3">
            <a
              href={transcriptUrl(job.id)}
              className="focus-ring inline-flex items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm font-semibold transition hover:bg-muted"
            >
              <Download className="size-4" />
              {JOB_COPY.downloadTranscript}
            </a>
            {(job.status === "LYRICS_PROCESSED" ||
              job.status === "ALIGNED" ||
              job.status === "SUBTITLE_GENERATED" ||
              job.status === "COMPLETED") && (
              <a
                href={processedLyricsUrl(job.id)}
                className="focus-ring inline-flex items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm font-semibold transition hover:bg-muted"
              >
                <Download className="size-4" />
                {JOB_COPY.downloadLyrics}
              </a>
            )}
            {(job.status === "ALIGNED" ||
              job.status === "SUBTITLE_GENERATED" ||
              job.status === "COMPLETED") && (
              <a
                href={timelineUrl(job.id)}
                className="focus-ring inline-flex items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm font-semibold transition hover:bg-muted"
              >
                <Download className="size-4" />
                {JOB_COPY.downloadTimeline}
              </a>
            )}
            {(job.status === "SUBTITLE_GENERATED" ||
              job.status === "COMPLETED") && (
              <a
                href={subtitleUrl(job.id)}
                className="focus-ring inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground"
              >
                <Download className="size-4" />
                {JOB_COPY.downloadSubtitle}
              </a>
            )}
          </div>
        )}

        {job.status === "COMPLETED" && <ResultVideos job={job} />}
      </div>

      {job.status === "AWAITING_REVIEW" && (
        <TimelineReview
          jobId={job.id}
          onRenderQueued={() => setRefreshKey((value) => value + 1)}
        />
      )}

      {(job.status === "COMPLETED" ||
        job.status === "SUBTITLE_GENERATED") && (
        <>
          <button
            type="button"
            aria-expanded={reviewOpen}
            onClick={() => setReviewOpen((open) => !open)}
            className="focus-ring inline-flex items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm font-semibold transition hover:bg-muted"
          >
            <Clapperboard className="size-4" />
            {reviewOpen ? REVIEW_COPY.close : REVIEW_COPY.openFromCompleted}
          </button>
          {reviewOpen && (
            <TimelineReview
              key={`review-${job.updated_at}`}
              jobId={job.id}
              onRenderQueued={() => {
                setReviewOpen(false);
                setRefreshKey((value) => value + 1);
              }}
            />
          )}
        </>
      )}

      {/* the review has its own style section, next to a live preview */}
      {!reviewOpen &&
        (job.status === "COMPLETED" ||
          job.status === "SUBTITLE_GENERATED") && (
        <RestylePanel
          key={job.updated_at}
          jobId={job.id}
          onQueued={() => setRefreshKey((value) => value + 1)}
        />
      )}

      <Link
        href="/"
        className="focus-ring inline-flex rounded-lg border bg-card px-4 py-2.5 text-sm font-medium transition hover:bg-muted"
      >
        {JOB_COPY.createAnother}
      </Link>
    </div>
  );
}
