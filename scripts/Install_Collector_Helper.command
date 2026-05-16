#!/bin/bash
set -euo pipefail

REPO_ZIP="https://github.com/chenrenhan91-art/shipinjiaoben/archive/refs/heads/main.zip"
SITE_URL="https://chenrenhan91-art.github.io/shipinjiaoben/"
WORK_DIR="$(mktemp -d /tmp/shipinjiaoben-installer.XXXXXX)"
ZIP_FILE="$WORK_DIR/shipinjiaoben.zip"

clear
echo "短视频爆款脚本 AI Agent - 本机采集助手安装器"
echo "================================================"
echo ""
echo "正在下载最新安装包..."
curl -fL "$REPO_ZIP" -o "$ZIP_FILE"

echo "正在解压..."
unzip -q "$ZIP_FILE" -d "$WORK_DIR"
PROJECT_DIR="$WORK_DIR/shipinjiaoben-main"

if [[ ! -f "$PROJECT_DIR/scripts/install_macos_helper.sh" ]]; then
  echo "安装包结构不正确：未找到 scripts/install_macos_helper.sh"
  read -n 1 -s -r -p "按任意键关闭..."
  exit 1
fi

echo "正在安装本机采集助手和抖音采集工具..."
chmod +x "$PROJECT_DIR/scripts/install_macos_helper.sh"
"$PROJECT_DIR/scripts/install_macos_helper.sh"

echo ""
echo "安装完成。"
echo "请回到网页点击「检测采集」，或刷新网页继续使用。"
open "$SITE_URL" >/dev/null 2>&1 || true

echo ""
read -n 1 -s -r -p "按任意键关闭..."
