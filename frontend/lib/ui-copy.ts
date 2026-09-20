export const HOME_COPY = {
  introduction:
    "导入原版 MV 和日语歌词，本机将自动完成歌声识别、歌词同步、假名注音与视频合成。",
  steps: [
    {
      title: "提交素材",
      text: "选择 MP4 视频，并粘贴歌词或上传 UTF-8 TXT 文件。",
    },
    {
      title: "本地处理",
      text: "任务创建后，本机会依次完成音频分析、歌词同步和字幕生成。",
    },
    {
      title: "获取结果",
      text: "处理完成后可在线预览，并下载生成的ニコカラ视频。",
    },
  ],
  callToAction: "开始创建",
  repository: {
    url: "https://github.com/Aperove/nicokara-studio",
    label: "在 GitHub 上查看本项目",
  },
  metadataDescription:
    "上传 MV 和日语歌词，自动生成带逐字高亮和假名注音的ニコカラ视频。",
} as const;

export const UPLOAD_COPY = {
  videoSectionTitle: "视频素材",
  videoPrompt: "选择 MP4 视频",
  videoHelp: "支持最大 1 GB 的 MP4 文件，请确保视频包含可正常播放的音轨。",
  lyricsSectionTitle: "歌词内容",
  lyricsHint: "每句歌词需单独成行（不然会卡出屏幕QAQ）",
  vocalSectionTitle: "人声模式",
  vocalOnLabel: "ON VOCAL",
  vocalOffLabel: "OFF VOCAL",
  offVocalHint:
    "本机将使用 MDX 模型分离人声并生成伴奏音轨，处理时间会相应增加。",
  reviewSectionTitle: "合成前核对",
  reviewLabel: "合成视频前先核对时间轴",
  reviewHint:
    "自动对齐难免有几句不准。勾选后会先停在核对界面，可以边听边修正，确认后再合成视频。",
  uploadProgressTitle: "正在导入素材到本机",
  uploadProgressDescription: "导入完成后会自动进入任务状态页。",
  uploadingButton: "正在导入…",
  submitButton: "提交生成任务",
  footer:
    "导入完成后，任务会由本地处理服务继续执行。关闭页面不会中断任务，但请保持本地服务运行。",
} as const;

export const JOB_COPY = {
  backToUpload: "返回上传页",
  loading: "正在读取本地任务状态…",
  currentProgress: "当前进度",
  submittedVideo: "提交的视频",
  taskId: "任务 ID",
  lyricsSource: "歌词来源",
  pastedLyrics: "粘贴输入",
  textFileLyrics: "TXT 文件",
  resultHeading: "生成结果",
  downloadTranscript: "下载歌声识别数据",
  downloadLyrics: "下载歌词处理数据",
  downloadTimeline: "下载歌词时间轴",
  downloadSubtitle: "下载字幕文件",
  unsupportedVideo: "当前浏览器无法播放该视频，请直接下载后查看。",
  downloadVideo: "下载生成的视频",
  downloadOnVocal: "下载 ON VOCAL 版",
  downloadOffVocal: "下载 OFF VOCAL 版",
  offVocalMissing: "这个任务没有生成 OFF VOCAL 版（伴奏分离失败，或任务创建于此功能之前）。",
  createAnother: "创建新任务",
} as const;

export const STYLE_COPY = {
  sectionTitle: "字幕样式",
  expand: "自定义样式",
  collapse: "收起",
  defaultSummary: "默认：珊瑚色高亮、白字深色描边、左右交错排布",
  colorPresets: "配色方案",
  previewHint: "预览仅供参考，最终效果以生成的视频为准。",
  sungColor: "已唱颜色",
  unsungColor: "未唱颜色",
  outlineColor: "描边颜色",
  font: "字体",
  fontHint:
    "需要是处理视频的那台机器上已安装的字体，找不到时会自动换成其他日文字体。标有 Docker 的字体在 Docker 部署中可用，其余为 Windows 自带字体。",
  customFont: "其他字体",
  customFontPlaceholder: "输入已安装的字体名称",
  fontSize: "字号",
  fontSizeHint: "歌词行过长时会自动缩小，以免超出画面。",
  layout: "排布方式",
  layoutStaggered: "左右交错",
  layoutCentered: "居中",
  verticalPosition: "垂直位置",
  positionTop: "顶部",
  positionMiddle: "中部",
  positionBottom: "底部",
  showRuby: "显示假名注音",
  glow: "高亮发光效果",
  leadIn: "提前显示",
  reset: "恢复默认样式",
  restyleHeading: "修改字幕样式",
  restyleDescription:
    "只重新生成字幕和视频，不会重新识别歌声，通常一两分钟即可完成。",
  restyleButton: "用新样式重新生成",
  restyling: "正在提交…",
} as const;

export const REVIEW_COPY = {
  heading: "核对时间轴",
  description:
    "播放原视频，对照实时变色预览检查每一句。发现不准的句子，可以在波形时间轴上直接拖动，也可以改起止时间或边听边打点。",
  openFromCompleted: "核对并修正时间轴",
  close: "返回结果",
  loading: "正在读取时间轴…",
  sourceVideo: "原视频",
  vocalsOnly: "仅人声",
  previewIdle: "（间奏）",
  lineStart: "起",
  lineEnd: "止",
  playLine: "播放此句",
  setStart: "把起点设为当前播放位置",
  setEnd: "把终点设为当前播放位置",
  resetLine: "撤销此句的修改",
  concernShort: "过短",
  concernLowConfidence: "匹配度低",
  concernOddPace: "语速异常",
  movedOutOfRest: "AI 从间奏里挪出",
  stuckInRest: "落在间奏里",
  lrcAdjusted: "按 LRC 调整过",
  restLabel: "间奏",
  edited: "已修改",
  concernSummary: (count: number) =>
    count ? `有 ${count} 句建议重点核对` : "没有发现明显可疑的句子",
  showConcernsOnly: "只看可疑的句子",
  unsavedCount: (count: number) => `${count} 处修改未保存`,
  save: "保存修改",
  saving: "正在保存…",
  refine: "用 AI 重新对齐已修改的句子",
  refining: "AI 对齐中，约需一分钟…",
  refineHint:
    "只需把句子的起止范围大致标对，AI 会在这个范围里重新精确到每个词。",
  styleTitle: "字幕样式",
  styleHint: "上方的预览会按这里的设置实时变化；样式在点“确认并合成视频”时一并保存。",
  styleOpen: "调整样式",
  styleClose: "收起",
  fallbackTitle: "这首歌没能用上整首强制对齐，时间轴来自语音识别，精度较低",
  fallbackReason: (reason: string) => `原因：${reason}`,
  fallbackUnknown: "这个任务是在启用整首强制对齐之前处理的，或失败原因没有留下记录。",
  fallbackRetry: "重试整首对齐",
  fallbackRetrying: "正在对齐整首歌（约 1 分钟）…",
  fallbackConfirm:
    "重试成功后会用新的结果替换当前时间轴，包括已经手动修改过的句子。要继续吗？",
  fallbackDone: "已改用整首强制对齐的结果，请再听一遍确认",
  refinedResult: (done: number, total: number) =>
    done === total
      ? `已重新对齐 ${done} 句，请再听一遍确认`
      : `已重新对齐 ${done} / ${total} 句，其余保持手动时间`,
  render: "确认并合成视频",
  rendering: "正在提交…",
  invalidRange: "终点必须晚于起点",
  readings: "读音",
  readingClickHint: "点一下修改这个词的读音",
  readingsTitle: "检查并修改这一句的假名读音",
  readingsHint:
    "读音错了，屏幕上的注音和句内的变色节奏都会跟着错。改完保存后，可以再让 AI 重新对齐这一句。",
  readingsLocalWarning:
    "这首歌的读音由本机词典生成，多音字容易读错，建议把带汉字的词过一遍。",
  readingInvalid: "读音只能填假名",
  readingsNone: "这一句没有需要检查读音的词",
  invalidTime: "时间格式应为 分:秒，例如 1:29.08",
  trackLine: "时间轴上的句子",
  trackHint:
    "拖动色块可以整体移动一句，拖动两端的白边可以单独调整起点或终点；点击空白处跳转播放位置。",
  trackScroll: "滚动时间轴",
  followPlayhead: "跟随播放",
  zoomIn: "放大时间轴",
  zoomOut: "缩小时间轴",
} as const;

export const CREATE_COPY = {
  heading: "新建任务",
  sourceTitle: "视频素材",
  sourceFile: "本地文件",
  sourceLink: "视频链接",
  linkLabel: "视频链接",
  linkPlaceholder: "粘贴 YouTube 视频链接",
  linkHelp:
    "目前支持 YouTube 链接。视频会由本机下载到任务目录，下载完成后自动开始处理。",
  linkRights: "请只下载你有权使用的视频。",
  lyricsPlaceholder: "在这里粘贴日语歌词，每句单独一行；也可以直接粘贴带时间标签的 LRC",
  optionsTitle: "选项",
  bothVersions:
    "会同时生成 ON VOCAL（原唱）和 OFF VOCAL（伴奏）两个版本，画面只渲染一次。",
  invalidLink: "请填写以 http:// 或 https:// 开头的视频链接",
  linkRequired: "请填写视频链接，或切换到“本地文件”选择视频",
} as const;

export const JOBS_COPY = {
  heading: "最近任务",
  empty: "还没有任务。创建第一个任务后会出现在这里。",
  loadFailed: "无法读取任务列表，请确认本地后端正在运行。",
  refresh: "刷新",
  justNow: "刚刚",
  minutesAgo: (minutes: number) => `${minutes} 分钟前`,
  hoursAgo: (hours: number) => `${hours} 小时前`,
  daysAgo: (days: number) => `${days} 天前`,
} as const;
