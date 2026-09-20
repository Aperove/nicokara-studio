#!/usr/bin/env bash

set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "请使用 root 用户执行此脚本。" >&2
  exit 1
fi

PUBLIC_ORIGIN="${1:-}"
RELEASE_ID="${2:-$(date +%Y%m%d-%H%M%S)}"
APP_ARCHIVE="${3:-}"

if [[ ! "$PUBLIC_ORIGIN" =~ ^http://[A-Za-z0-9._-]+$ ]]; then
  echo "用法: $0 http://服务器IP [发布编号] [应用包路径]" >&2
  echo "示例: $0 http://192.0.2.10 20260731-01 /data/nicokara-app-20260731-120000.tar.gz" >&2
  exit 1
fi

SERVER_NAME="${PUBLIC_ORIGIN#http://}"
if [[ -z "$APP_ARCHIVE" ]]; then
  # the newest application package that was uploaded
  APP_ARCHIVE="$(ls -1t /data/nicokara-app-*.tar.gz 2>/dev/null | head -n 1 || true)"
fi
if [[ -z "$APP_ARCHIVE" || ! -f "$APP_ARCHIVE" ]]; then
  echo "没有找到应用包 /data/nicokara-app-*.tar.gz，请先上传，或把路径作为第三个参数传入。" >&2
  exit 1
fi
WHISPER_ARCHIVE="/data/faster-whisper-small.tar.gz"
MDX_ARCHIVE="/data/audio-separator-UVR_MDXNET_KARA_2.tar.gz"
APP_ROOT="/data/nicokara"
RELEASE_DIR="$APP_ROOT/releases/$RELEASE_ID"
SHARED_DIR="$APP_ROOT/shared"

for command_name in sha256sum tar python3 node ffmpeg nginx curl systemctl; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "缺少运行环境命令: $command_name，请先完成部署步骤 2。" >&2
    exit 1
  fi
done

python3 -c \
  'import sys; assert sys.version_info >= (3, 11), "需要 Python 3.11+"'

if ! node -e \
  'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 13) ? 0 : 1)'; then
  echo "Node.js 版本过低，需要 >=22.13.0，推荐 24.x。" >&2
  exit 1
fi

if ! id www-data >/dev/null 2>&1; then
  echo "缺少 www-data 系统用户，请确认 Nginx 已正确安装。" >&2
  exit 1
fi

# Every build of the application has a different checksum, so it is checked
# against the SHA256SUMS file that was generated and uploaded with it.
echo "校验部署包: $APP_ARCHIVE"
SUMS_FILE="$(dirname "$APP_ARCHIVE")/SHA256SUMS"
if [[ ! -f "$SUMS_FILE" ]]; then
  echo "缺少 $SUMS_FILE，请把打包时生成的 SHA256SUMS 一并上传。" >&2
  exit 1
fi
if ! grep -q "  $(basename "$APP_ARCHIVE")\$" "$SUMS_FILE"; then
  echo "$SUMS_FILE 里没有 $(basename "$APP_ARCHIVE") 的校验值，两者不是同一次打包生成的。" >&2
  exit 1
fi
(
  cd "$(dirname "$APP_ARCHIVE")"
  # model packages only need to be present on the first deployment
  sha256sum -c --ignore-missing "$SUMS_FILE"
)

mkdir -p \
  "$RELEASE_DIR" \
  "$SHARED_DIR/data" \
  "$SHARED_DIR/storage/jobs" \
  "$SHARED_DIR/models"

if find "$RELEASE_DIR" -mindepth 1 -print -quit | grep -q .; then
  echo "发布目录非空，拒绝覆盖: $RELEASE_DIR" >&2
  echo "请指定新的发布编号，例如: $0 $PUBLIC_ORIGIN 20260731-02" >&2
  exit 1
fi

echo "解压应用..."
tar -xzf "$APP_ARCHIVE" -C "$RELEASE_DIR" --strip-components=1

WHISPER_MODEL="$SHARED_DIR/models/faster-whisper-small/model.bin"
if [[ ! -f "$WHISPER_MODEL" ]]; then
  echo "解压 Whisper 模型..."
  tar -xzf "$WHISPER_ARCHIVE" -C "$SHARED_DIR/models"
fi

MDX_MODEL="$SHARED_DIR/models/audio-separator/UVR_MDXNET_KARA_2.onnx"
if [[ ! -f "$MDX_MODEL" ]]; then
  echo "解压 MDX 人声分离模型..."
  tar -xzf "$MDX_ARCHIVE" -C "$SHARED_DIR/models"
fi

printf '%s  %s\n' \
  "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671" \
  "$WHISPER_MODEL" \
  "bf32e15105a09c0f7dddd2b67346146334d6f3ecb399ed7638eba2ab07cbf5f4" \
  "$MDX_MODEL" |
  sha256sum -c -

echo "安装后端 Python 依赖..."
python3 -m venv "$RELEASE_DIR/backend/.venv"
"$RELEASE_DIR/backend/.venv/bin/python" -m pip install --upgrade pip
"$RELEASE_DIR/backend/.venv/bin/python" -m pip install \
  -e "$RELEASE_DIR/backend[ai,reading]"

# Settings are only added, never overwritten: a redeploy must not wipe a key
# or a choice that was made on this server.
ENV_FILE="$SHARED_DIR/nicokara.env"
touch "$ENV_FILE"
ensure_env() {
  if ! grep -q "^$1=" "$ENV_FILE"; then
    printf '%s=%s\n' "$1" "$2" >>"$ENV_FILE"
  fi
}
set_env() {
  if grep -q "^$1=" "$ENV_FILE"; then
    sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$1" "$2" >>"$ENV_FILE"
  fi
}
ensure_env NICOKARA_DATA_DIR "$SHARED_DIR/data"
ensure_env NICOKARA_STORAGE_DIR "$SHARED_DIR/storage/jobs"
# the public address is what this run was asked to serve
set_env NICOKARA_ALLOWED_ORIGINS "$PUBLIC_ORIGIN"
ensure_env NICOKARA_PROCESSING_ENABLED true
ensure_env NICOKARA_FFMPEG_PATH ffmpeg
ensure_env NICOKARA_WHISPER_MODEL "$SHARED_DIR/models/faster-whisper-small"
ensure_env NICOKARA_WHISPER_DEVICE cpu
ensure_env NICOKARA_WHISPER_COMPUTE_TYPE int8
ensure_env NICOKARA_VOCAL_REMOVAL_BACKEND mdx
ensure_env NICOKARA_VOCAL_REMOVAL_MODEL UVR_MDXNET_KARA_2.onnx
ensure_env NICOKARA_VOCAL_REMOVAL_MODEL_DIR "$SHARED_DIR/models/audio-separator"
ensure_env NICOKARA_DEEPSEEK_API_KEY ""
# A shared server: visitors must not see each other's job ids, and must not
# be able to make this machine download videos.
ensure_env NICOKARA_JOB_LISTING_ENABLED false
ensure_env NICOKARA_VIDEO_URL_HOSTS ""
NICOKARA_DATA_DIR=$SHARED_DIR/data
NICOKARA_STORAGE_DIR=$SHARED_DIR/storage/jobs
NICOKARA_ALLOWED_ORIGINS=$PUBLIC_ORIGIN
NICOKARA_PROCESSING_ENABLED=true
NICOKARA_FFMPEG_PATH=ffmpeg
NICOKARA_WHISPER_MODEL=$SHARED_DIR/models/faster-whisper-small
NICOKARA_WHISPER_DEVICE=cpu
NICOKARA_WHISPER_COMPUTE_TYPE=int8
NICOKARA_VOCAL_REMOVAL_BACKEND=mdx
NICOKARA_VOCAL_REMOVAL_MODEL=UVR_MDXNET_KARA_2.onnx
NICOKARA_VOCAL_REMOVAL_MODEL_DIR=$SHARED_DIR/models/audio-separator
NICOKARA_DEEPSEEK_API_KEY=
EOF

chown -R www-data:www-data "$SHARED_DIR"
chmod 640 "$SHARED_DIR/nicokara.env"
ln -sfn "$RELEASE_DIR" "$APP_ROOT/current"

cat >/etc/systemd/system/nicokara-backend.service <<EOF
[Unit]
Description=Nicokara FastAPI Backend
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=$APP_ROOT/current/backend
EnvironmentFile=$SHARED_DIR/nicokara.env
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=HOME=$SHARED_DIR
ExecStart=$APP_ROOT/current/backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/nicokara-frontend.service <<EOF
[Unit]
Description=Nicokara Frontend
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=$APP_ROOT/current/frontend
Environment=NODE_ENV=production
Environment=HOST=127.0.0.1
Environment=PORT=3000
ExecStart=$(command -v node) $APP_ROOT/current/frontend/server.js
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/nginx/sites-available/nicokara <<EOF
server {
    listen 80;
    server_name $SERVER_NAME;

    client_max_body_size 1024m;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_request_buffering off;
        proxy_buffering off;
        proxy_read_timeout 7200s;
        proxy_send_timeout 7200s;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

ln -sfn \
  /etc/nginx/sites-available/nicokara \
  /etc/nginx/sites-enabled/nicokara

nginx -t
systemctl daemon-reload
systemctl enable --now nicokara-backend nicokara-frontend nginx
systemctl restart nicokara-backend nicokara-frontend
systemctl reload nginx

echo "检查服务..."
BACKEND_READY=false
for _ in {1..30}; do
  if curl --fail --silent http://127.0.0.1:8000/health >/dev/null; then
    BACKEND_READY=true
    break
  fi
  sleep 1
done

if [[ "$BACKEND_READY" != "true" ]]; then
  echo "后端未在 30 秒内就绪。" >&2
  journalctl -u nicokara-backend -n 100 --no-pager >&2
  exit 1
fi

curl --fail --silent --show-error http://127.0.0.1:8000/health
echo
curl --fail --silent --show-error --head http://127.0.0.1:3000/ |
  sed -n '1p'

echo
echo "部署完成: $PUBLIC_ORIGIN"
echo "发布目录: $RELEASE_DIR"
echo "查看日志:"
echo "  journalctl -u nicokara-backend -n 100 --no-pager"
echo "  journalctl -u nicokara-frontend -n 100 --no-pager"
