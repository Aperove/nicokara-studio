import { JobStatus } from "@/components/job-status";
import { PAGE_WIDTH } from "@/lib/layout";

export default async function JobPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;

  return (
    <main className={`${PAGE_WIDTH} py-8`}>
      <JobStatus jobId={jobId} />
    </main>
  );
}

