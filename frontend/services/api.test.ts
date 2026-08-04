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
        title: "任务不存在或已过期",
        retryable: false,
      });
    }
  });

  it("returns gateway recovery steps for a deployed server outage", async () => {
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
      expect(feedback.title).toBe("服务器网关暂时不可用");
      expect(feedback.solutions.join(" ")).toContain("Nginx");
    }
  });

  it("returns recoverable server guidance when the request cannot connect", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    const { ApiRequestError, getJob } = await import("./api");

    try {
      await getJob("job-1");
      expect.fail("getJob should reject a network failure");
    } catch (reason) {
      expect(reason).toBeInstanceOf(ApiRequestError);
      expect((reason as InstanceType<typeof ApiRequestError>).feedback).toMatchObject({
        title: "无法连接服务器",
        retryable: true,
      });
    }
  });
});
