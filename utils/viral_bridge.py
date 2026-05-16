"""抖音/小红书爆款内容桥接。

优先调用已验证的 GitHub 工具本地 API：
- JoeanAmier/TikTokDownloader（DouK-Downloader），默认 http://127.0.0.1:5555
- JoeanAmier/XHS-Downloader，默认 http://127.0.0.1:5556

说明：两个平台的关键词搜索/作品详情都可能受 Cookie、风控和平台策略影响。
本模块只调用本机服务或公开可访问页面，不绕过登录、验证码或权限限制。
"""
from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from config import config
from utils.text_utils import clean_text


DOUYIN_SEARCH_URL = "https://www.douyin.com/search/{keyword}"
XHS_SEARCH_URL = "https://www.xiaohongshu.com/search_result?keyword={keyword}"


def _headers(token: str = "") -> dict[str, str]:
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"}
    if token:
        headers["token"] = token
    return headers


def _normalize_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return 0
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return 0
    number = float(match.group(1))
    if "亿" in text:
        number *= 100000000
    elif "万" in text or "w" in text.lower():
        number *= 10000
    return int(number)


def _safe_get(data: Any, path: str, default: Any = "") -> Any:
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part, default)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if idx < len(cur) else default
        else:
            return default
    return cur


def _walk_dicts(data: Any, max_items: int = 300) -> list[dict[str, Any]]:
    stack = [data]
    found: list[dict[str, Any]] = []
    while stack and len(found) < max_items:
        item = stack.pop()
        if isinstance(item, dict):
            found.append(item)
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return found


def _first_text(data: dict[str, Any], paths: list[str]) -> str:
    for path in paths:
        value = _safe_get(data, path)
        if isinstance(value, str) and (value := clean_text(value)):
            return value
        if isinstance(value, (int, float)):
            return str(value)
    return ""


def _first_count(data: dict[str, Any], paths: list[str]) -> int:
    for path in paths:
        value = _safe_get(data, path)
        count = _normalize_count(value)
        if count:
            return count
    return 0


def _normalize_item(raw: dict[str, Any], platform: str, source: str) -> dict[str, Any] | None:
    title = _first_text(raw, [
        "title", "desc", "description", "display_title", "displayTitle", "content", "word",
        "aweme_info.desc", "aweme_detail.desc", "noteCard.displayTitle", "note_card.displayTitle",
        "noteCard.desc", "note_card.desc", "data.title", "data.desc",
    ])
    url = _first_text(raw, [
        "url", "share_url", "shareUrl", "web_url", "link", "href", "video_url", "下载地址.0",
        "aweme_info.share_url", "aweme_detail.share_url", "noteCard.url", "note_card.url",
    ])
    item_id = _first_text(raw, [
        "aweme_id", "id", "item_id", "note_id", "noteId", "aweme_info.aweme_id", "aweme_detail.aweme_id",
    ])
    if platform == "douyin" and not url and item_id:
        url = f"https://www.douyin.com/video/{item_id}"
    if platform == "xiaohongshu" and not url and item_id:
        url = f"https://www.xiaohongshu.com/explore/{item_id}"

    likes = _first_count(raw, [
        "likes", "like_count", "liked_count", "digg_count", "点赞数量", "statistics.digg_count",
        "stats.digg_count", "interact_info.liked_count", "noteCard.interactInfo.likedCount",
        "note_card.interact_info.liked_count", "data.likes",
    ])
    comment_count = _first_count(raw, [
        "comment_count", "commentCount", "评论数量", "statistics.comment_count", "stats.comment_count",
        "interact_info.comment_count", "noteCard.interactInfo.commentCount",
    ])
    share_count = _first_count(raw, [
        "share_count", "shareCount", "分享数量", "statistics.share_count", "stats.share_count",
    ])
    collect_count = _first_count(raw, [
        "collect_count", "collectCount", "收藏数量", "statistics.collect_count", "stats.collect_count",
    ])
    duration = _first_count(raw, ["duration", "video.duration", "video_duration", "时长"])
    script = _first_text(raw, [
        "subtitle", "字幕", "transcript", "script", "文案", "desc", "description", "title",
        "aweme_info.desc", "aweme_detail.desc", "noteCard.desc", "note_card.desc",
    ])
    comments = []
    hot_comments = _safe_get(raw, "comments_hot") or _safe_get(raw, "评论") or []
    if isinstance(hot_comments, list):
        comments = [clean_text(str(i)) for i in hot_comments[:5] if clean_text(str(i))]

    if not title and not script:
        return None
    return {
        "platform": platform,
        "source": source,
        "title": title or script[:40],
        "url": url,
        "likes": likes,
        "comment_count": comment_count,
        "share_count": share_count,
        "collect_count": collect_count,
        "duration_seconds": duration,
        "script": script,
        "comments_hot": comments,
        "raw_id": item_id,
    }


def _dedupe(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        key = item.get("url") or item.get("raw_id") or item.get("title", "")[:24]
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _merge_item(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = {**base}
    for key, value in extra.items():
        if key == "comments_hot":
            existing = merged.get(key) or []
            merged[key] = _dedupe_comments([*existing, *(value or [])])
        elif value and (not merged.get(key) or key in {"likes", "comment_count", "share_count", "collect_count", "duration_seconds"}):
            merged[key] = value
    return merged


def _dedupe_comments(comments: list[str], limit: int = 8) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for text in comments:
        text = clean_text(str(text))
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _extract_comments(data: Any, limit: int = 8) -> list[str]:
    comments: list[str] = []
    for item in _walk_dicts(data, 500):
        text = _first_text(item, ["text", "content", "comment", "评论内容", "desc"])
        if text:
            digg = _first_count(item, ["digg_count", "like_count", "likes"])
            comments.append(f"{text}（{digg}赞）" if digg else text)
    return _dedupe_comments(comments, limit)


async def _post_json(client: httpx.AsyncClient, url: str, payload: dict[str, Any], token: str = "") -> dict[str, Any]:
    resp = await client.post(url, json=payload, headers=_headers(token), timeout=18)
    resp.raise_for_status()
    return resp.json()


async def _get_text(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, headers=_headers(), timeout=18, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


async def _search_douyin(keyword: str, limit: int, status: dict[str, Any]) -> list[dict[str, Any]]:
    url = f"{config.douk_api_base.rstrip('/')}/douyin/search/video"
    payload = {
        "keyword": keyword,
        "pages": 1,
        "count": min(max(limit * 3, 10), 30),
        "sort_type": 0,
        "publish_time": 7,
        "duration": 0,
        "search_range": 0,
        "source": False,
    }
    try:
        async with httpx.AsyncClient() as client:
            data = await _post_json(client, url, payload, config.douk_api_token)
        items = [i for d in _walk_dicts(data) if (i := _normalize_item(d, "douyin", "TikTokDownloader"))]
        threshold = config.douyin_like_threshold
        viral = [i for i in items if i["likes"] >= threshold]
        result = _dedupe(viral or items, limit)
        status["douyin"] = "ok" if result else "empty"
        return result
    except httpx.HTTPStatusError as exc:
        status["douyin"] = f"unavailable: HTTP {exc.response.status_code}"
        return []
    except httpx.RequestError as exc:
        status["douyin"] = f"unavailable: {exc.__class__.__name__}"
        return []


async def _detail_douyin_by_id(detail_id: str, status: dict[str, Any]) -> dict[str, Any] | None:
    if not detail_id:
        return None
    url = f"{config.douk_api_base.rstrip('/')}/douyin/detail"
    payload = {"detail_id": detail_id, "source": False}
    try:
        async with httpx.AsyncClient() as client:
            data = await _post_json(client, url, payload, config.douk_api_token)
        for raw in _walk_dicts(data):
            item = _normalize_item(raw, "douyin", "TikTokDownloader/detail")
            if item and (item.get("raw_id") == detail_id or item.get("title")):
                return item
    except httpx.HTTPStatusError as exc:
        status.setdefault("douyin_detail_batch", f"unavailable: HTTP {exc.response.status_code}")
    except httpx.RequestError as exc:
        status.setdefault("douyin_detail_batch", f"unavailable: {exc.__class__.__name__}")
    return None


async def _comments_douyin(detail_id: str, status: dict[str, Any]) -> list[str]:
    if not detail_id:
        return []
    url = f"{config.douk_api_base.rstrip('/')}/douyin/comment"
    payload = {"detail_id": detail_id, "pages": 1, "cursor": 0, "count": 20, "source": False}
    try:
        async with httpx.AsyncClient() as client:
            data = await _post_json(client, url, payload, config.douk_api_token)
        comments = _extract_comments(data)
        if comments:
            return comments
    except httpx.HTTPStatusError as exc:
        status.setdefault("douyin_comments", f"unavailable: HTTP {exc.response.status_code}")
    except httpx.RequestError as exc:
        status.setdefault("douyin_comments", f"unavailable: {exc.__class__.__name__}")
    return []


async def _enrich_douyin_items(items: list[dict[str, Any]], status: dict[str, Any]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in items:
        if item.get("platform") != "douyin":
            enriched.append(item)
            continue
        merged = item
        detail_id = item.get("raw_id", "")
        detail = await _detail_douyin_by_id(detail_id, status)
        if detail:
            merged = _merge_item(merged, detail)
            status["douyin_detail_batch"] = "ok"
        await asyncio.sleep(1.2)
        comments = await _comments_douyin(detail_id, status)
        if comments:
            merged["comments_hot"] = _dedupe_comments([*(merged.get("comments_hot") or []), *comments])
            status["douyin_comments"] = "ok"
        enriched.append(merged)
        await asyncio.sleep(1.2)
    return enriched


async def check_douyin_status(keyword: str = "测试") -> dict[str, Any]:
    status: dict[str, Any] = {
        "bridge": "ok",
        "douyin_api_base": config.douk_api_base,
        "token_configured": bool(config.douk_api_token),
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{config.douk_api_base.rstrip('/')}/docs", timeout=5)
        status["douyin_api"] = "ok" if resp.status_code < 500 else f"HTTP {resp.status_code}"
    except httpx.RequestError as exc:
        status["douyin_api"] = f"unavailable: {exc.__class__.__name__}"
        return status

    probe: dict[str, Any] = {}
    items = await _search_douyin(keyword, 1, probe)
    status["search_probe"] = probe.get("douyin", "empty")
    status["login_hint"] = "搜索探测成功" if items else "若搜索为空/403/502，请在抖音官方页面登录并确认 DouK API Token 配置"
    return status


async def _detail_xhs(source_url: str, status: dict[str, Any]) -> list[dict[str, Any]]:
    if not source_url or "xiaohongshu.com" not in source_url and "xhslink.com" not in source_url:
        return []
    url = f"{config.xhs_api_base.rstrip('/')}/xhs/detail"
    payload = {"url": source_url, "download": False, "skip": False}
    try:
        async with httpx.AsyncClient() as client:
            data = await _post_json(client, url, payload)
        items = [i for d in _walk_dicts(data) if (i := _normalize_item(d, "xiaohongshu", "XHS-Downloader"))]
        result = _dedupe(items, 3)
        if result:
            status["xiaohongshu_detail"] = "ok"
        return result
    except httpx.HTTPStatusError as exc:
        status["xiaohongshu_detail"] = f"unavailable: HTTP {exc.response.status_code}"
        return []
    except httpx.RequestError as exc:
        status["xiaohongshu_detail"] = f"unavailable: {exc.__class__.__name__}"
        return []


async def _detail_douyin(source_url: str, status: dict[str, Any]) -> list[dict[str, Any]]:
    if not source_url or "douyin.com" not in source_url and "iesdouyin.com" not in source_url:
        return []
    match = re.search(r"(\d{16,22})", source_url)
    if not match:
        return []
    url = f"{config.douk_api_base.rstrip('/')}/douyin/detail"
    payload = {"detail_id": match.group(1), "source": False}
    try:
        async with httpx.AsyncClient() as client:
            data = await _post_json(client, url, payload, config.douk_api_token)
        items = [i for d in _walk_dicts(data) if (i := _normalize_item(d, "douyin", "TikTokDownloader"))]
        result = _dedupe(items, 3)
        if result:
            status["douyin_detail"] = "ok"
        return result
    except httpx.HTTPStatusError as exc:
        status["douyin_detail"] = f"unavailable: HTTP {exc.response.status_code}"
        return []
    except httpx.RequestError as exc:
        status["douyin_detail"] = f"unavailable: {exc.__class__.__name__}"
        return []


async def _extract_public_page(source_url: str, status: dict[str, Any]) -> str:
    if not source_url:
        return ""
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            html = await _get_text(client, source_url)
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        body = clean_text(soup.get_text(" ", strip=True))
        text = clean_text(f"{title}\n{body}")[:3000]
        if len(text) >= 80:
            status["public_page"] = "ok"
            return text
    except Exception as exc:
        status["public_page"] = f"unavailable: {exc.__class__.__name__}"
    return ""


def _items_to_source_text(items: list[dict[str, Any]], public_text: str = "") -> str:
    lines: list[str] = []
    for idx, item in enumerate(items, 1):
        lines.append(
            f"来源{idx}｜平台：{item['platform']}｜标题：{item['title']}｜点赞：{item.get('likes', 0)}｜评论：{item.get('comment_count', 0)}｜分享：{item.get('share_count', 0)}｜收藏：{item.get('collect_count', 0)}｜链接：{item.get('url', '')}"
        )
        if item.get("script"):
            lines.append(f"文案/字幕素材：{item['script'][:500]}")
        if item.get("comments_hot"):
            lines.append("热评：" + "；".join(item["comments_hot"][:3]))
    if public_text:
        lines.append("原始链接正文：" + public_text[:1500])
    return "\n".join(lines).strip()


async def search_viral_content(keyword: str, source_url: str = "", limit: int = 6) -> dict[str, Any]:
    keyword = clean_text(keyword)
    status: dict[str, Any] = {}
    items: list[dict[str, Any]] = []

    if keyword:
        items.extend(await _search_douyin(keyword, limit, status))
    items.extend(await _detail_douyin(source_url, status))
    items.extend(await _detail_xhs(source_url, status))
    public_text = await _extract_public_page(source_url, status) if source_url else ""

    items = await _enrich_douyin_items(_dedupe(items, limit), status)
    search_links = [
        {"label": "抖音关键词搜索", "url": DOUYIN_SEARCH_URL.format(keyword=quote(keyword))},
        {"label": "小红书关键词搜索", "url": XHS_SEARCH_URL.format(keyword=quote(keyword))},
    ] if keyword else []
    return {
        "keyword": keyword,
        "items": items,
        "source_text": _items_to_source_text(items, public_text),
        "search_links": search_links,
        "status": status,
        "thresholds": {
            "douyin_likes": config.douyin_like_threshold,
            "xiaohongshu_likes": config.xiaohongshu_like_threshold,
        },
        "tools": {
            "douyin": "JoeanAmier/TikTokDownloader",
            "xiaohongshu": "JoeanAmier/XHS-Downloader",
        },
    }