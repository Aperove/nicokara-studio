# ニコカラ自动生成器 Studio

导入原版 MV 和日语歌词，在本机自动完成歌声识别、歌词对齐、假名注音和视频合成，生成带逐字变色效果的ニコカラ（卡拉OK字幕）视频。自动结果可以在合成前逐句核对、修正。

> **本仓库 fork 自 [Xuan-cc/nicokara-studio](https://github.com/Xuan-cc/nicokara-studio)。**
> 处理闭环（上传、识别、歌词处理、对齐、ASS 字幕、视频合成、部署脚本）来自原项目；本 fork 在此基础上重写了对齐算法，并补上了原项目 README 中列为“后续开发”的时间轴核对、字幕预览和样式编辑等功能。详见[与原项目的差异](#与原项目的差异)。

## 项目定位

面向ニコカラ制作者和字幕轴制作者的本地制作工具。它不追求完全取代人工，而是把重复、耗时的基础工作自动做完，再把检查和修正的控制权交还给制作者：

- 所有音视频处理都在本机完成，素材不上传到第三方（DeepSeek 歌词处理是可选项，见下文）
- 自动生成逐字时间轴和 Karaoke 字幕
- 合成前可以边听边核对，逐句修正时间
- 字幕的配色、字体、位置等可以在界面上直接选

原项目另有面向公开服务器的 Cloud 版本，两者定位不同，本仓库只关注本地制作。

## 与原项目的差异

| 方面 | 原项目 | 本 fork |
|---|---|---|
| 歌词对齐 | 按 Whisper 的段落分配时间窗。Whisper 处理歌声时每 30 秒才输出一个段落，导致大量歌词行时长为 0、没有变色效果 | 重写为整首歌的音节级全局对齐；识别并忽略 Whisper 塌缩的时间戳；保证每一行都有合理的时长 |
| 时间精度 | 只依赖 Whisper 的词级时间戳 | 可选接入 [karatimer](https://github.com/Jerry-at-GH/karatimer) 对整首歌做 CTC 强制对齐，不再需要语音识别；也可用 [Qwen3-ForcedAligner](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B) 分段精修（均需 GPU，见[可选：GPU 强制对齐](#可选gpu-强制对齐)） |
| 间奏 | 歌词可能被对到没人唱的间奏里 | 可选用 Roformer 分离出干净人声，检测间奏并把落在里面的句子自动挪出来 |
| 识别用的音频 | 带伴奏的原混音 | 先分离人声，用人声轨识别；可把歌词作为提示词传给 Whisper |
| 素材与界面 | 只能上传本地文件；首页左侧是大段介绍；只能靠网址回到某个任务 | 可直接填视频链接；首页改为“新建任务 + 最近任务列表”的工具式布局 |
| 人工核对 | 无，需导出文件用外部工具修改 | 任务页内置核对界面：原视频 + 实时变色预览、逐句播放、改时间、打点、AI 重新对齐单句 |
| 字幕样式 | 固定样式 | 8 套配色、11 种字体、字号、位置、排布、发光、注音开关；完成后可只换样式重新生成 |
| 长歌词行 | 可能超出画面 | 按每行所在位置的可用宽度自动缩小字号；半角字符不再导致注音偏移 |
| 稳定性 | — | 修复渲染超时残留半截视频、重启后排队任务丢失、关机等待过久、竖屏视频补边尺寸等问题；补齐 Python 3.13 下人声分离缺失的依赖 |

## 功能概览

| 模块 | 能力 |
|---|---|
| 素材来源 | 上传本地 MP4（校验、1 GB 限制、上传进度），或填写视频链接由本机用 yt-dlp 下载到任务目录（默认只允许 YouTube）；歌词粘贴或 UTF-8 TXT 上传，也可以直接粘贴 LRC（时间标签会被去掉，句子起点用来防止自动对齐出现几秒级的大错） |
| 任务列表 | 首页右侧显示最近任务的状态和进度，自动刷新，点击进入任务页 |
| 两个版本 | 每个任务同时生成 `ON VOCAL`（原唱）和 `OFF VOCAL`（MDX-Net 去除主唱的伴奏）两个成片；字幕只烧录一次，伴奏版只替换音轨，约多花几秒 |
| 歌声识别 | FFmpeg 提取音频，faster-whisper 日语识别；默认先分离出人声轨再识别，转录进度实时显示 |
| 歌词处理 | DeepSeek（可选）或本地 pykakasi 生成读音、分词和 Ruby 注音 |
| 时间轴对齐 | 音节级全局对齐；可选 karatimer 整首强制对齐（成功时跳过 Whisper）或 Qwen3 分段精修；可选间奏检测与修复；任何一步失败都自动退回上一级结果 |
| 核对与修正 | 合成前暂停等待核对；逐句播放、修改起止时间、打点、在波形上拖动；检查并修改假名读音；AI 重新对齐单句；手动修改不会被后续自动对齐覆盖 |
| 字幕样式 | 配色方案、字体、字号、排布、垂直位置、假名注音、发光、提前显示时间；带实时预览 |
| 字幕与视频 | ASS v4+、逐字 `\kf` 变色、Ruby 注音；FFmpeg/libass 烧录为 H.264 MP4，可在线播放和下载 |
| 重新生成 | 已完成的任务可以只换样式或只改时间轴后重新合成，不需要重新识别（约 1 分钟） |
| 运行保护 | 单任务队列、可选限流、重启后恢复排队任务、过期任务自动清理、路径安全校验 |

## 处理流程

```text
创建任务（上传文件，或填写视频链接）
-> 下载视频（仅链接方式）
-> 提取音频
-> 分离人声（得到伴奏和人声轨；伴奏用于 OFF VOCAL 成片）
-> 处理歌词与假名
-> 对齐歌词时间轴
     已配置 karatimer：整首强制对齐，不做语音识别
     否则或失败时：Whisper 识别 -> 全局对齐 -> 可选的 Qwen3 分段强制对齐
-> 间奏修复（已配置 Roformer 人声轨时）：把对到间奏里的句子挪到有人声的一侧
-> LRC 兜底（歌词是 LRC 时）：与 LRC 的句子起点相差超过 2 秒的句子按 LRC 纠正
-> 生成 ASS 字幕
-> 等待核对（上传时勾选“合成视频前先核对时间轴”才会停在这里）
-> 合成最终视频（ON VOCAL），再替换音轨得到 OFF VOCAL 版
-> 在线预览或下载
```

每个任务有独立目录：

```text
storage/jobs/{job_id}/
|-- source_url.txt              # 视频链接（用链接创建任务时）
|-- input.mp4                   # 上传或下载得到的视频
|-- lyrics.txt
|-- lyrics_lrc.json             # 粘贴 LRC 时，各句的起始时间
|-- style.json                  # 字幕样式（上传时设置，可在任务页修改）
|-- options.json                # 任务选项，例如是否先核对
|-- audio.wav                   # 16 kHz 单声道，用于识别
|-- audio_instrumental.wav      # 伴奏
|-- audio_vocals.wav            # 人声轨（原混音减伴奏），用于识别和对齐
|-- audio_vocals_clean.wav      # Roformer 人声轨，用于检测间奏和核对时试听（启用时）
|-- transcript.json             # 词级时间：karatimer 的对齐结果，或 Whisper 的识别结果
|-- transcript.source           # transcript.json 的来源标记（karatimer 时存在）
|-- alignment_notes.json        # 检测到的间奏、被自动挪动的句子（启用时）
|-- lyrics_processed.json       # 歌词读音与分词
|-- forced_alignment.json       # Qwen3 强制对齐的词级时间（启用时）
|-- timeline.json               # 最终逐字时间轴，可在核对界面修改
|-- lyrics.ass
|-- final_karaoke.mp4           # ON VOCAL 成片
`-- final_karaoke_off.mp4       # OFF VOCAL 成片（有伴奏时）
```

## 核对与修正时间轴

自动对齐难免有几句不准。上传时保持勾选“合成视频前先核对时间轴”，任务会在字幕生成后停在“等待核对”状态；已完成的任务也可以在任务页点“核对并修正时间轴”进入同一个界面。

- 播放上传的原视频，下方预览条用浏览器实时绘制变色效果，不需要等待渲染
- 有人声轨时可以切换到“仅人声”来听，更容易判断每个字的起点
- 每句可以单独播放；起止时间可以直接改数字，也可以边听边点“起”“止”把时间设为当前播放位置
- 波形时间轴上可以直接拖动每一句：拖色块整体移动，拖两端单独调起点或终点；检测到的间奏会画成阴影
- 时长过短、匹配度低、语速异常，或被自动从间奏里挪出来的句子会被标出，可以只看这些可疑的句子
- 每句的“读音”按钮会列出带汉字的词和它们的假名读音，可以直接修改。读音错了，屏幕上的注音和句内的变色节奏都会跟着错；没有配置 DeepSeek 时读音来自本机词典，多音字尤其容易读错
- 启用了强制对齐时，可以让 AI 重新对齐改过的句子（包括改过读音的句子）：只需把起止范围大致标对，模型会在这个范围内重新精确到每个词（每次约 1 分钟，主要花在加载模型上，建议多改几句再一起执行）
- 多句修改会一次性保存，后端只校验最终结果（各句起点必须依次递增）
- 点“确认并合成视频”后才开始渲染

手动修改过的时间轴会带上标记，之后再“换样式重新生成”时不会被自动对齐覆盖。

目前只能调整整句的起止时间，句内每个字的节奏由对齐结果决定（可以用 AI 重新对齐来刷新），还不支持逐字拖动。

## 技术架构

```text
浏览器
|-- /       -> Next.js 前端
`-- /api/   -> FastAPI 后端
                  |-- SQLite
                  |-- storage/jobs
                  |-- faster-whisper / MDX-Net 本地模型
                  |-- FFmpeg / libass
                  `-- （可选）独立 Python 环境中的子进程：
                        karatimer 强制对齐 / Roformer 人声分离 / Qwen3-ForcedAligner
```

- 前端：Next.js、React、TypeScript、Tailwind CSS
- 后端：FastAPI、SQLite
- 音视频：FFmpeg、libass、MDX-Net（audio-separator）
- 识别与歌词：faster-whisper、DeepSeek（可选）、pykakasi（本地降级）
- 强制对齐：karatimer（推荐）或 Qwen3-ForcedAligner-0.6B；间奏检测：Mel-Band Roformer 人声分离（均可选，GPU）
- 部署：Docker Compose，或 Linux + Nginx + systemd

这些 GPU 组件运行在单独的 Python 解释器里，以子进程方式调用。这样后端依赖里不需要 PyTorch，每首歌处理完显存即释放，没有 GPU 的部署不配置这一项就完全不受影响。

## 项目目录

```text
frontend/       Next.js 前端
backend/        FastAPI 后端与测试
release/        Linux 发布、部署和恢复脚本
storage/jobs/   本地任务文件，不提交到 Git
work/           本地实验与可选环境，不提交到 Git
DEPLOYMENT_LOCAL_BUILD.md  构建、发布和无 Docker 部署指南
```

## 本地运行

### Docker Compose

需要 Docker Desktop 和至少 2 GB 可用内存：

```powershell
docker compose up --build
```

启动后访问：

- 前端：http://localhost:3200
- API 文档：http://localhost:8100/docs
- 健康检查：http://localhost:8100/health

停止服务：

```powershell
docker compose down
```

Docker 镜像内只有 Noto Sans CJK 字体，也不包含 Qwen3 强制对齐环境；选择其他字体时 libass 会自动替换为可用的日文字体。

### 不使用 Docker

后端需要 Python 3.11 或更高版本：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[ai,dev]"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8100
```

另开终端启动前端。Node.js 要求 `>=22.13.0`：

```powershell
cd frontend
$env:NEXT_PUBLIC_API_URL = "http://localhost:8100/api/v1"
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1 --port 3200
```

还需要 FFmpeg。可以让 `ffmpeg` 能从 `PATH` 调用，也可以用 `NICOKARA_FFMPEG_PATH` 指向具体的可执行文件（文件名需为 `ffmpeg` / `ffmpeg.exe`）；后端启动时会把它所在的目录加入 `PATH`，供人声分离库调用。

后端配置写在 `backend/.env`，可从仓库根目录的 `.env.example` 复制需要的项。首次处理任务时会自动下载 faster-whisper 模型和 MDX-Net 模型。

### 可选：GPU 强制对齐

三个可选组件都运行在同一个**单独的虚拟环境**里，以子进程方式调用，互不依赖，可以只启用其中一部分。需要 NVIDIA GPU。

| 组件 | 作用 | 配置项 |
|---|---|---|
| [karatimer](https://github.com/Jerry-at-GH/karatimer) | 推荐。用为日语卡拉OK微调的 CTC 模型把已知歌词对齐到整首歌，成功时跳过 Whisper 和 Qwen3 | `NICOKARA_KARATIMER_PYTHON` |
| Roformer 人声分离 | 产出干净人声轨，用来检测间奏、修复对到间奏里的句子，也用于核对界面的“仅人声”试听 | `NICOKARA_VOCAL_STEM_PYTHON` |
| Qwen3-ForcedAligner | 没有 karatimer 时，对 Whisper 的粗定位做分段精修 | `NICOKARA_FORCED_ALIGNER_PYTHON` |

在一首有人工校对时间轴的歌上实测（43 句）：只用 Whisper + Qwen3 时有 6 句的起点误差超过 1 秒；karatimer 加间奏修复后没有一句超过 1 秒，起点误差中位数约 0.06 秒，整首处理约 70 秒。这只是一首歌的结果，不代表所有歌曲。

安装环境：

```powershell
python -m venv work\qwen-venv
work\qwen-venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
work\qwen-venv\Scripts\python.exe -m pip install -U qwen-asr soundfile
# karatimer：它依赖的 pyopenjtalk 在 Windows 上需要编译，可改用有预编译包的 pyopenjtalk-plus
git clone https://github.com/Jerry-at-GH/karatimer work\karatimer
work\qwen-venv\Scripts\python.exe -m pip install "av>=18.1,<19" "jaconv==0.5.0" "numba>=0.61" pyopenjtalk-plus
work\qwen-venv\Scripts\python.exe -m pip install --no-deps -e work\karatimer
# Roformer 人声分离
work\qwen-venv\Scripts\python.exe -m pip install audio-separator onnxruntime audioread
```

然后在 `backend/.env` 中指向这个环境的解释器并重启后端：

```text
NICOKARA_KARATIMER_PYTHON=C:/path/to/nicokara-studio/work/qwen-venv/Scripts/python.exe
NICOKARA_VOCAL_STEM_PYTHON=C:/path/to/nicokara-studio/work/qwen-venv/Scripts/python.exe
NICOKARA_FORCED_ALIGNER_PYTHON=C:/path/to/nicokara-studio/work/qwen-venv/Scripts/python.exe
```

首次使用各组件时会自动下载模型（Qwen3 约 1.8 GB，Roformer 约 0.9 GB，karatimer 另有两个 wav2vec2 模型）。在 RTX 4070 上实测一首 4 分半的歌：Qwen3 对齐本身约 1 秒、模型加载约 20 秒、显存峰值约 2.2 GB；Roformer 分离约 17 秒。

说明：

- karatimer 使用的对齐模型 `NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn` 以 **CC-BY-NC-SA-4.0** 授权，只能用于非商业用途。
- karatimer 直接对原视频的完整混音做对齐；人声轨只用于间奏检测。实测中，把识别和对齐也换到 Roformer 人声轨上反而更差，所以这两步仍使用常规人声轨。
- 间奏检测的阈值相对每首歌自身的响度设定；人声轨不够干净时会放弃检测，不会硬猜。
- 把整首歌一次性交给 Qwen3 模型会在后半首严重漂移，所以这里按 Whisper 的粗定位把歌切成约 30 秒的片段分别对齐，切点只选在 Whisper 时间可靠的位置。
- 强制对齐失败，或结果只匹配到不足 60% 的歌词时，会自动退回 Whisper 的时间轴，任务不会因此失败。
- 留空 `NICOKARA_FORCED_ALIGNER_PYTHON` 即关闭，行为与未安装时完全相同。

## 关键配置

后端环境变量使用 `NICOKARA_` 前缀，完整列表见 `.env.example`：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `NICOKARA_STORAGE_DIR` | `../storage/jobs` | 任务文件目录 |
| `NICOKARA_MAX_VIDEO_BYTES` | `1073741824` | MP4 最大字节数 |
| `NICOKARA_MAX_PENDING_JOBS` | `4` | 最大等待任务数（重启后恢复的任务不受此限制） |
| `NICOKARA_MAX_UPLOADS_PER_HOUR` | `0` | 单来源每小时上传任务数；`0` 表示不限流 |
| `NICOKARA_JOB_RETENTION_HOURS` | `24` | 已结束任务的保留时间，包含“等待核对”的任务 |
| `NICOKARA_ALLOWED_ORIGINS` | `http://localhost:3200` | 允许的前端来源 |
| `NICOKARA_FFMPEG_PATH` | `ffmpeg` | FFmpeg 命令或可执行文件路径 |
| `NICOKARA_VIDEO_URL_HOSTS` | `youtube.com,youtu.be` | 允许用链接创建任务的站点（含子域名），逗号分隔；其他地址一律拒绝 |
| `NICOKARA_VIDEO_COOKIES_FROM_BROWSER` | 空 | 可选：让 yt-dlp 借用这个浏览器的登录状态（`chrome`、`edge`、`firefox` 等）。个别视频需要登录才能观看时才需要；它会读取该浏览器的 cookie，默认关闭 |
| `NICOKARA_WHISPER_MODEL` | `small` | Whisper 模型名称或本地路径 |
| `NICOKARA_WHISPER_DEVICE` | `cpu` | `cpu` 或 `cuda` |
| `NICOKARA_WHISPER_LYRICS_HINT` | `true` | 把上传的歌词作为提示词传给 Whisper |
| `NICOKARA_TRANSCRIBE_VOCAL_STEM` | `true` | 先分离人声再识别；更准，但 `ON VOCAL` 任务也会多花几分钟做分离 |
| `NICOKARA_VOCAL_REMOVAL_BACKEND` | `mdx` | 人声分离后端 |
| `NICOKARA_KARATIMER_PYTHON` | 空 | 装有 karatimer 的 Python 解释器；留空则不启用整首强制对齐 |
| `NICOKARA_VOCAL_STEM_PYTHON` | 空 | 装有 torch 和 audio-separator 的 Python 解释器；留空则不做间奏检测 |
| `NICOKARA_FORCED_ALIGNER_PYTHON` | 空 | 装有 torch 和 qwen-asr 的 Python 解释器；留空则不启用 Qwen3 精修 |
| `NICOKARA_FORCED_ALIGNER_DEVICE` | `cuda:0` | 强制对齐使用的设备 |
| `NICOKARA_DEEPSEEK_API_KEY` | 空 | DeepSeek Key；为空时使用本地歌词处理 |

注意事项：

- 用链接创建任务时，视频由本机的 yt-dlp 下载。视频站点经常改版，下载失败时先升级它：`python -m pip install -U yt-dlp`。请只下载你有权使用的视频，并遵守来源站点的条款。
- 配置了 DeepSeek Key 时，歌词文本会发送到 DeepSeek 的接口以生成读音；不希望歌词离开本机就保持为空。
- 歌词提示可能让 Whisper 在间奏里“听出”并不存在的歌词。如果发现对齐反而变差，先把 `NICOKARA_WHISPER_LYRICS_HINT` 设为 `false` 对比。
- 密钥只应保存在本地 `.env` 或服务器的环境配置文件中，不要提交到 Git 仓库。

## 任务接口

所有接口位于 `/api/v1/jobs` 之下：

| 方法与路径 | 作用 |
|---|---|
| `GET /` | 最近任务列表（`limit`，最多 100） |
| `POST /` | 创建任务（视频文件或 `video_url` 二选一、歌词、样式、是否先核对；`vocal_mode` 默认 `both`，也接受旧的 `on` / `off`） |
| `GET /{id}` | 任务状态与进度 |
| `GET /{id}/transcript`、`/lyrics`、`/timeline`、`/subtitle` | 下载中间文件 |
| `GET /{id}/result`、`/download` | 在线播放或下载成片；加 `?vocal=off` 取 OFF VOCAL 版 |
| `GET /{id}/style`、`POST /{id}/restyle` | 读取样式；用新样式重新生成 |
| `GET /{id}/review` | 核对界面所需的时间轴与能力信息 |
| `GET /{id}/source`、`/audio/{mix\|vocals}` | 原视频与音轨，供核对时播放 |
| `PUT /{id}/timeline` | 批量保存逐句的起止时间 |
| `PUT /{id}/readings` | 修改词的假名读音，同时更新歌词数据和时间轴 |
| `POST /{id}/timeline/refine` | 在当前起止范围内用强制对齐重新对齐指定的句子 |
| `POST /{id}/render` | 按当前时间轴合成视频 |

## 服务器部署

原项目保留了完整的 Linux 服务器部署方式（Nginx + systemd + `/data/nicokara` 发布结构），本 fork 没有改动这部分。完整步骤和回滚方法见 [DEPLOYMENT_LOCAL_BUILD.md](./DEPLOYMENT_LOCAL_BUILD.md)。

需要注意：

- 在反向代理后面运行时，限流依据的客户端地址需要代理传递 `X-Forwarded-For`，并让 uvicorn 以 `--proxy-headers` 启动，否则所有用户会共用同一个地址。
- 上传大小的真正限制要靠 Nginx 的 `client_max_body_size`；后端的大小检查发生在请求体接收完成之后。
- 本项目没有用户账号和任务权限隔离，知道任务 ID 就能访问和修改该任务，不应直接作为公开服务使用。

## 测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest

cd ..\frontend
npm.cmd run lint
npm.cmd test
npm.cmd run build
```

当前基线：后端 198 项测试；前端 8 个测试文件、43 项测试。类型检查中 `frontend/worker/index.ts` 有两个缺少 Cloudflare 类型定义的既有报错，与功能无关。

## 已知限制

- 核对界面只能调整整句的起止时间（可在波形时间轴上拖动），不能逐字调整。
- 读音可以在核对界面里逐词修改，但不会自动找出读错的词，需要人工过一遍；歌词原文（汉字写法）本身还不能在界面里改。
- 必须提供歌词；没有无歌词模式。LRC 只用它的句子起点做兜底，逐字时间（增强型 LRC）和 ASS 字幕文件里的时间不会被采用。
- 字幕样式不能保存为个人预设；描边粗细等更细的参数还不能调。
- 和声跨过句子边界时，相邻两句的分界可能偏差零点几秒；人工打点本身也有约 0.3 秒的浮动。
- 未启用 karatimer 时：Whisper `small` 的词级时间戳在歌声上经常塌缩，部分句子的时间只能按语速估算；Qwen3 的时间分辨率为 80 毫秒，唱得极快的字可能没有可见的变色过程。
- 伴奏分离失败时任务照常完成，只是没有 OFF VOCAL 版；在此功能之前创建的任务重新生成时仍按原来的单版本输出。
- OFF VOCAL 成片的伴奏仍由 MDX-Net Karaoke 模型生成；Roformer 人声轨目前只用于分析，不用于成片。
- 以上实测结论都只来自一首歌，阈值和取舍还需要更多歌曲验证。
- 字体由负责渲染的那台机器提供；界面里的字体列表是 Windows 常见日文字体，Docker 部署中只有 Noto Sans CJK 可用。
- 只支持日语歌曲；上传只接受 MP4，链接方式默认只允许 YouTube。
- 队列和限流是单进程实现；多后端实例需要引入 Redis/Celery 等共享服务。

## 后续计划

- 自动找出可能读错的词（例如对比歌声识别结果）
- 用只保留主唱的分离模型减轻和声对句子分界的影响
- 逐字级的时间微调与波形显示
- 保存和复用个人字幕样式

## 来源与致谢

- 原项目：[Xuan-cc/nicokara-studio](https://github.com/Xuan-cc/nicokara-studio)。本仓库是它的 fork，整体架构、处理流程和部署脚本均来自原项目。
- 整首强制对齐来自 [Jerry-at-GH/karatimer](https://github.com/Jerry-at-GH/karatimer)（Apache-2.0）。本项目只在运行时调用它，没有包含它的代码；它使用的 [NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn](https://huggingface.co/NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn) 模型为 CC-BY-NC-SA-4.0（非商用）。
- 使用的开源组件与模型：[faster-whisper](https://github.com/SYSTRAN/faster-whisper)、[Qwen3-ASR / Qwen3-ForcedAligner](https://github.com/QwenLM/Qwen3-ASR)、[audio-separator](https://github.com/nomadkaraoke/python-audio-separator) 与 UVR 社区的 MDX-Net 模型、[pykakasi](https://codeberg.org/miurahr/pykakasi)、FFmpeg、libass。各组件和模型遵循其各自的许可证。

## 许可

原项目和本仓库目前都没有附带许可证文件。在原作者明确授权之前，请不要默认本仓库的代码可以自由再分发或商用；如需这样使用，请先联系原项目作者。

使用本工具处理的视频、音频和歌词的版权归其各自的权利人所有。请只处理你有权使用的素材，公开发布成片前确认已获得相应授权。

## 进一步文档

- [本地构建与无 Docker 部署指南](./DEPLOYMENT_LOCAL_BUILD.md)
