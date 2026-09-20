"use client";

import { useEffect, useState } from "react";

import { CreateJobForm } from "@/components/create-job-form";
import { RecentJobs } from "@/components/recent-jobs";
import { CREATE_COPY, HOME_COPY } from "@/lib/ui-copy";
import { getCapabilities, type Capabilities } from "@/services/api";

// What a local installation offers; a shared server may switch parts off.
const LOCAL: Capabilities = { video_link_hosts: ["youtube.com"], job_listing: true };

export function HomeWorkspace() {
  const [capabilities, setCapabilities] = useState<Capabilities>(LOCAL);

  useEffect(() => {
    let active = true;
    getCapabilities()
      .then((value) => {
        if (active) setCapabilities(value);
      })
      .catch(() => {
        // an older backend: everything is on
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div
      className={
        capabilities.job_listing
          ? "grid gap-8 lg:grid-cols-[minmax(0,1fr)_24rem] lg:items-start"
          : ""
      }
    >
      <section
        aria-labelledby="create-heading"
        className="rounded-2xl border bg-card/92 p-5 sm:p-7"
      >
        <h1 id="create-heading" className="font-display text-2xl font-bold">
          {CREATE_COPY.heading}
        </h1>
        <p className="mb-6 mt-1.5 text-sm text-muted-foreground">
          {HOME_COPY.introduction}
        </p>
        <CreateJobForm allowLinks={capabilities.video_link_hosts.length > 0} />
      </section>

      {capabilities.job_listing && (
        <aside className="lg:sticky lg:top-6">
          <RecentJobs />
        </aside>
      )}
    </div>
  );
}
