import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ErrorFeedbackPanel } from "./error-feedback";

describe("ErrorFeedbackPanel", () => {
  it("renders the problem, solutions, and support details", () => {
    const html = renderToStaticMarkup(
      <ErrorFeedbackPanel
        feedback={{
          title: "本地前后端连接异常",
          description: "页面暂时无法连接本机后端。",
          solutions: ["确认 Docker Compose 已启动。", "检查本地端口配置。"],
          technicalDetails: ["HTTP 状态码：502", "任务 ID：job-123"],
          retryable: true,
        }}
        onRetry={() => undefined}
      />,
    );

    expect(html).toContain('role="alert"');
    expect(html).toContain("本地前后端连接异常");
    expect(html).toContain("本地处理建议");
    expect(html).toContain("确认 Docker Compose 已启动。");
    expect(html).toContain("诊断信息");
    expect(html).toContain("任务 ID：job-123");
    expect(html).toContain("重新检查");
  });
});
