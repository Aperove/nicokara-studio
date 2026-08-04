import { describe, expect, it } from "vitest";

import { HOME_COPY, JOB_COPY, UPLOAD_COPY } from "./ui-copy";

describe("Studio local interface copy", () => {
  it("describes local processing without cloud deployment wording", () => {
    const copy = JSON.stringify({ HOME_COPY, JOB_COPY, UPLOAD_COPY });

    expect(copy).not.toContain("电脑性能");
    expect(copy).not.toContain("最快约");
    expect(copy).not.toContain("服务器");
    expect(HOME_COPY.introduction).toContain("本机");
    expect(UPLOAD_COPY.footer).toContain("本地处理服务");
  });

  it("labels transfer progress as importing into the local workspace", () => {
    expect(UPLOAD_COPY.uploadProgressTitle).toBe("正在导入素材到本机");
    expect(UPLOAD_COPY.uploadingButton).toBe("正在导入…");
    expect(UPLOAD_COPY.uploadProgressDescription).toContain("任务状态页");
  });

  it("uses the requested vocal labels and lyrics guidance", () => {
    expect(UPLOAD_COPY.vocalOnLabel).toBe("ON VOCAL");
    expect(UPLOAD_COPY.vocalOffLabel).toBe("OFF VOCAL");
    expect(UPLOAD_COPY.offVocalHint).toContain("MDX");
    expect(UPLOAD_COPY.offVocalHint).not.toContain("相位抵消");
    expect(UPLOAD_COPY.lyricsHint).toBe(
      "每句歌词需单独成行（不然会卡出屏幕QAQ）",
    );
  });

  it("uses clear task and result labels", () => {
    expect(JOB_COPY.loading).toBe("正在读取本地任务状态…");
    expect(JOB_COPY.currentProgress).toBe("当前进度");
    expect(JOB_COPY.resultHeading).toBe("生成结果");
    expect(JOB_COPY.downloadVideo).toBe("下载生成的视频");
    expect(JOB_COPY.downloadTranscript).toBe("下载歌声识别数据");
    expect(JOB_COPY.downloadLyrics).toBe("下载歌词处理数据");
    expect(JOB_COPY.downloadTimeline).toBe("下载歌词时间轴");
    expect(JOB_COPY.downloadSubtitle).toBe("下载字幕文件");
  });
});
