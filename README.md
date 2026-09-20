# ニコカラ自动生成器 Studio

给一段 MV 和日语歌词，在自己的电脑上生成带**逐字变色**和**假名注音**的ニコカラ（卡拉OK字幕）视频，`ON VOCAL` 和 `OFF VOCAL` 两个版本一次出齐。

自动对齐之后、合成视频之前，可以在浏览器里边听边核对：拖动波形上的句子、修正读音、让 AI 重新对齐改过的句子，确认无误再渲染。

> **原项目由 esr 开发**，原仓库为 `delete039/nicokara-studio`（现已删除）。本仓库 fork 自保留了原项目代码的 [Xuan-cc/nicokara-studio](https://github.com/Xuan-cc/nicokara-studio)。
> 上传、识别、歌词处理、ASS 字幕、视频合成和部署脚本这条处理闭环来自原项目。本 fork 在此基础上面向本地制作做了扩展：调整了歌词对齐，接入了强制对齐模型，并实现了原项目规划中的时间轴核对、字幕预览和样式编辑等功能。详见[与原项目的差异](#与原项目的差异)。

## 目录

- [它能做什么](#它能做什么)
- [快速开始](#快速开始)
- [推荐：GPU 组件](#推荐gpu-组件)
- [使用方法](#使用方法)
- [处理流程与任务文件](#处理流程与任务文件)
- [配置](#配置)
- [接口](#接口)
- [架构与目录](#架构与目录)
- [服务器部署](#服务器部署)
- [测试](#测试)
- [与原项目的差异](#与原项目的差异)
- [已知限制](#已知限制)
- [后续计划](#后续计划)
- [来源、致谢与许可](#来源致谢与许可)

## 它能做什么

| | |
|---|---|
| **素材** | 上传本地 MP4，或者直接填 YouTube 链接由本机下载；歌词粘贴、上传 TXT，或者直接粘贴 LRC |
| **读音与注音** | 自动生成每个词的假名读音，汉字上方显示 Ruby 注音；读音可以在核对时逐词修改 |
| **对齐** | 把已知歌词对齐到整首歌，精确到音节；自动把被对到间奏里的句子挪回有人唱的位置（句内的短暂停顿不算） |
| **核对** | 原视频 + 实时变色预览、仅人声试听、逐句播放、波形上拖动句子、打点、AI 重新对齐单句 |
| **样式** | 8 套配色、11 种字体、字号、排布、位置、注音和发光开关，带实时预览；完成后可以只换样式重新生成 |
| **成片** | H.264 MP4，`ON VOCAL`（原唱）和 `OFF VOCAL`（伴奏）两个版本；字幕只烧录一次，伴奏版只替换音轨 |
| **任务管理** | 首页列出最近任务的状态和进度，自动刷新；重启后自动恢复排队中的任务 |

所有音视频处理都在本机完成。唯一会把数据发到外部的是可选的 DeepSeek 歌词处理（见[配置](#配置)）。

它不追求完全取代人工：自动做完重复、耗时的部分，再把检查和修正的控制权交还给制作者。

## 快速开始

需要 Python 3.11+、Node.js 22.13+ 和 FFmpeg。

**后端**

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[ai,reading,dev]"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8100
```

**前端**（另开一个终端）

```powershell
cd frontend
$env:NEXT_PUBLIC_API_URL = "http://localhost:8100/api/v1"
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1 --port 3200
```

打开 http://localhost:3200 。API 文档在 http://localhost:8100/docs ，健康检查在 http://localhost:8100/health 。

几点说明：

- **FFmpeg**：让 `ffmpeg` 能从 `PATH` 调用，或者用 `NICOKARA_FFMPEG_PATH` 指向具体的可执行文件（文件名需为 `ffmpeg` / `ffmpeg.exe`）。后端启动时会把它所在的目录加入 `PATH`，供人声分离库调用。
- **`reading` 附加项**装的是 OpenJTalk 形态分析器（`pyopenjtalk-plus`，有预编译包，不需要编译），用来生成本机读音。不装也能运行，但读音会退回逐字查词典，带送假名的动词、形容词经常被读成音读。
- **配置**写在 `backend/.env`，可以从仓库根目录的 `.env.example` 复制需要的项。
- 首次处理任务时会自动下载 faster-whisper 和 MDX-Net 模型。

### 用 Docker

```powershell
docker compose up --build
```

需要 Docker Desktop 和至少 2 GB 可用内存，访问地址同上，`docker compose down` 停止。Docker 镜像里只有 Noto Sans CJK 字体，不包含 OpenJTalk 和下面的 GPU 组件。

## 推荐：GPU 组件

有 NVIDIA 显卡的话，强烈建议启用。这三个组件装在一个**单独的虚拟环境**里，由后端以子进程方式调用：后端本身不需要 PyTorch，每首歌处理完显存就释放，三者互不依赖，可以只启用一部分。

| 组件 | 作用 | 配置项 |
|---|---|---|
| [karatimer](https://github.com/Jerry-at-GH/karatimer) | **最推荐。** 用专门为日语卡拉OK微调的 CTC 模型，把已知歌词直接对齐到整首歌。成功时不再需要 Whisper 识别和 Qwen3 精修 | `NICOKARA_KARATIMER_PYTHON` |
| Roformer 人声分离 | 产出干净的人声轨，用来检测间奏、修复被对到间奏里的句子，也用于核对界面的“仅人声”试听 | `NICOKARA_VOCAL_STEM_PYTHON` |
| Qwen3-ForcedAligner | 没有 karatimer 时，对 Whisper 的粗定位做分段精修 | `NICOKARA_FORCED_ALIGNER_PYTHON` |

**实测效果**（一首 4 分半、43 句的歌，以人工校对的时间轴为标准，RTX 4070）：

| 方案 | 起点误差超过 1 秒的句子 | 起点误差中位数 |
|---|---|---|
| Whisper + Qwen3 | 6 句 | — |
| karatimer + 间奏修复 | **0 句** | **约 0.06 秒** |

整首歌处理约 70 秒。这只是一首歌的结果，不代表所有歌曲；人工打点本身也有约 0.3 秒的浮动。

### 安装

```powershell
python -m venv work\qwen-venv
work\qwen-venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126

# karatimer：它依赖的 pyopenjtalk 在 Windows 上需要编译，这里改用有预编译包的 pyopenjtalk-plus
git clone https://github.com/Jerry-at-GH/karatimer work\karatimer
work\qwen-venv\Scripts\python.exe -m pip install "av>=18.1,<19" "jaconv==0.5.0" "numba>=0.61" pyopenjtalk-plus
work\qwen-venv\Scripts\python.exe -m pip install --no-deps -e work\karatimer

# Roformer 人声分离
work\qwen-venv\Scripts\python.exe -m pip install audio-separator onnxruntime audioread

# Qwen3-ForcedAligner（可选）
work\qwen-venv\Scripts\python.exe -m pip install -U qwen-asr soundfile
```

然后在 `backend/.env` 里指向这个环境的解释器，重启后端：

```text
NICOKARA_KARATIMER_PYTHON=C:/path/to/nicokara-studio/work/qwen-venv/Scripts/python.exe
NICOKARA_VOCAL_STEM_PYTHON=C:/path/to/nicokara-studio/work/qwen-venv/Scripts/python.exe
NICOKARA_FORCED_ALIGNER_PYTHON=C:/path/to/nicokara-studio/work/qwen-venv/Scripts/python.exe
```

留空某一项就是不启用它，行为与未安装时完全相同。首次使用时会自动下载模型（Qwen3 约 1.8 GB，Roformer 约 0.9 GB，karatimer 另有两个 wav2vec2 模型）。

### 需要知道的

- **许可**：karatimer 使用的对齐模型 `NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn` 以 **CC-BY-NC-SA-4.0** 授权，只能用于非商业用途。
- **任何一步失败都不会让任务失败**：karatimer 出错时自动退回 Whisper（+ Qwen3）；Roformer 出错时只是不做间奏检测。
- **但退回不是悄悄发生的**：Whisper 的精度明显不如 karatimer，所以这样的任务在核对界面顶部会有提示并写明原因，旁边的“重试整首对齐”可以再跑一次 karatimer，成功后替换当前时间轴。
- karatimer 直接对原视频的完整混音做对齐。Roformer 人声轨只用于间奏检测和试听：实测中把识别和对齐也换到它上面反而更差。
- 间奏检测的阈值相对每首歌自身的响度设定；人声轨不够干净时会放弃检测，不会硬猜。
- Qwen3 不能一次处理整首歌（后半首会严重漂移），所以按 Whisper 的粗定位切成约 30 秒的片段分别对齐，切点只选在 Whisper 时间可靠的位置。实测一首歌对齐本身约 1 秒、模型加载约 20 秒、显存峰值约 2.2 GB；Roformer 分离约 17 秒。

## 使用方法

### 1. 新建任务

首页左边是表单，右边是最近任务列表。

- **视频素材**：选本地 MP4（最大 1 GB），或者切到“视频链接”粘贴 YouTube 链接。视频会下载到这个任务自己的目录里，下载完成后自动开始处理。
- **歌词**：每句单独一行。可以直接粘贴 LRC，时间标签会被自动去掉。
- **合成前核对**：默认勾选。任务会在字幕生成后停下来等你核对，而不是直接渲染。
- **字幕样式**：默认折叠，点“自定义样式”展开。这里不带预览，更适合在核对时对着真实歌词调（见下一节），也可以等出了成片再换。

### 2. 核对时间轴

任务停在“等待核对”时，任务页会直接显示核对界面；已完成的任务点“核对并修正时间轴”进入同一个界面。

窗口够宽时（至少约 1000×480），核对界面会铺满整个窗口：左边是视频、变色预览和波形，始终可见；右边是歌词列表，单独滚动并自动跟随正在唱的句子；字幕样式从右侧滑出。右上角的“退出工作台”可以回到任务页里的单列视图，窄窗口下始终是单列视图。

- **看**：播放原视频，下方预览条用浏览器实时绘制变色效果，不需要等渲染。预览按这个任务的字幕样式绘制（配色、字体、描边、发光、注音），太长的句子会缩小到放得下。
- **调样式**：预览条下面的“字幕样式”可以展开，改动会立刻反映在预览上，并在点“确认并合成视频”时一并保存。可以切到“仅人声”来听，更容易判断每个字的起点。
- **找**：时长过短、匹配度低、语速异常、被自动从间奏里挪出来，或按 LRC 调整过的句子都会带标记，可以勾选“只看可疑的句子”。
- **改时间**：在波形时间轴上拖色块整体移动一句，拖两端的白边单独调起点或终点；也可以直接改“分:秒”数字，或边听边点“起”“止”把时间设为当前播放位置。检测到的间奏会画成阴影。
- **改读音**：每句的“读音”按钮会列出带汉字的词和它们的假名读音。读音错了，屏幕上的注音和句内的变色节奏都会跟着错。注意词是按分析器的结果切分的，动词词干和后面的助词是两个词，只需填汉字那一部分的读音。
- **AI 重新对齐**：只需把句子的起止范围大致标对（或改好读音），模型会在这个范围内重新精确到每个词。每次约 1 分钟，主要花在加载模型上，建议多改几句再一起执行。
- **确认并合成视频**：多处修改会一次性保存，然后开始渲染。

手动修改过的时间轴会带上标记，之后再“换样式重新生成”时不会被自动对齐覆盖。

### 3. 成片

“生成结果”右上角可以在 `ON VOCAL` 和 `OFF VOCAL` 之间切换预览，下面是两个版本各自的下载按钮。任务页底部的“修改字幕样式”可以只换样式重新生成，不重新识别和对齐，约 1 分钟。

### 关于字号

字号只会自动**缩小**，不会放大：你选的字号是上限。整首歌统一用一个字号，由最宽的一句决定，最小缩到 40。“左右交错”排布时每句以画面 35% / 65% 处为中心，120 号字约能放 15 个全角字；“居中”排布约能放 21 个，句子偏长时选“居中”缩得更少。

## 处理流程与任务文件

```text
创建任务（上传文件，或填写视频链接）
-> 下载视频（仅链接方式）
-> 提取音频
-> 分离人声（得到伴奏和人声轨；伴奏用于 OFF VOCAL 成片）
-> 处理歌词：读音、分词、注音
-> 对齐歌词时间轴
     已配置 karatimer：整首强制对齐，不做语音识别
     否则或失败时：Whisper 识别 -> 全局对齐 -> 可选的 Qwen3 分段强制对齐
-> 间奏修复（已配置 Roformer 时）：把对到间奏里的句子挪到有人声的一侧
-> LRC 兜底（歌词是 LRC 时）：与 LRC 的句子起点相差超过 2 秒的句子按 LRC 纠正
-> 生成 ASS 字幕
-> 等待核对（勾选了“合成前核对”时）
-> 合成 ON VOCAL 视频，再替换音轨得到 OFF VOCAL 版
-> 在线预览或下载
```

每个任务有独立目录：

```text
storage/jobs/{job_id}/
|-- source_url.txt              # 视频链接（用链接创建任务时）
|-- input.mp4                   # 上传或下载得到的视频
|-- lyrics.txt
|-- lyrics_lrc.json             # 粘贴 LRC 时，各句的起始时间
|-- style.json                  # 字幕样式
|-- options.json                # 任务选项，例如是否先核对
|-- audio.wav                   # 16 kHz 单声道
|-- audio_instrumental.wav      # 伴奏
|-- audio_vocals.wav            # 人声轨（原混音减伴奏），用于识别和对齐
|-- audio_vocals_clean.wav      # Roformer 人声轨，用于检测间奏和试听（启用时）
|-- lyrics_processed.json       # 歌词读音与分词
|-- transcript.json             # 词级时间：karatimer 的对齐结果，或 Whisper 的识别结果
|-- transcript.source           # transcript.json 的来源标记（karatimer 时存在）
|-- transcript.asr.json         # 旧任务升级到 karatimer 时保留的 Whisper 结果
|-- forced_alignment.json       # Qwen3 强制对齐的词级时间（启用时）
|-- forced_alignment_failure.json  # 整首强制对齐失败、退回 Whisper 的原因（发生时）
|-- alignment_notes.json        # 检测到的间奏、被自动挪动或按 LRC 调整的句子
|-- timeline.json               # 最终逐字时间轴，可在核对界面修改
|-- lyrics.ass
|-- final_karaoke.mp4           # ON VOCAL 成片
`-- final_karaoke_off.mp4       # OFF VOCAL 成片（有伴奏时）
```

## 配置

后端环境变量使用 `NICOKARA_` 前缀，写在 `backend/.env`，完整列表见 `.env.example`。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `NICOKARA_STORAGE_DIR` | `../storage/jobs` | 任务文件目录 |
| `NICOKARA_FFMPEG_PATH` | `ffmpeg` | FFmpeg 命令或可执行文件路径 |
| `NICOKARA_MAX_VIDEO_BYTES` | `1073741824` | 视频最大字节数（上传和下载都受限） |
| `NICOKARA_MAX_PENDING_JOBS` | `4` | 最大等待任务数（重启后恢复的任务不受此限制） |
| `NICOKARA_MAX_UPLOADS_PER_HOUR` | `0` | 单来源每小时创建任务数；`0` 表示不限流 |
| `NICOKARA_JOB_RETENTION_HOURS` | `24` | 已结束任务的保留时间，包含“等待核对”的任务 |
| `NICOKARA_ALLOWED_ORIGINS` | `http://localhost:3200` | 允许的前端来源 |
| `NICOKARA_VIDEO_URL_HOSTS` | `youtube.com,youtu.be` | 允许用链接创建任务的站点（含子域名），逗号分隔；其他地址一律拒绝。留空则关闭链接方式，界面上不再显示 |
| `NICOKARA_JOB_LISTING_ENABLED` | `true` | 首页是否列出最近任务。多人共用的服务器应设为 `false`：任务 ID 是访问任务的唯一凭据 |
| `NICOKARA_VIDEO_COOKIES_FROM_BROWSER` | 空 | 让 yt-dlp 借用这个浏览器的登录状态（`chrome`、`edge`、`firefox` 等），个别视频需要登录才能观看时才需要。它会读取该浏览器的 cookie，默认关闭 |
| `NICOKARA_KARATIMER_PYTHON` | 空 | 装有 karatimer 的 Python 解释器；留空则不启用整首强制对齐 |
| `NICOKARA_VOCAL_STEM_PYTHON` | 空 | 装有 torch 和 audio-separator 的解释器；留空则不做间奏检测 |
| `NICOKARA_FORCED_ALIGNER_PYTHON` | 空 | 装有 torch 和 qwen-asr 的解释器；留空则不启用 Qwen3 精修 |
| `NICOKARA_FORCED_ALIGNER_DEVICE` | `cuda:0` | Qwen3 强制对齐使用的设备 |
| `NICOKARA_VOCAL_REMOVAL_BACKEND` | `mdx` | 伴奏分离后端 |
| `NICOKARA_WHISPER_MODEL` | `small` | Whisper 模型名称或本地路径（未启用 karatimer 或它失败时使用） |
| `NICOKARA_WHISPER_DEVICE` | `cpu` | `cpu` 或 `cuda` |
| `NICOKARA_WHISPER_LYRICS_HINT` | `true` | 把上传的歌词作为提示词传给 Whisper |
| `NICOKARA_TRANSCRIBE_VOCAL_STEM` | `true` | 用人声轨而不是原混音做识别 |
| `NICOKARA_DEEPSEEK_API_KEY` | 空 | DeepSeek Key；为空时读音完全在本机生成 |

注意事项：

- **读音从哪来**：配置了 DeepSeek Key 时，歌词文本会发送到 DeepSeek 的接口生成读音，通常最准，但歌词会离开本机。留空则用本机的 OpenJTalk；没装的话退回 pykakasi。
- **链接下载**：视频由本机的 yt-dlp 下载。视频站点经常改版，下载失败时先升级它：`python -m pip install -U yt-dlp`。请只下载你有权使用的视频，并遵守来源站点的条款。
- 歌词提示可能让 Whisper 在间奏里“听出”并不存在的歌词。走 Whisper 路径时如果发现对齐变差，把 `NICOKARA_WHISPER_LYRICS_HINT` 设为 `false` 对比。
- 密钥只应保存在本地 `.env` 或服务器的环境配置文件中，不要提交到 Git 仓库。

## 接口

任务接口位于 `/api/v1/jobs` 之下；另有 `GET /api/v1/capabilities` 返回本机开放了哪些功能（允许的视频站点、是否列出任务），界面据此隐藏未开放的部分。

| 方法与路径 | 作用 |
|---|---|
| `GET /` | 最近任务列表（`limit`，最多 100）；关闭任务列表时返回 404 |
| `POST /` | 创建任务：视频文件或 `video_url` 二选一、歌词、样式、是否先核对；`vocal_mode` 默认 `both`，也接受旧的 `on` / `off` |
| `GET /{id}` | 任务状态与进度 |
| `GET /{id}/result`、`/download` | 在线播放或下载成片；加 `?vocal=off` 取 OFF VOCAL 版 |
| `GET /{id}/transcript`、`/lyrics`、`/timeline`、`/subtitle` | 下载中间文件 |
| `GET /{id}/style`、`POST /{id}/restyle` | 读取样式；用新样式重新生成 |
| `GET /{id}/review` | 核对界面所需的时间轴、间奏、标记和能力信息 |
| `GET /{id}/source`、`/audio/{mix\|vocals}` | 原视频与音轨，供核对时播放 |
| `PUT /{id}/timeline` | 批量保存逐句的起止时间（只校验最终结果：各句起点必须依次递增） |
| `PUT /{id}/readings` | 修改词的假名读音，同时更新歌词数据和时间轴 |
| `POST /{id}/timeline/forced` | 对退回到语音识别的任务重新做整首强制对齐，成功后替换时间轴 |
| `POST /{id}/timeline/refine` | 在当前起止范围内用强制对齐重新对齐指定的句子 |
| `POST /{id}/render` | 按当前时间轴合成视频；可以附带核对时选好的字幕样式 |

## 架构与目录

```text
浏览器
|-- /       -> Next.js 前端
`-- /api/   -> FastAPI 后端
                  |-- SQLite
                  |-- storage/jobs
                  |-- faster-whisper / MDX-Net / OpenJTalk
                  |-- FFmpeg / libass / yt-dlp
                  `-- （可选）独立 Python 环境中的子进程：
                        karatimer / Roformer 人声分离 / Qwen3-ForcedAligner
```

- 前端：Next.js、React、TypeScript、Tailwind CSS
- 后端：FastAPI、SQLite，单进程任务队列
- 音视频：FFmpeg、libass、MDX-Net（audio-separator）、yt-dlp
- 歌词：DeepSeek（可选）、OpenJTalk、pykakasi（兜底）
- 对齐：自研的音节级全局对齐器；karatimer、Qwen3-ForcedAligner、Mel-Band Roformer（均可选，GPU）；faster-whisper 作为后备

```text
frontend/       Next.js 前端
backend/        FastAPI 后端与测试
release/        Linux 发布、部署和恢复脚本
storage/jobs/   本地任务文件，不提交到 Git
work/           可选的 GPU 环境与本地实验，不提交到 Git
DEPLOYMENT_LOCAL_BUILD.md  构建、发布和无 Docker 部署指南
```

## 服务器部署

原项目保留了完整的 Linux 服务器部署方式（Nginx + systemd + `/data/nicokara` 发布结构），本 fork 没有改动这部分。完整步骤和回滚方法见 [DEPLOYMENT_LOCAL_BUILD.md](./DEPLOYMENT_LOCAL_BUILD.md)。

需要注意：

- **本项目没有用户账号和任务权限隔离**，知道任务 ID 就能访问和修改该任务，不应直接作为公开服务使用。
- 部署脚本默认关闭首页的任务列表和视频链接下载（`NICOKARA_JOB_LISTING_ENABLED=false`、`NICOKARA_VIDEO_URL_HOSTS=`）：前者避免访客看到彼此的任务 ID，后者避免任何访客都能让服务器去下载视频。界面会自动隐藏对应的部分。
- 脚本覆盖的是 CPU 配置；GPU 组件需要另行安装。对外开放时请至少加一层 Nginx Basic 认证。
- 限流依据的客户端地址来自代理传递的 `X-Forwarded-For`；uvicorn 默认只信任本机代理发来的这个请求头，代理在另一台机器上时需要加 `--forwarded-allow-ips`。
- 上传大小的真正限制要靠 Nginx 的 `client_max_body_size`；后端的大小检查发生在请求体接收完成之后。

## 测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest

cd ..\frontend
npm.cmd run lint
npm.cmd test
npm.cmd run build
```

当前基线：后端 209 项测试；前端 8 个测试文件、43 项测试。类型检查中 `frontend/worker/index.ts` 有两个缺少 Cloudflare 类型定义的既有报错，与功能无关。

## 与原项目的差异

原项目已经把“上传 → 识别 → 歌词处理 → 对齐 → ASS 字幕 → 视频合成”的完整闭环和服务器部署都做好了，本 fork 的全部工作都建立在这个基础之上。两者的侧重点不同：原项目兼顾公开服务器上的轻量运行（另有 Cloud 版本），本 fork 只面向在自己电脑上制作，因此可以放心使用 GPU 和更重的模型，也把更多精力放在人工核对上。

在原项目的基础上，本 fork 主要增加和调整了这些：

| 方面 | 本 fork 的做法 |
|---|---|
| 歌词对齐 | 改为整首歌的音节级全局对齐，针对 Whisper 在歌声上时间戳不稳定的情况做了专门处理，让每一行都有合理的时长 |
| 时间精度 | 可选接入 karatimer 对整首歌做 CTC 强制对齐；也可用 Qwen3-ForcedAligner 分段精修 |
| 间奏 | 可选用 Roformer 分离出干净人声，检测间奏并把落在里面的句子自动挪出来 |
| 读音 | 本机读音在 pykakasi 之外增加了 OpenJTalk 形态分析；读音可以在核对界面里逐词修改 |
| 素材 | 在上传本地文件之外，可直接填 YouTube 链接；歌词可直接粘贴 LRC |
| 人工核对 | 实现了原项目规划中的时间轴核对：原视频 + 实时变色预览、波形拖动、打点、改读音、AI 重新对齐单句 |
| 字幕样式 | 配色、字体、字号、位置、排布、发光、注音开关可调；完成后可只换样式重新生成 |
| 成片 | 一次生成 ON / OFF VOCAL 两个版本，字幕只烧录一次 |
| 首页 | 调整为“新建任务 + 最近任务列表”的工具式布局 |
| 长歌词行 | 按每行所在位置的可用宽度自动缩小字号 |
| 其他 | 一些本地运行时遇到的边界情况处理：渲染超时的清理、重启后恢复排队任务、竖屏视频补边、Python 3.13 下人声分离的依赖等 |

这些改动大多依赖本地 GPU 或较长的处理时间，并不一定适合原项目的使用场景。

## 已知限制

- 只支持日语歌曲；上传只接受 MP4，链接方式默认只允许 YouTube；必须提供歌词，没有无歌词模式。
- 核对界面只能调整整句的起止时间，不能逐字调整；句内节奏由对齐结果决定，可以用 AI 重新对齐来刷新。
- 本机读音即使用了形态分析也会有错（人名、生僻词、歌词里的特殊读法），而且不会自动找出读错的词，需要人工过一遍。歌词原文（汉字写法）本身还不能在界面里改。
- 和声跨过句子边界时，相邻两句的分界可能偏差零点几秒。
- LRC 只用它的句子起点做兜底；增强型 LRC 的逐词时间和 ASS 字幕文件里的时间不会被采用。
- 未启用 karatimer 时：Whisper `small` 的词级时间戳在歌声上经常塌缩，部分句子的时间只能按语速估算；Qwen3 的时间分辨率为 80 毫秒，唱得极快的字可能没有可见的变色过程。
- 伴奏分离失败时任务照常完成，只是没有 OFF VOCAL 版；在两版输出功能之前创建的任务重新生成时仍按原来的单版本输出。伴奏由 MDX-Net Karaoke 模型生成，Roformer 人声轨目前只用于分析。
- 字幕样式不能保存为个人预设；描边粗细等更细的参数还不能调；样式预览不反映自动缩小后的字号。
- 字体由负责渲染的那台机器提供；界面里的字体列表是 Windows 常见日文字体，Docker 部署中只有 Noto Sans CJK 可用，其余会被自动替换。字宽按 Noto Sans CJK 估算，换用其他字体时边缘可能略有出入。
- 对齐相关的实测结论和阈值都只来自一首歌，还需要更多歌曲验证。
- 队列和限流是单进程实现；多后端实例需要引入 Redis/Celery 等共享服务。

## 后续计划

- 自动找出可能读错的词（例如对比歌声识别结果）
- 用只保留主唱的分离模型减轻和声对句子分界的影响
- 逐字级的时间微调
- 保存和复用个人字幕样式

## 来源、致谢与许可

- **原项目**：作者 esr，原仓库 `delete039/nicokara-studio`（现已删除，最初的提交记录仍保留在本仓库的历史中）。整体架构、处理流程和部署脚本均来自原项目。
- **fork 来源**：[Xuan-cc/nicokara-studio](https://github.com/Xuan-cc/nicokara-studio) 保留了原项目的代码，本仓库是从它 fork 而来的。
- **整首强制对齐**来自 [Jerry-at-GH/karatimer](https://github.com/Jerry-at-GH/karatimer)（Apache-2.0）。本项目只在运行时调用它，没有包含它的代码。它使用的 [NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn](https://huggingface.co/NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn) 模型为 CC-BY-NC-SA-4.0（非商用）。
- **其他开源组件与模型**：[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[Qwen3-ASR / Qwen3-ForcedAligner](https://github.com/QwenLM/Qwen3-ASR)、[audio-separator](https://github.com/nomadkaraoke/python-audio-separator) 与 UVR 社区的 MDX-Net、Roformer 模型、[pyopenjtalk-plus](https://github.com/tsukumijima/pyopenjtalk-plus)（OpenJTalk）、[pykakasi](https://codeberg.org/miurahr/pykakasi)、[yt-dlp](https://github.com/yt-dlp/yt-dlp)、FFmpeg、libass。各组件和模型遵循其各自的许可证。

**许可**：原项目和本仓库目前都没有附带许可证文件。在原作者明确授权之前，请不要默认本仓库的代码可以自由再分发或商用；如需这样使用，请先联系原项目作者。

使用本工具处理的视频、音频和歌词的版权归其各自的权利人所有。请只处理你有权使用的素材，公开发布成片前确认已获得相应授权。
