import { describe, expect, it } from "vitest";

describe("jobPresentation", () => {
  it("maps Phase 3 and 4 stages to user-facing states", async () => {
    let jobPresentation: (
      status: string,
      stage: string,
    ) => {
      eyebrow: string;
      title: string;
      description: string;
      progressLabel: string;
      terminal: boolean;
      tone: string;
    };
    try {
      ({ jobPresentation } = await import("./job-presentation"));
    } catch {
      expect.fail("Phase 3 job presentation is not implemented");
    }

    expect(jobPresentation("PROCESSING", "EXTRACTING_AUDIO")).toMatchObject({
      eyebrow: "音频准备",
      title: "正在准备视频音轨",
      progressLabel: "提取音频",
      terminal: false,
      tone: "active",
    });
    expect(jobPresentation("PROCESSING", "REMOVING_VOCALS")).toMatchObject({
      eyebrow: "人声处理",
      title: "正在生成伴奏音轨",
      progressLabel: "分离人声",
      terminal: false,
      tone: "active",
    });
    expect(jobPresentation("UPLOADED", "UPLOAD_COMPLETE")).toMatchObject({
      eyebrow: "等待处理",
      title: "任务正在排队",
      progressLabel: "等待处理",
      terminal: false,
      tone: "pending",
    });
    expect(jobPresentation("FAILED", "REMOVING_VOCALS")).toMatchObject({
      title: "人声分离失败",
      terminal: true,
      tone: "error",
    });
    expect(jobPresentation("PROCESSING", "TRANSCRIBING")).toMatchObject({
      title: "正在识别歌声",
      progressLabel: "识别歌声",
      terminal: false,
      tone: "active",
    });
    expect(jobPresentation("TRANSCRIBED", "TRANSCRIPTION_COMPLETE")).toMatchObject({
      title: "歌声识别已完成",
      progressLabel: "识别完成",
      terminal: true,
      tone: "success",
    });
    expect(jobPresentation("PROCESSING", "PROCESSING_LYRICS")).toMatchObject({
      title: "正在整理歌词与注音",
      progressLabel: "处理歌词",
      terminal: false,
      tone: "active",
    });
    expect(
      jobPresentation("LYRICS_PROCESSED", "LYRIC_PROCESSING_COMPLETE"),
    ).toMatchObject({
      title: "歌词与注音已处理",
      progressLabel: "歌词处理完成",
      terminal: true,
      tone: "success",
    });
    expect(jobPresentation("FAILED", "TRANSCRIBING")).toMatchObject({
      title: "歌声识别失败",
      terminal: true,
      tone: "error",
    });
    expect(jobPresentation("PROCESSING", "ALIGNING")).toMatchObject({
      title: "正在匹配歌词时间",
      progressLabel: "对齐时间",
      terminal: false,
      tone: "active",
    });
    expect(jobPresentation("ALIGNED", "ALIGNMENT_COMPLETE")).toMatchObject({
      title: "歌词时间轴已完成",
      progressLabel: "时间轴完成",
      terminal: true,
      tone: "success",
    });
    expect(jobPresentation("FAILED", "ALIGNING")).toMatchObject({
      title: "歌词时间轴对齐失败",
      terminal: true,
      tone: "error",
    });
    expect(jobPresentation("PROCESSING", "GENERATING_SUBTITLE")).toMatchObject({
      title: "正在生成逐字高亮字幕",
      progressLabel: "生成字幕",
      terminal: false,
      tone: "active",
    });
    expect(
      jobPresentation("SUBTITLE_GENERATED", "SUBTITLE_GENERATION_COMPLETE"),
    ).toMatchObject({
      title: "字幕文件已生成",
      progressLabel: "字幕生成完成",
      terminal: true,
      tone: "success",
    });
    expect(jobPresentation("FAILED", "GENERATING_SUBTITLE")).toMatchObject({
      title: "ASS 字幕生成失败",
      terminal: true,
      tone: "error",
    });
    expect(jobPresentation("PROCESSING", "RENDERING_VIDEO")).toMatchObject({
      title: "正在合成最终视频",
      progressLabel: "合成视频",
      terminal: false,
      tone: "active",
    });
    expect(
      jobPresentation("COMPLETED", "VIDEO_RENDERING_COMPLETE"),
    ).toMatchObject({
      title: "ニコカラ视频已生成",
      progressLabel: "处理完成",
      terminal: true,
      tone: "success",
    });
    expect(jobPresentation("FAILED", "RENDERING_VIDEO")).toMatchObject({
      title: "视频渲染失败",
      terminal: true,
      tone: "error",
    });
  });

  it("describes failures as local processing problems", async () => {
    const { jobPresentation } = await import("./job-presentation");

    const presentation = jobPresentation("FAILED", "TRANSCRIBING");

    expect(presentation.description).toContain("本机");
    expect(presentation.description).not.toContain("服务器");
  });

  it("explains active stages without exposing internal stage codes", async () => {
    const { jobPresentation } = await import("./job-presentation");

    const presentation = jobPresentation("PROCESSING", "RENDERING_VIDEO");

    expect(presentation.description).toContain("本机");
    expect(presentation.description).toContain("耗时较长");
    expect(presentation.description).not.toContain("FFmpeg");
    expect(presentation.progressLabel).not.toContain("RENDERING_VIDEO");
  });

  it("uses the same vocal mode label as the upload form", async () => {
    const { jobPresentation } = await import("./job-presentation");

    const presentation = jobPresentation("PROCESSING", "REMOVING_VOCALS");

    expect(presentation.description).toContain("OFF VOCAL");
  });

  it("keeps every active stage in the Studio local context", async () => {
    const { jobPresentation } = await import("./job-presentation");
    const stages = [
      "UPLOAD_COMPLETE",
      "EXTRACTING_AUDIO",
      "REMOVING_VOCALS",
      "TRANSCRIBING",
      "PROCESSING_LYRICS",
      "ALIGNING",
      "GENERATING_SUBTITLE",
      "RENDERING_VIDEO",
    ];
    const copy = JSON.stringify(
      stages.map((stage) => jobPresentation("PROCESSING", stage)),
    );

    expect(copy).not.toContain("服务器");
    expect(copy).toContain("本机");
  });
});
