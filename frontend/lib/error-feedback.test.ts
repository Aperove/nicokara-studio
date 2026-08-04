import { describe, expect, it } from "vitest";

import {
  httpErrorFeedback,
  jobFailureFeedback,
  networkErrorFeedback,
  validationErrorFeedback,
} from "./error-feedback";

describe("validationErrorFeedback", () => {
  it("explains how to fix an invalid MP4 selection", () => {
    const feedback = validationErrorFeedback("invalid_video_type");

    expect(feedback.title).toBe("视频格式不受支持");
    expect(feedback.description).toContain("MP4");
    expect(feedback.solutions).toContain(
      "使用视频转换工具将素材重新编码为标准 MP4 后再上传。",
    );
  });
});

describe("networkErrorFeedback", () => {
  it("explains how to restore the local processing service", () => {
    const feedback = networkErrorFeedback("upload");

    expect(feedback.title).toBe("无法连接本地处理服务");
    expect(feedback.description).toContain("本机");
    expect(feedback.solutions.join(" ")).toContain("Docker Compose");
    expect(feedback.solutions.join(" ")).toContain("127.0.0.1:8100/health");
    expect(JSON.stringify(feedback)).not.toContain("管理员");
    expect(feedback.retryable).toBe(true);
  });
});

describe("httpErrorFeedback", () => {
  it("maps oversized uploads to an actionable size error", () => {
    const feedback = httpErrorFeedback("upload", 413, "视频文件超过大小限制");

    expect(feedback.title).toBe("文件超过本地处理限制");
    expect(feedback.solutions.join(" ")).toContain("1 GB");
    expect(feedback.solutions.join(" ")).toContain(
      "NICOKARA_MAX_VIDEO_BYTES",
    );
    expect(feedback.solutions.join(" ")).not.toContain("Nginx");
    expect(feedback.technicalDetails).toContain("HTTP 状态码：413");
  });

  it("does not misreport a development proxy rejection as a 1 GB file", () => {
    const feedback = httpErrorFeedback("upload", 413, "Payload Too Large");

    expect(feedback.title).toBe("本地开发代理拒绝了上传");
    expect(feedback.description).toContain("尚未进入 Studio 后端");
    expect(feedback.solutions.join(" ")).toContain("8100");
    expect(feedback.solutions.join(" ")).not.toContain("压缩到 1 GB");
  });

  it("shows the retry interval for rate limited uploads", () => {
    const feedback = httpErrorFeedback(
      "upload",
      429,
      "Upload rate limit exceeded. Try again later.",
      3600,
    );

    expect(feedback.title).toBe("本地提交频率受限");
    expect(feedback.description).toContain("60 分钟");
    expect(feedback.solutions.join(" ")).toContain("Studio 默认关闭");
    expect(feedback.solutions.join(" ")).toContain("Cloud 后端");
    expect(feedback.retryable).toBe(true);
  });

  it("explains that a full server queue should be retried later", () => {
    const feedback = httpErrorFeedback(
      "upload",
      503,
      "Processing queue is full. Try again later.",
      60,
    );

    expect(feedback.title).toBe("本地任务队列已满");
    expect(feedback.solutions.join(" ")).toContain("1 分钟");
    expect(feedback.solutions.join(" ")).toContain(
      "NICOKARA_MAX_PENDING_JOBS",
    );
    expect(feedback.retryable).toBe(true);
  });

  it("provides local proxy and backend checks for gateway failures", () => {
    const feedback = httpErrorFeedback("job", 502, "Bad Gateway");

    expect(feedback.title).toBe("本地前后端连接异常");
    expect(feedback.solutions.join(" ")).toContain("Docker Compose");
    expect(feedback.solutions.join(" ")).toContain("8100");
    expect(feedback.solutions.join(" ")).not.toContain("Nginx");
  });

  it("uses local troubleshooting for every supported HTTP error", () => {
    const feedback = [400, 404, 409, 410, 413, 415, 422, 429, 502, 503, 504].map(
      (status) => httpErrorFeedback("upload", status, null, 60),
    );
    const copy = JSON.stringify(feedback);

    expect(copy).not.toContain("管理员");
    expect(copy).not.toContain("Nginx");
    expect(copy).not.toContain("多人共用");
  });
});

describe("jobFailureFeedback", () => {
  it("offers the ON VOCAL fallback when MDX vocal removal fails", () => {
    const feedback = jobFailureFeedback(
      "VOCAL_REMOVAL_FAILED",
      "REMOVING_VOCALS",
      "Processing failed during vocal removal.",
      "job-123",
    );

    expect(feedback.title).toBe("人声分离失败");
    expect(feedback.solutions.join(" ")).toContain("ON VOCAL");
    expect(feedback.solutions.join(" ")).toContain("MDX");
    expect(feedback.solutions.join(" ")).toContain("本地模型");
    expect(feedback.technicalDetails).toContain("任务 ID：job-123");
  });

  it("explains how to improve lyrics alignment input", () => {
    const feedback = jobFailureFeedback(
      "ALIGNMENT_FAILED",
      "ALIGNING",
      null,
      "job-456",
    );

    expect(feedback.title).toBe("歌词时间轴对齐失败");
    expect(feedback.solutions.join(" ")).toContain("每句歌词单独一行");
    expect(feedback.solutions.join(" ")).toContain("演唱内容一致");
  });

  it("tells the user how to recover after a local service restart", () => {
    const feedback = jobFailureFeedback(
      "SERVICE_RESTARTED",
      "TRANSCRIBING",
      "Processing was interrupted by a service restart.",
      "job-789",
    );

    expect(feedback.title).toBe("任务因本地服务重启而中断");
    expect(feedback.solutions.join(" ")).toContain("重新上传");
    expect(feedback.solutions.join(" ")).toContain("Docker");
  });

  it("keeps unknown failures useful for support", () => {
    const feedback = jobFailureFeedback(
      "UNEXPECTED_FAILURE",
      "UNKNOWN_STAGE",
      "Unexpected processing failure.",
      "job-999",
    );

    expect(feedback.title).toBe("本地任务处理失败");
    expect(feedback.solutions.join(" ")).toContain("任务 ID");
    expect(feedback.technicalDetails).toContain("错误代码：UNEXPECTED_FAILURE");
  });

  it("keeps all known task failures free of cloud operations guidance", () => {
    const codes = [
      "VOCAL_REMOVAL_FAILED",
      "AUDIO_EXTRACTION_FAILED",
      "TRANSCRIPTION_FAILED",
      "LYRIC_PROCESSING_FAILED",
      "ALIGNMENT_FAILED",
      "SUBTITLE_GENERATION_FAILED",
      "VIDEO_RENDERING_FAILED",
      "SERVICE_RESTARTED",
    ];
    const copy = JSON.stringify(
      codes.map((code) => jobFailureFeedback(code, "PROCESSING", null, "job-local")),
    );

    expect(copy).not.toContain("管理员");
    expect(copy).not.toContain("服务器日志");
    expect(copy).toContain("本地");
  });
});
