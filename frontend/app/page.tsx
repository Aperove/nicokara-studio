import { CreateJobForm } from "@/components/create-job-form";
import { RecentJobs } from "@/components/recent-jobs";
import { CREATE_COPY, HOME_COPY } from "@/lib/ui-copy";

export default function Home() {
  return (
    <main className="mx-auto max-w-6xl px-5 py-8 sm:px-8 sm:py-10">
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_21rem] lg:items-start">
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
          <CreateJobForm />
        </section>

        <aside className="lg:sticky lg:top-6">
          <RecentJobs />
        </aside>
      </div>

      <footer
        aria-label="作者信息"
        className="mt-10 border-t pt-4 text-xs leading-6 text-muted-foreground"
      >
        <p className="flex flex-wrap gap-x-5">
          <span>qq：{HOME_COPY.author.qq}</span>
          <span>bilibili：{HOME_COPY.author.bilibili}</span>
          <span>小红书：{HOME_COPY.author.xiaohongshu}</span>
        </p>
        <p>{HOME_COPY.author.message}</p>
      </footer>
    </main>
  );
}
