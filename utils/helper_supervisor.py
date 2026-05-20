"""本机采集助手监督工具。

负责检查、打开和尽量拉起本机抖音采集工具。它不会读取浏览器 Cookie，也不会绕过验证码；
登录态仍由用户在官方页面或采集工具自身配置中完成。
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

import httpx

from config import config


PROJECT_DIR = Path(__file__).resolve().parents[1]
STATE_DIR = Path.home() / ".shipinjiaoben"
LOG_DIR = STATE_DIR / "logs"
LAUNCH_AGENT_LABEL = "com.shipinjiaoben.collector-helper"
LAUNCH_AGENT_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
DOUYIN_LOGIN_URL = "https://www.douyin.com/?recommend=1"
DOUK_RELEASE_URL = "https://github.com/JoeanAmier/TikTokDownloader/releases/latest"
DOUK_COOKIE_HELP_URL = "https://github.com/JoeanAmier/TikTokDownloader/blob/master/docs/Cookie%E8%8E%B7%E5%8F%96%E6%95%99%E7%A8%8B.md"
HELPER_INSTALL_URL = "https://github.com/chenrenhan91-art/shipinjiaoben/tree/main/scripts"
BROWSER_CODES = {
    "arc": "1",
    "chrome": "2",
    "chromium": "3",
    "opera": "4",
    "brave": "6",
    "edge": "7",
    "firefox": "9",
    "safari": "11",
}


def _douk_docs_url() -> str:
    return f"{config.douk_api_base.rstrip('/')}/docs"


def _candidate_commands() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    if config.douk_start_cmd:
        candidates.append({
            "label": "自定义采集工具启动命令",
            "command": config.douk_start_cmd,
            "cwd": str(PROJECT_DIR),
            "shell": True,
        })

    if config.douk_executable:
        executable = Path(config.douk_executable).expanduser()
        if executable.exists():
            candidates.append({
                "label": "采集工具可执行文件",
                "command": [str(executable)],
                "cwd": str(executable.parent),
                "shell": False,
                "startup_input": "1\nYES\n7\n",
            })

    possible_dirs = [
        Path(config.douk_project_dir).expanduser() if config.douk_project_dir else None,
        STATE_DIR / "tools" / "TikTokDownloader",
        Path.home() / "TikTokDownloader",
        Path.home() / "Downloads" / "TikTokDownloader",
        Path.home() / "Downloads" / "DouK-Downloader",
        PROJECT_DIR / "tools" / "TikTokDownloader",
    ]
    seen: set[Path] = set()
    for maybe_dir in possible_dirs:
        if not maybe_dir:
            continue
        tool_dir = maybe_dir.resolve()
        if tool_dir in seen or not tool_dir.exists():
            continue
        seen.add(tool_dir)
        for executable_name in ("main", "main.exe"):
            executable = tool_dir / executable_name
            if executable.exists():
                candidates.append({
                    "label": "采集工具可执行文件",
                    "command": [str(executable)],
                    "cwd": str(tool_dir),
                    "shell": False,
                    "startup_input": "1\nYES\n7\n",
                })
        main_py = tool_dir / "main.py"
        if main_py.exists():
            candidates.append({
                "label": "采集工具源码入口",
                "command": [sys.executable, str(main_py)],
                "cwd": str(tool_dir),
                "shell": False,
                "startup_input": "1\nYES\n7\n",
            })
    return candidates


async def probe_douyin_tool() -> dict[str, Any]:
    url = _douk_docs_url()
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.get(url, timeout=5)
        ok = resp.status_code == 200
        return {
            "ok": ok,
            "status": "ok" if ok else f"http_{resp.status_code}",
            "status_code": resp.status_code,
            "url": url,
        }
    except httpx.RequestError as exc:
        return {
            "ok": False,
            "status": "not_running",
            "error": exc.__class__.__name__,
            "url": url,
        }


async def _wait_for_douyin_tool(timeout_seconds: int = 15) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last = await probe_douyin_tool()
    while asyncio.get_running_loop().time() < deadline:
        if last.get("ok"):
            return last
        await asyncio.sleep(1)
        last = await probe_douyin_tool()
    return last


def _launch_process(candidate: dict[str, Any]) -> dict[str, Any]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "douyin_tool.log"
    output = log_file.open("ab")
    startup_input = candidate.get("startup_input")
    process = subprocess.Popen(
        candidate["command"],
        cwd=candidate.get("cwd") or str(PROJECT_DIR),
        shell=bool(candidate.get("shell")),
        stdin=subprocess.PIPE if startup_input else subprocess.DEVNULL,
        stdout=output,
        stderr=output,
        start_new_session=True,
    )
    if startup_input and process.stdin:
        process.stdin.write(startup_input.encode("utf-8"))
        process.stdin.close()
    return {"pid": process.pid, "log_file": str(log_file), "label": candidate.get("label", "采集工具")}


def _menu_candidate() -> dict[str, Any] | None:
    for candidate in _candidate_commands():
        if candidate.get("startup_input"):
            return candidate
    return None


def _find_settings_file(candidate: dict[str, Any] | None = None) -> Path | None:
    roots: list[Path] = []
    if candidate and candidate.get("cwd"):
        roots.append(Path(str(candidate["cwd"])).expanduser())
    roots.extend([STATE_DIR / "tools" / "DouK-Downloader", PROJECT_DIR / "tools" / "TikTokDownloader"])
    for root in roots:
        if not root.exists():
            continue
        known = [root / "_internal" / "Volume" / "settings.json", root / "Volume" / "settings.json", root / "settings.json"]
        for item in known:
            if item.exists():
                return item
        found = next(root.rglob("settings.json"), None)
        if found:
            return found
    return None


def _cookie_status(candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = _find_settings_file(candidate)
    if not settings:
        return {"configured": False, "length": 0, "settings_file": ""}
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except Exception:
        return {"configured": False, "length": 0, "settings_file": str(settings)}
    raw_cookie = data.get("cookie") or ""
    if isinstance(raw_cookie, dict):
        cookie = "; ".join(f"{key}={value}" for key, value in raw_cookie.items())
    elif isinstance(raw_cookie, list):
        cookie = "; ".join(str(item) for item in raw_cookie)
    else:
        cookie = str(raw_cookie)
    parts = {}
    for item in cookie.split(";"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        parts[key.strip()] = value.strip()
    logged_in = any(parts.get(marker) for marker in ("sessionid", "sid_guard", "sid_tt", "passport_csrf_token")) or len(cookie) > 200
    return {"configured": logged_in, "length": len(cookie), "settings_file": str(settings)}


def _stop_douyin_tool() -> list[int]:
    if platform.system() == "Windows":
        return []
    try:
        result = subprocess.run(["lsof", "-tiTCP:5555", "-sTCP:LISTEN"], capture_output=True, text=True, timeout=5)
    except Exception:
        return []
    pids = [int(line) for line in result.stdout.splitlines() if line.strip().isdigit()]
    for pid in pids:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    return pids


async def import_douyin_cookie_from_browser(browser: str = "chrome") -> dict[str, Any]:
    candidate = _menu_candidate()
    if not candidate:
        return {
            "ok": False,
            "status": "tool_not_installed",
            "message": "未找到可导入登录状态的抖音采集工具，请先安装本机助手。",
            "release_url": DOUK_RELEASE_URL,
        }
    browser_code = BROWSER_CODES.get(browser.lower(), browser)
    if not str(browser_code).isdigit():
        browser_code = "2"

    stopped = _stop_douyin_tool()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "douyin_cookie_import.log"
    with log_file.open("ab") as output:
        try:
            subprocess.run(
                candidate["command"],
                cwd=candidate.get("cwd") or str(PROJECT_DIR),
                shell=bool(candidate.get("shell")),
                input=f"2\n{browser_code}\n".encode("utf-8"),
                stdout=output,
                stderr=output,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "status": "timeout", "message": "导入登录状态超时，请确认浏览器已登录抖音。", "log_file": str(log_file)}

    cookie = _cookie_status(candidate)
    start = await ensure_douyin_tool_started()
    return {
        "ok": cookie["configured"],
        "status": "ok" if cookie["configured"] else "cookie_empty",
        "cookie": cookie,
        "stopped_pids": stopped,
        "start": start,
        "log_file": str(log_file),
        "message": "已从本机浏览器导入抖音登录状态，并重启采集工具。" if cookie["configured"] else "未读取到抖音登录状态，请先在所选浏览器登录抖音。",
    }


async def set_douyin_cookie_direct(cookie: str) -> dict[str, Any]:
    """直接向 TikTokDownloader /settings 接口写入 Cookie 字符串，无需手动操作工具菜单。"""
    cookie = (cookie or "").strip()
    if not cookie:
        return {"ok": False, "status": "empty", "message": "Cookie 不能为空"}
    # Step 1: POST to TikTokDownloader API（更新内存，立即生效）
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            await client.post(
                f"{config.douk_api_base.rstrip('/')}/settings",
                json={"cookie": cookie},
                timeout=8,
            )
    except Exception as exc:
        return {"ok": False, "status": "api_error", "message": f"写入失败：{exc}"}
    # Step 2: 同时写入 settings.json 文件，重启后也能保留
    candidate = _menu_candidate()
    settings_file = _find_settings_file(candidate)
    if settings_file and settings_file.exists():
        try:
            data = json.loads(settings_file.read_text(encoding="utf-8"))
            data["cookie"] = cookie
            settings_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass  # API 写入已完成，文件写入尽力而为
    result = _cookie_status(candidate)
    return {
        "ok": result["configured"],
        "status": "ok" if result["configured"] else "cookie_invalid",
        "cookie": result,
        "message": "Cookie 已写入并检测到有效登录态 ✓" if result["configured"]
                   else "Cookie 已写入，但未检测到 sessionid 等关键字段，请确认 Cookie 来自已登录抖音的浏览器页面",
    }


async def ensure_douyin_tool_started() -> dict[str, Any]:
    before = await probe_douyin_tool()
    if before.get("ok"):
        return {"ok": True, "status": "already_running", "probe": before, "message": "抖音采集工具已运行"}
    if before.get("status_code"):
        return {
            "ok": False,
            "status": "tool_unhealthy",
            "probe": before,
            "message": "检测到抖音采集工具端口已响应，但服务处于异常状态；请重启采集工具或重新完成首次 Cookie 配置。",
            "release_url": DOUK_RELEASE_URL,
            "cookie_help_url": DOUK_COOKIE_HELP_URL,
        }

    candidates = _candidate_commands()
    if not candidates:
        return {
            "ok": False,
            "status": "not_configured",
            "probe": before,
            "message": "未找到可自动启动的抖音采集工具，请先完成一次性安装或设置 DOUK_START_CMD。",
            "release_url": DOUK_RELEASE_URL,
            "cookie_help_url": DOUK_COOKIE_HELP_URL,
        }

    attempts: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            launched = _launch_process(candidate)
            probe = await _wait_for_douyin_tool(15)
            attempts.append({**launched, "probe": probe})
            if probe.get("ok"):
                return {
                    "ok": True,
                    "status": "started",
                    "probe": probe,
                    "attempts": attempts,
                    "message": "已自动启动抖音采集工具",
                }
        except Exception as exc:
            attempts.append({"label": candidate.get("label"), "error": f"{exc.__class__.__name__}: {exc}"})

    return {
        "ok": False,
        "status": "start_failed",
        "probe": await probe_douyin_tool(),
        "attempts": attempts,
        "message": "已尝试自动启动，但采集工具未进入可用状态；首次使用通常需要先在采集工具中写入 Cookie 并选择 Web API 模式。",
        "release_url": DOUK_RELEASE_URL,
        "cookie_help_url": DOUK_COOKIE_HELP_URL,
    }


async def helper_status() -> dict[str, Any]:
    candidates = _candidate_commands()
    candidate = _menu_candidate()
    douyin_tool = await probe_douyin_tool()
    # 读取安装时写入的版本号
    version = ""
    try:
        version = (PROJECT_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return {
        "ok": True,
        "helper": "running",
        "version": version,
        "project_dir": str(PROJECT_DIR),
        "python": sys.executable,
        "port": config.local_api_port,
        "platform": platform.system(),
        "autostart": {
            "supported": platform.system() == "Darwin",
            "installed": LAUNCH_AGENT_PATH.exists() if platform.system() == "Darwin" else False,
            "label": LAUNCH_AGENT_LABEL,
        },
        "douyin_tool": douyin_tool,
        "douyin_cookie": _cookie_status(candidate),
        "can_auto_start_douyin_tool": bool(candidates),
        "candidate_count": len(candidates),
        "install_url": HELPER_INSTALL_URL,
        "douyin_release_url": DOUK_RELEASE_URL,
        "cookie_help_url": DOUK_COOKIE_HELP_URL,
    }


def open_douyin_login_page(keyword: str = "") -> dict[str, Any]:
    url = DOUYIN_LOGIN_URL
    webbrowser.open(url)
    return {"ok": True, "url": url, "message": "已打开抖音官方页面，请扫码登录"}


def open_douyin_search_page(keyword: str = "财经热点") -> dict[str, Any]:
    from urllib.parse import quote

    url = f"https://www.douyin.com/search/{quote(keyword or '财经热点')}"
    webbrowser.open(url)
    return {"ok": True, "url": url, "message": "已打开抖音关键词搜索页"}
