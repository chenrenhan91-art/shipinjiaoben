#!/usr/bin/env bash
set -euo pipefail

LABEL="com.shipinjiaoben.collector-helper"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
rm -f "$PLIST"

echo "本机采集助手已卸载。"