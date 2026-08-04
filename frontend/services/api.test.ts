import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("result video URLs", () => {
  it("uses the deployed reverse proxy by default", async () => {
    const api = await import("./api");

    expect(api.resultVideoUrl("job-1")).toBe(
      "/api/v1/jobs/job-1/result",
    );
    expect(api.downloadVideoUrl("job-1")).toBe(
      "/api/v1/jobs/job-1/download",
    );
  });
});

describe("getJob", () => {
  it("returns detailed guidance when the task has expired", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "任务不存在" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const { ApiRequestError, getJob } = await import("./api");

    try {
      await getJob("missing-job");
      expect.fail("getJob should reject a missing task");
    } catch (reason) {
      expect(reason).toBeInstanceOf(ApiRequestError);
      expect((reason as InstanceType<typeof ApiRequestError>).feedback).toMatchObject({
        title: "本地任务不存在或已清理",
        retryable: false,
      });
    }
  });

  it("returns local recovery steps when the frontend cannot reach the backend", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("Bad Gateway", {
          status: 502,
          statusText: "Bad Gateway",
        }),
      ),
    );
    const { ApiRequestError, getJob } = await import("./api");

    try {
      await getJob("job-1");
      expect.fail("getJob should reject a gateway failure");
    } catch (reason) {
      expect(reason).toBeInstanceOf(ApiRequestError);
      const feedback = (reason as InstanceType<typeof ApiRequestError>).feedback;
      expect(feedback.title).toBe("本地前后端连接异常");
      expect(feedback.solutions.join(" ")).toContain("Docker Compose");
    }
  });

  it("returns recoverable local guidance when the request cannot connect", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    const { ApiRequestError, getJob } = await import("./api");

    try {
      await getJob("job-1");
      expect.fail("getJob should reject a network failure");
    } catch (reason) {
      expect(reason).toBeInstanceOf(ApiRequestError);
      expect((reason as InstanceType<typeof ApiRequestError>).feedback).toMatchObject({
        title: "无法连接本地处理服务",
        retryable: true,
      });
    }
  });
});
