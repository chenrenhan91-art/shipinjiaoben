#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STATE_DIR="$HOME/.shipinjiaoben"
APP_DIR="$STATE_DIR/app"
TOOLS_DIR="$STATE_DIR/tools"
VENV_DIR="$STATE_DIR/venv"
DOUK_DIR="$TOOLS_DIR/TikTokDownloader"
LABEL="com.shipinjiaoben.collector-helper"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$STATE_DIR/logs"

SYSTEM_PYTHON="${PYTHON_BIN:-$(command -v python3 || true)}"
if [[ -z "$SYSTEM_PYTHON" ]]; then
  echo "未找到 python3，请先安装 Python 3。"
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR" "$APP_DIR" "$TOOLS_DIR"

echo "正在复制本机采集助手文件..."
rsync -a --delete \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  "$SOURCE_DIR/" "$APP_DIR/"

echo "正在准备 Python 虚拟环境..."
"$SYSTEM_PYTHON" -m venv "$VENV_DIR"
PYTHON_BIN="$VENV_DIR/bin/python"
"$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel
"$PYTHON_BIN" -m pip install -r "$APP_DIR/requirements.txt"

set_env_value() {
  local key="$1"
  local value="$2"
  "$PYTHON_BIN" - "$APP_DIR/.env" "$key" "$value" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
line = f"{key}={value}\n"
lines = env_path.read_text(encoding="utf-8").splitlines(True) if env_path.exists() else []
written = False
for idx, item in enumerate(lines):
    if item.startswith(f"{key}=") or item.startswith(f"# {key}="):
        lines[idx] = line
        written = True
        break
if not written:
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.append(line)
env_path.write_text("".join(lines), encoding="utf-8")
PY
}

install_douk_tool() {
  local existing_main
  existing_main="$(find "$DOUK_DIR" -type f -name main 2>/dev/null | head -1 || true)"
  if [[ -n "$existing_main" ]]; then
    chmod +x "$existing_main" || true
    set_env_value "DOUK_EXECUTABLE" "$existing_main"
    return 0
  fi

  local arch asset url zip_path
  arch="$(uname -m)"
  if [[ "$arch" == "arm64" ]]; then
    asset="macOS_ARM64.zip"
  else
    asset="macOS_X64.zip"
  fi

  echo "正在下载抖音采集工具（DouK/TikTokDownloader）..."
  url="$(curl -fsSL https://api.github.com/repos/JoeanAmier/TikTokDownloader/releases/latest | "$PYTHON_BIN" -c 'import json,sys; data=json.load(sys.stdin); suffix=sys.argv[1]; assets=data.get("assets", []); matches=[a.get("browser_download_url", "") for a in assets if a.get("name", "").endswith(suffix)]; print(matches[0] if matches else "")' "$asset")"
  if [[ -z "$url" ]]; then
    echo "未找到适合当前系统的 DouK 下载包，将跳过自动安装采集工具。"
    return 0
  fi

  rm -rf "$DOUK_DIR"
  mkdir -p "$DOUK_DIR"
  zip_path="$TOOLS_DIR/douk.zip"
  curl -fL "$url" -o "$zip_path"
  unzip -q "$zip_path" -d "$DOUK_DIR"
  rm -f "$zip_path"
  xattr -cr "$DOUK_DIR" 2>/dev/null || true

  existing_main="$(find "$DOUK_DIR" -type f -name main 2>/dev/null | head -1 || true)"
  if [[ -n "$existing_main" ]]; then
    chmod +x "$existing_main" || true
    set_env_value "DOUK_EXECUTABLE" "$existing_main"
    echo "抖音采集工具已安装：$existing_main"
  else
    echo "DouK 下载完成，但未找到 main 可执行文件。"
  fi
}

install_douk_tool
set_env_value "LOCAL_API_PORT" "8765"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$APP_DIR/local_api.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$APP_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/helper.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/helper.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "本机采集助手已安装并启动。"
echo "状态地址：http://127.0.0.1:8765/api/helper/status"
echo "日志目录：$LOG_DIR"
echo "助手目录：$APP_DIR"
echo "Python 环境：$PYTHON_BIN"
