# ニコカラ自动生成器 Studio

面向ニコカラ制作者、字幕轴制作者及具备一定视频制作经验的用户，提供高质量、高自由度的本地制作工具。

本地部署版并不追求完全取代人工制作，而是希望自动完成重复、耗时的基础工作，并为制作者保留检查、调整和精细控制的空间，从而缩短制作时间，提高成片质量。

## 项目定位

本地部署版以“高效制作、精细调整”为核心：

- 使用本地设备完成音视频处理
- 辅助生成歌词时间轴和 Karaoke 字幕
- 保留人工检查与修正流程
- 支持更丰富的字幕样式和输出参数
- 面向高质量ニコカラ及 PV 歌词视频制作

适合已经了解字幕打轴、ASS 字幕或视频剪辑，希望提高制作效率并保留完整控制权的用户。

## 当前版本状态

Studio 仓库目前以已经完成 Phase 1-8 的服务器运行版本为开发基线，现有代码具备完整的视频生成闭环、Docker 本地运行能力和 Linux 服务器部署能力。专业时间轴编辑、字幕预览和样式编辑等 Studio 功能仍属于后续开发内容。

> GitHub 仓库中的代码不会自动同步到正在运行的服务器。修改代码后仍需重新构建、打包、上传并切换服务器版本，具体步骤见 [本地构建与无 Docker 部署指南](./DEPLOYMENT_LOCAL_BUILD.md)。

## 当前能力

| 模块 | 状态 | 能力 |
|---|---|---|
| 素材上传 | 已完成 | MP4 校验、1 GB 限制、歌词粘贴或 UTF-8 TXT 上传、上传进度 |
| 人声模式 | 已完成 | `ON VOCAL` 保留原人声；`OFF VOCAL` 使用 MDX 生成人声分离后的伴奏 |
| 歌声识别 | 已完成 | FFmpeg 音频提取、faster-whisper 日语识别和词级时间戳 |
| 歌词处理 | 已完成 | DeepSeek 可选处理、pykakasi 本地降级、Ruby 注音和 Mora 拆分 |
| 时间轴与字幕 | 已完成 | 歌词对齐、漏词插值、ASS v4+、逐字高亮和 Ruby 注音 |
| 视频合成 | 已完成 | FFmpeg/libass 烧录、H.264 MP4、在线播放和下载 |
| 前端反馈 | 已完成 | 中文进度、服务器错误分类、详细原因、解决方案和技术信息 |
| 运行保护 | 已完成 | 单任务队列、限流、重启恢复、自动清理和路径安全校验 |
| 部署 | 已完成 | Docker Compose；Linux 下的 Nginx + systemd + `/data/nicokara` 发布结构 |

## 当前开发重点

后续将重点完善以下专业制作功能：

- 导入并使用已有歌词或字幕文件
- 提供可视化时间轴编辑与手动校准
- 增加汉字假名注音的检查和修正流程
- 支持字体、颜色、描边、位置及 Karaoke 效果自定义
- 提供字幕预览和生成前检查
- 支持保存配置，复用个人字幕样式

## 处理流程

上传任务会依次经过以下阶段：

```text
上传完成
-> 提取音频
-> 分离人声（仅 OFF VOCAL）
-> 识别歌声
-> 处理歌词与假名
-> 对齐歌词时间轴
-> 生成 ASS 字幕
-> 合成最终视频
-> 在线预览或下载
```

成功任务会在独立任务目录中生成：

```text
storage/jobs/{job_id}/
|-- input.mp4
|-- lyrics.txt
|-- audio.wav
|-- audio_instrumental.wav      # 仅 OFF VOCAL
|-- transcript.json
|-- lyrics_processed.json
|-- timeline.json
|-- lyrics.ass
`-- final_karaoke.mp4
```

`timeline.json`、`lyrics.ass` 等中间文件可以作为后续 Studio 编辑器的输入基础。目前版本尚未提供可视化修改界面，需要使用外部工具手动检查或编辑。

## 技术架构

```text
浏览器
|-- /       -> Next.js 前端
`-- /api/   -> FastAPI 后端
                  |-- SQLite
                  |-- storage/jobs
                  |-- Whisper/MDX 本地模型
                  `-- FFmpeg/libass
```

- 前端：Next.js、React、TypeScript、Tailwind CSS
- 后端：FastAPI、SQLite
- 音视频：FFmpeg、libass、MDX-Net
- 识别与歌词：faster-whisper、DeepSeek（可选）、pykakasi（本地降级）
- 部署：Docker Compose，或 Linux + Nginx + systemd

## 项目目录

```text
frontend/       Next.js 前端
backend/        FastAPI 后端与测试
release/        Linux 发布、部署和恢复脚本
storage/jobs/   本地任务文件，不提交到 Git
DEPLOYMENT_LOCAL_BUILD.md  构建、发布和无 Docker 部署指南
```

## 本地运行

### Docker Compose

需要 Docker Desktop 和至少 2 GB 可用内存：

```powershell
docker compose up --build
```

启动后访问：

- 前端：http://localhost:3000
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

停止服务：

```powershell
docker compose down
```

### 不使用 Docker

后端需要 Python 3.11 或更高版本：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[ai,dev]"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

另开终端启动前端。Node.js 要求 `>=22.13.0`，推荐 Node.js 24：

```powershell
cd frontend
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000/api/v1"
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1 --port 3000
```

本地直接运行时还需安装 FFmpeg，并保证 `ffmpeg` 可从 `PATH` 调用。首次转录会下载 faster-whisper 模型。

## 服务器部署与更新

虽然 Studio 的目标是本地专业制作，当前基线仍保留完整的服务器部署能力。推荐生产结构：

```text
/data/nicokara/
|-- releases/          每次发布一个独立版本目录
|-- current -> releases/{release-id}
`-- shared/
    |-- data/          SQLite 数据
    |-- storage/jobs/  上传和生成结果
    |-- models/        Whisper 与 MDX 模型
    `-- nicokara.env   生产环境配置
```

更新已经运行的服务器时：

1. 在本地拉取或确认需要发布的提交。
2. 使用相对 API 地址 `NEXT_PUBLIC_API_URL=/api/v1` 构建 Linux 前端产物。
3. 按部署指南生成应用发布包并计算 SHA-256。
4. 将发布包上传到服务器 `/data/`。
5. 解压到新的 `/data/nicokara/releases/{release-id}/`。
6. 安装后端依赖，切换 `/data/nicokara/current` 软链接。
7. 重启前后端服务，并检查健康接口、首页和完整生成流程。

模型、SQLite、上传文件和任务结果位于 `shared/`，发布新版本时不应覆盖。完整命令和回滚方法见 [DEPLOYMENT_LOCAL_BUILD.md](./DEPLOYMENT_LOCAL_BUILD.md)。

## 关键配置

后端环境变量使用 `NICOKARA_` 前缀：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `NICOKARA_STORAGE_DIR` | `../storage/jobs` | 任务文件目录 |
| `NICOKARA_MAX_VIDEO_BYTES` | `1073741824` | MP4 最大字节数 |
| `NICOKARA_MAX_PENDING_JOBS` | `4` | 最大等待任务数 |
| `NICOKARA_MAX_UPLOADS_PER_HOUR` | `6` | 单来源每小时上传任务数 |
| `NICOKARA_JOB_RETENTION_HOURS` | `24` | 已结束任务保留时间 |
| `NICOKARA_ALLOWED_ORIGINS` | `http://localhost:3000` | 允许的前端来源 |
| `NICOKARA_WHISPER_MODEL` | `small` | Whisper 模型名称或本地路径 |
| `NICOKARA_WHISPER_DEVICE` | `cpu` | `cpu` 或 `cuda` |
| `NICOKARA_VOCAL_REMOVAL_BACKEND` | `mdx` | 人声分离后端 |
| `NICOKARA_DEEPSEEK_API_KEY` | 空 | DeepSeek Key；为空时使用本地歌词处理 |

密钥只应保存在本地 `.env` 或服务器 `/data/nicokara/shared/nicokara.env` 中，不要提交到 Git 仓库。

## 测试

```powershell
cd backend
python -m pytest

cd ..\frontend
npm.cmd run lint
npm.cmd test
npm.cmd run build
```

## 当前边界

- 当前还没有内置可视化时间轴、Ruby 注音修正和字幕样式编辑器。
- 当前前端要求用户提供歌词，无歌词模式尚未接入前端流程。
- 队列和限流目前是单进程实现；多后端实例需要引入 Redis/Celery 等共享服务。
- 当前没有用户账号和任务权限隔离，公开部署前应限制访问范围并启用 HTTPS。
- 原始 FFmpeg、模型路径及外部 API 错误只应写入服务器日志，不直接返回给用户。

## 进一步文档

- [本地构建与无 Docker 部署指南](./DEPLOYMENT_LOCAL_BUILD.md)
