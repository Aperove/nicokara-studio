export type ErrorFeedback = {
  title: string;
  description: string;
  solutions: string[];
  technicalDetails: string[];
  retryable: boolean;
};

export type ErrorContext = "upload" | "job";

export type ValidationErrorCode =
  | "video_required"
  | "lyrics_required"
  | "lyrics_source_conflict"
  | "invalid_video_type"
  | "video_too_large";

const VALIDATION_ERRORS: Record<ValidationErrorCode, ErrorFeedback> = {
  video_required: {
    title: "尚未选择视频",
    description: "生成任务需要一个包含画面和音轨的 MP4 视频。",
    solutions: ["点击“上传原版 MV”并选择视频文件。"],
    technicalDetails: [],
    retryable: false,
  },
  lyrics_required: {
    title: "尚未提供歌词",
    description: "当前 Studio 版本需要歌词才能生成逐字变色字幕。",
    solutions: [
      "在歌词输入框中粘贴歌词，或选择一个 UTF-8 编码的 TXT 文件。",
      "每句歌词单独一行，并尽量与视频中的演唱顺序一致。",
    ],
    technicalDetails: [],
    retryable: false,
  },
  lyrics_source_conflict: {
    title: "歌词来源重复",
    description: "粘贴歌词和 TXT 文件不能同时提交。",
    solutions: ["保留其中一种歌词来源，移除另一种后重新提交。"],
    technicalDetails: [],
    retryable: false,
  },
  invalid_video_type: {
    title: "视频格式不受支持",
    description: "Studio 当前只接受标准 MP4 容器的视频。",
    solutions: [
      "使用视频转换工具将素材重新编码为标准 MP4 后再上传。",
      "不要仅修改文件扩展名，程序会检查文件内部的 MP4 标识。",
    ],
    technicalDetails: [],
    retryable: false,
  },
  video_too_large: {
    title: "视频文件过大",
    description: "Studio 默认允许导入的视频最大为 1 GB。",
    solutions: [
      "降低视频分辨率或码率，将文件压缩到 1 GB 以内。",
      "裁剪不需要的片头、片尾后重新上传。",
    ],
    technicalDetails: [],
    retryable: false,
  },
};

function retryDelay(seconds?: number): string {
  if (!seconds || seconds <= 0) return "稍后";
  if (seconds < 60) return `${seconds} 秒后`;
  return `${Math.ceil(seconds / 60)} 分钟后`;
}

function httpDetails(status: number, detail?: string | null): string[] {
  const details = [`HTTP 状态码：${status}`];
  if (detail?.trim()) details.push(`本地程序信息：${detail.trim()}`);
  return details;
}

export function validationErrorFeedback(
  code: ValidationErrorCode,
): ErrorFeedback {
  return VALIDATION_ERRORS[code];
}

export function networkErrorFeedback(context: ErrorContext): ErrorFeedback {
  return {
    title: "无法连接本地处理服务",
    description:
      context === "upload"
        ? "素材尚未导入本机。页面无法访问本地 Nicokara 后端，通常是后端未启动、Docker 容器未运行或端口配置不一致。"
        : "暂时无法读取本地任务状态。任务文件仍保存在本机，页面会自动尝试恢复连接。",
    solutions: [
      "确认 Nicokara 后端或 Docker Compose 已启动。",
      "Docker 用户可运行 docker compose ps，并使用 docker compose logs backend 查看错误日志。",
      context === "upload"
        ? "直接运行后端时，确认 http://127.0.0.1:8100/health 可以访问，并检查前端本地代理端口。"
        : "不要删除任务目录；恢复本地服务后，使用当前任务页面和任务 ID 继续查询。",
    ],
    technicalDetails: ["页面未从本地 API 收到有效的 HTTP 响应。"],
    retryable: true,
  };
}

export function httpErrorFeedback(
  context: ErrorContext,
  status: number,
  detail?: string | null,
  retryAfterSeconds?: number,
): ErrorFeedback {
  const technicalDetails = httpDetails(status, detail);

  if (status === 413) {
    const detailText = detail?.trim() ?? "";
    const rejectedByStudioLimit = [
      "视频文件超过大小限制",
      "歌词文件超过大小限制",
      "歌词文本超过大小限制",
    ].some((message) => detailText.includes(message));

    if (!rejectedByStudioLimit) {
      return {
        title: "本地开发代理拒绝了上传",
        description:
          "上传请求尚未进入 Studio 后端，本地前端开发服务先返回了请求体过大的错误。文件实际大小可能仍在 Studio 允许范围内。",
        solutions: [
          "确认 http://127.0.0.1:8100/health 可以访问。",
          "重启 Studio 前端开发服务，使 /api 本地代理配置生效后重新导入。",
          "如果修改过后端端口，请将 NICOKARA_DEV_API_ORIGIN 设置为对应的本地地址。",
        ],
        technicalDetails,
        retryable: true,
      };
    }

    return {
      title: "文件超过本地处理限制",
      description: "Studio 拒绝导入当前素材，因为视频或歌词文件超过本地配置的大小限制。",
      solutions: [
        "将视频压缩到 1 GB 以内后重新导入。",
        "歌词 TXT 文件应小于 1 MB，并使用 UTF-8 编码。",
        "如需处理更大的本地素材，可调整 .env 中的 NICOKARA_MAX_VIDEO_BYTES 或 NICOKARA_MAX_LYRICS_BYTES，重启本地服务后再试。",
      ],
      technicalDetails,
      retryable: false,
    };
  }

  if (status === 415) {
    return {
      title: "素材格式不正确",
      description: "Studio 检测到视频不是有效 MP4，或歌词文件不是 UTF-8 文本。",
      solutions: [
        "重新编码视频为 MP4，不要只修改扩展名。",
        "将歌词文件另存为 UTF-8 编码的 TXT 文件。",
      ],
      technicalDetails,
      retryable: false,
    };
  }

  if (status === 422 || status === 400) {
    return {
      title: "提交内容未通过校验",
      description: "本地程序无法使用当前视频、歌词或表单参数创建任务。",
      solutions: [
        "确认选择了 MP4 视频，并且只使用粘贴歌词或 TXT 文件中的一种。",
        "重新选择素材后提交；如果持续失败，请展开下方诊断信息并检查本地后端终端日志。",
      ],
      technicalDetails,
      retryable: false,
    };
  }

  if (status === 429) {
    const delay = retryDelay(retryAfterSeconds);
    return {
      title: "本地提交频率受限",
      description: `本地服务已触发任务创建频率限制，请在${delay}再次提交。`,
      solutions: [
        `等待至少${delay}再创建任务，避免连续重复点击提交。`,
        "Studio 默认关闭提交频率限制；出现此提示时，请确认前端没有连接到 Cloud 后端。",
        "如果本地 .env 显式设置了 NICOKARA_MAX_UPLOADS_PER_HOUR，请改为 0 并重启 Studio 后端。",
      ],
      technicalDetails,
      retryable: true,
    };
  }

  if (status === 503 && detail?.toLowerCase().includes("queue")) {
    const delay = retryDelay(retryAfterSeconds);
    return {
      title: "本地任务队列已满",
      description: `本机已有较多任务等待处理，请在${delay}重新提交。`,
      solutions: [
        `等待约${delay}，让当前任务处理完成后再提交。`,
        "不要重复导入同一素材；确需扩大队列时，可调整 NICOKARA_MAX_PENDING_JOBS 后重启本地服务。",
      ],
      technicalDetails,
      retryable: true,
    };
  }

  if (status === 502 || status === 504) {
    return {
      title: "本地前后端连接异常",
      description: "当前页面没有及时连接到本机后端，通常是 Docker Compose 未启动、后端重启或本地代理端口不一致。",
      solutions: [
        "确认 Docker Compose 中 frontend 和 backend 均处于运行状态。",
        "直接运行时，确认后端监听 127.0.0.1:8100，并检查 NICOKARA_DEV_API_ORIGIN 是否指向正确端口。",
        "查看启动终端或运行 docker compose logs backend，修复错误后点击重新检查。",
      ],
      technicalDetails,
      retryable: true,
    };
  }

  if (status === 503) {
    return {
      title: "本地处理服务暂时不可用",
      description: "本地后端可能正在启动、重新加载模型，或当前没有足够内存和磁盘空间处理任务。",
      solutions: [
        "等待本地服务和模型加载完成后重新尝试。",
        "检查 Docker Desktop 或启动终端中的服务状态、内存占用和可用磁盘空间。",
      ],
      technicalDetails,
      retryable: true,
    };
  }

  if (status === 404) {
    return {
      title: context === "job" ? "本地任务不存在或已清理" : "本地 API 地址不正确",
      description:
        context === "job"
          ? "本地数据库找不到这个任务。任务可能已被自动清理、数据目录发生变化，或任务地址不完整。"
          : "当前页面没有找到任务创建接口，通常是前端 API 路径或本地代理配置不一致。",
      solutions:
        context === "job"
          ? ["返回上传页创建新任务。", "核对任务链接是否完整。"]
          : [
              "刷新页面后重试。",
              "确认前端使用 /api/v1，并检查 NICOKARA_DEV_API_ORIGIN 与本地后端端口。",
            ],
      technicalDetails,
      retryable: false,
    };
  }

  if (status === 409) {
    return {
      title: "任务结果尚未准备完成",
      description: "本地程序仍在处理任务，当前文件暂时不能下载。",
      solutions: ["返回任务状态页等待处理完成后再下载。"],
      technicalDetails,
      retryable: true,
    };
  }

  if (status === 410) {
    return {
      title: "任务文件已被清理",
      description: "任务记录仍存在，但本地任务目录已经过期、被移动或被清理。",
      solutions: ["重新上传原视频和歌词创建新任务。"],
      technicalDetails,
      retryable: false,
    };
  }

  return {
    title: status >= 500 ? "本地处理请求失败" : "请求未能完成",
    description:
      status >= 500
        ? "本地后端发生内部错误，当前请求没有正常完成。"
        : "本地程序拒绝了当前请求，请检查提交内容或任务地址。",
    solutions: [
      "稍后重试一次。",
      "如果问题持续出现，请展开诊断信息，并在启动终端或 docker compose logs backend 中查找相同时间的错误。",
    ],
    technicalDetails,
    retryable: status >= 500,
  };
}

type JobFailureDefinition = Omit<
  ErrorFeedback,
  "technicalDetails" | "retryable"
>;

const JOB_FAILURES: Record<string, JobFailureDefinition> = {
  VOCAL_REMOVAL_FAILED: {
    title: "人声分离失败",
    description: "本地程序无法使用 MDX 模型生成伴奏音轨，当前任务不能继续渲染。",
    solutions: [
      "重新上传并选择 ON VOCAL，可跳过人声分离继续制作。",
      "确认源视频包含正常的立体声音轨，而不是损坏或无声素材。",
      "检查本地模型目录中的 MDX 文件、可用磁盘空间，以及启动终端或 docker compose logs backend。",
    ],
  },
  AUDIO_EXTRACTION_FAILED: {
    title: "音频提取失败",
    description: "本地 FFmpeg 无法从视频中提取可供分析的音轨。",
    solutions: [
      "确认视频可以正常播放且确实包含音频。",
      "将视频重新编码为 H.264 视频加 AAC 音频的标准 MP4 后再上传。",
      "在终端运行 ffmpeg -version 确认可用，并根据任务 ID 检查本地后端日志。",
    ],
  },
  TRANSCRIPTION_FAILED: {
    title: "日语语音识别失败",
    description: "本地 Whisper 未能完成转录，后续歌词对齐无法继续。",
    solutions: [
      "确认视频音轨清晰且不是完全静音。",
      "尝试使用较短的素材，或关闭占用大量内存的其他本地程序。",
      "检查 NICOKARA_WHISPER_MODEL 指向的本地模型、可用内存和后端日志。",
    ],
  },
  LYRIC_PROCESSING_FAILED: {
    title: "歌词处理失败",
    description: "本地程序无法完成歌词分句、日语读音或 Ruby 注音处理。",
    solutions: [
      "移除歌词中的网页标签、异常控制字符和大段空白后重试。",
      "确保 TXT 文件使用 UTF-8 编码，并让每句歌词单独一行。",
      "根据任务 ID 检查本地后端中的歌词处理与 DeepSeek 降级日志。",
    ],
  },
  ALIGNMENT_FAILED: {
    title: "歌词时间轴对齐失败",
    description: "歌词内容与识别到的演唱音频差异过大，无法生成可靠时间轴。",
    solutions: [
      "确保歌词与视频中的实际演唱内容一致，不要混入翻译、时间标签或说明文字。",
      "每句歌词单独一行，并保持与演唱顺序一致。",
      "删去视频中未演唱的歌词，或补齐明显缺失的歌词后重试。",
    ],
  },
  SUBTITLE_GENERATION_FAILED: {
    title: "ASS 字幕生成失败",
    description: "时间轴已处理，但本地程序无法生成可烧录的 ASS 字幕。",
    solutions: [
      "将过长歌词拆成多行，并移除特殊控制字符后重试。",
      "检查本地 Noto CJK 日文字体是否可用，并根据任务 ID 查看字幕生成日志。",
    ],
  },
  VIDEO_RENDERING_FAILED: {
    title: "最终视频渲染失败",
    description: "字幕已经生成，但 FFmpeg 没有成功输出最终 MP4。",
    solutions: [
      "关闭占用 CPU、GPU 或内存的其他程序，确认输出磁盘有足够空间后重试。",
      "尝试使用分辨率或码率更低的源视频。",
      "运行 ffmpeg -version，并检查本地 FFmpeg/libass、日文字体和后端日志。",
    ],
  },
  SERVICE_RESTARTED: {
    title: "任务因本地服务重启而中断",
    description: "处理期间本地后端、终端或 Docker 容器发生重启，当前任务无法从中断位置继续。",
    solutions: [
      "返回上传页重新上传视频和歌词，创建一个新任务。",
      "确认本地后端或 Docker 容器已经稳定运行后再提交。",
      "处理任务时不要关闭启动终端、Docker Desktop 或本地处理服务。",
    ],
  },
};

export function jobFailureFeedback(
  errorCode: string | null,
  stage: string,
  serverMessage: string | null,
  jobId: string,
): ErrorFeedback {
  const definition =
    (errorCode ? JOB_FAILURES[errorCode] : undefined) ?? {
      title: "本地任务处理失败",
      description: "本地程序未能完成当前任务，具体原因需要结合本机任务日志确认。",
      solutions: [
        "检查素材后重新创建一次任务。",
        "如果问题重复出现，请使用任务 ID、错误代码和失败阶段在本地后端日志中定位原因。",
      ],
    };
  const technicalDetails = [`任务 ID：${jobId}`, `失败阶段：${stage}`];
  if (errorCode) technicalDetails.push(`错误代码：${errorCode}`);
  if (serverMessage?.trim()) {
    technicalDetails.push(`本地程序信息：${serverMessage.trim()}`);
  }

  return {
    ...definition,
    technicalDetails,
    retryable: false,
  };
}
