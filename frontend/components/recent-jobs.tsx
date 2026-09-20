"use client";

import { RefreshCw } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { jobPresentation, type JobTone } from "@/lib/job-presentation";
import { JOBS_COPY } from "@/lib/ui-copy";
import { listJobs } from "@/services/api";
import type { Job } from "@/types/job";

const ACTIVE_POLL_MS = 3_000;
const IDLE_POLL_MS = 15_000;

const TONE_CLASSES: Record<JobTone, string> = {
  success: "bg-success/15 text-success",
  error: "bg-destructive/15 text-destructive",
  pending: "bg-warning/15 text-warning",
  active: "bg-primary/10 text-primary",
};

export function relativeTime(iso: string, now: number): string {
  const minutes = Math.floor((now - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return JOBS_COPY.justNow;
  if (minutes < 60) return JOBS_COPY.minutesAgo(minutes);
  if (minutes < 60 * 24) return JOBS_COPY.hoursAgo(Math.floor(minutes / 60));
  return JOBS_COPY.daysAgo(Math.floor(minutes / (60 * 24)));
}

export function RecentJobs() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function load() {
      let delay = IDLE_POLL_MS;
      try {
        const value = await listJobs(20);
        if (!active) return;
        setJobs(value);
        setFailed(false);
        setNow(Date.now());
        if (value.some((job) => !jobPresentation(job.status, job.stage).terminal)) {
          delay = ACTIVE_POLL_MS;
        }
      } catch {
        if (!active) return;
        setFailed(true);
      }
      timer = setTimeout(load, delay);
    }

    load();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [tick]);

  return (
    <section aria-labelledby="recent-jobs-heading">
      <div className="mb-3 flex items-center justify-between">
        <h2 id="recent-jobs-heading" className="text-lg font-semibold">
          {JOBS_COPY.heading}
        </h2>
        <button
          type="button"
          onClick={refresh}
          aria-label={JOBS_COPY.refresh}
          title={JOBS_COPY.refresh}
          className="focus-ring rounded-lg border bg-card p-1.5 text-muted-foreground transition hover:bg-muted"
        >
          <RefreshCw className="size-4" />
        </button>
      </div>

      {failed && (
        <p className="mb-3 rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {JOBS_COPY.loadFailed}
        </p>
      )}

      {jobs !== null && jobs.length === 0 && !failed && (
        <p className="rounded-xl border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
          {JOBS_COPY.empty}
        </p>
      )}

      <ul className="space-y-2">
        {(jobs ?? []).map((job) => {
          const presentation = jobPresentation(job.status, job.stage);
          return (
            <li key={job.id}>
              <Link
                href={`/jobs/${job.id}`}
                className="focus-ring block rounded-xl border bg-card px-3.5 py-3 transition hover:border-primary/50 hover:bg-accent/30"
              >
                <div className="flex items-start justify-between gap-3">
                  <p className="min-w-0 flex-1 truncate text-sm font-medium">
                    {job.original_video_name}
                  </p>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[presentation.tone]}`}
                  >
                    {presentation.progressLabel}
                  </span>
                </div>
                {!presentation.terminal && (
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary transition-[width]"
                      style={{ width: `${job.progress}%` }}
                    />
                  </div>
                )}
                <p className="mt-1.5 text-xs text-muted-foreground">
                  {relativeTime(job.updated_at, now)}
                </p>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
