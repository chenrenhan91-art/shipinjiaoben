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
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from config import config
from utils.text_utils import clean_text


DOUYIN_SEARCH_URL = "https://www.douyin.com/search/{keyword}"
XHS_SEARCH_URL = "https://www.xiaohongshu.com/search_result?keyword={keyword}"
DOUYIN_HOT_ENDPOINTS = [
    "https://www.douyin.com/aweme/v1/web/hot/search/list/",
    "https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/",
]
DOUYIN_KEYWORD_GROUPS = {
    "财经热点": ["财经", "经济", "股市", "A股", "港股", "美股", "基金", "银行", "券商", "保险", "房价", "楼市", "地产", "消费", "企业", "裁员", "招聘", "薪资", "美联储", "人民币", "美元", "关税", "降息", "加息", "通胀", "油价", "黄金"],
    "AI": ["AI", "人工智能", "大模型", "机器人", "芯片", "算力", "OpenAI", "英伟达", "DeepSeek", "智能体", "自动驾驶"],
    "职场": ["职场", "裁员", "招聘", "薪资", "加班", "就业", "考公", "副业", "离职", "公司", "老板"],
    "房产": ["房产", "楼市", "房价", "买房", "卖房", "租房", "房贷", "地产", "小区", "物业"],
    "美妆": ["美妆", "护肤", "口红", "面膜", "防晒", "彩妆", "穿搭", "变美", "医美"],
}
URL_RE = re.compile(r"https?://[^\s'\"<>，。；、）)】」]+", re.I)


def _extract_first_url(value: str) -> str:
    text = clean_text(value)
    if not text:
        return ""
    match = URL_RE.search(text)
    url = match.group(0) if match else text
    url = url.strip().rstrip(".,;:!?，。；：！？）)]】」\"'")
    return url if re.match(r"^https?://", url, re.I) else ""


async def _resolve_source_url(source_url: str, status: dict[str, Any]) -> str:
    url = _extract_first_url(source_url)
    if not url:
        status["source_url"] = "invalid"
        return ""
    try:
        async with httpx.AsyncClient(follow_redirects=True, trust_env=False) as client:
            resp = await client.get(url, headers=_headers(), timeout=12)
        resolved = str(resp.url) or url
        if resolved != url:
            status["source_resolved_url"] = resolved
        if resp.status_code >= 400:
            status.setdefault("source_resolve", f"HTTP {resp.status_code}")
        return resolved
    except httpx.RequestError as exc:
        status.setdefault("source_resolve", f"unavailable: {exc.__class__.__name__}")
        return url


def _readable_text_from_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    meta_parts: list[str] = []
    for selector in [
        {"property": "og:title"},
        {"property": "og:description"},
        {"name": "description"},
        {"name": "keywords"},
    ]:
        tag = soup.find("meta", attrs=selector)
        content = tag.get("content", "") if tag else ""
        if content:
            meta_parts.append(content)
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    body = soup.get_text(" ", strip=True)
    return clean_text("\n".join([title, *meta_parts, body]))


def _is_useful_public_text(text: str) -> bool:
    if len(clean_text(text)) < 80:
        return False
    blocked_markers = ["验证码", "安全验证", "请完成验证", "enable javascript", "access denied"]
    lower = text.lower()
    return not any(marker in lower for marker in blocked_markers)


def _headers(token: str = "") -> dict[str, str]:
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"}
    if token:
        headers["token"] = token
    return headers


def _normalize_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
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


def _normalize_hot_word(raw: dict[str, Any], source: str, position: int) -> dict[str, Any] | None:
    word = clean_text(str(raw.get("word") or raw.get("sentence") or raw.get("title") or ""))
    if not word:
        return None
    hot_value = _normalize_count(raw.get("hot_value") or raw.get("hotValue") or raw.get("heat_score"))
    rank = _normalize_count(raw.get("position") or raw.get("rank") or raw.get("max_rank")) or position
    video_count = _normalize_count(raw.get("video_count") or raw.get("discuss_video_count"))
    sentence_id = clean_text(str(raw.get("sentence_id") or raw.get("group_id") or ""))
    summary_parts = [f"抖音热榜第 {rank} 名"]
    if hot_value:
        summary_parts.append(f"热度 {hot_value:,}")
    if video_count:
        summary_parts.append(f"相关视频 {video_count} 条")
    return {
        "platform": "douyin",
        "source": source,
        "source_type": "hot_word",
        "title": word,
        "url": DOUYIN_SEARCH_URL.format(keyword=quote(word)),
        "likes": 0,
        "hot_value": hot_value,
        "heat_score": hot_value,
        "comment_count": 0,
        "share_count": 0,
        "collect_count": 0,
        "duration_seconds": 0,
        "script": "；".join(summary_parts) + "。",
        "comments_hot": [],
        "raw_id": sentence_id or f"douyin_hot_{rank}_{word}",
        "position": rank,
        "video_count": video_count,
    }


def _keyword_terms(keyword: str) -> list[str]:
    keyword = clean_text(keyword)
    if not keyword:
        return []
    terms = [keyword]
    keyword_lower = keyword.lower()
    for group, values in DOUYIN_KEYWORD_GROUPS.items():
        values_lower = [value.lower() for value in values]
        if keyword == group or keyword_lower == group.lower() or keyword_lower in values_lower:
            terms.extend(values)
        elif any(value in keyword or value.lower() in keyword_lower for value in values):
            terms.extend(values)
    return [term for term in dict.fromkeys(clean_text(term) for term in terms) if term]


def _hot_word_relevance(item: dict[str, Any], keyword: str) -> int:
    title = clean_text(str(item.get("title") or ""))
    if not title:
        return 0
    title_lower = title.lower()
    score = 0
    for term in _keyword_terms(keyword):
        term_lower = term.lower()
        if term == title:
            score += 40
        elif term in title or term_lower in title_lower:
            score += 20
        elif title in term:
            score += 8
    return score


def _keyword_matches_hot_word(item: dict[str, Any], keyword: str) -> bool:
    return _hot_word_relevance(item, keyword) > 0


def _core_video_score(item: dict[str, Any]) -> int:
    return (
        int(item.get("likes") or 0)
        + int(item.get("comment_count") or 0) * 5
        + int(item.get("share_count") or 0) * 8
        + int(item.get("collect_count") or 0) * 3
    )


def _video_search_terms(keyword: str, limit: int = 6) -> list[str]:
    terms = _keyword_terms(keyword) or [clean_text(keyword)]
    return [term for term in dict.fromkeys(terms) if term][:limit]


def _indexed_result_url(href: str) -> str:
    href = clean_text(href)
    if not href:
        return ""
    if href.startswith("//"):
        href = f"https:{href}"
    parsed = urlparse(href)
    for key in ("uddg", "u"):
        values = parse_qs(parsed.query).get(key) or []
        for value in values:
            decoded = unquote(value)
            if "douyin.com/video/" in decoded:
                return decoded
    return href if "douyin.com/video/" in href else ""


def _douyin_video_ids_from_text(text: str) -> list[str]:
    expanded = text
    for _ in range(2):
        expanded = unquote(expanded)
    ids = re.findall(r"(?:douyin\.com/video/|/video/|video%2F)(\d{16,22})", expanded, re.I)
    return [item_id for item_id in dict.fromkeys(ids) if item_id]


def _indexed_candidates_from_markdown(text: str, term: str, limit: int) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    sections = re.split(r"\n##\s+", f"\n{text}")
    for section in sections:
        match = re.match(r"\[([^\]]+)\]\(([^)]+)\)", section.strip())
        title = clean_text(match.group(1)) if match else ""
        href = _indexed_result_url(match.group(2)) if match else ""
        block_text = clean_text(section)
        ids = _douyin_video_ids_from_text(f"{href} {block_text}")
        if not ids:
            continue
        item_id = ids[0]
        candidates.append({
            "raw_id": item_id,
            "title": title or block_text[:80],
            "url": href or f"https://www.douyin.com/video/{item_id}",
            "script": block_text,
            "search_term": term,
        })
        if len(candidates) >= limit:
            break
    return _dedupe(candidates, limit)


def _indexed_candidates_from_html(text: str, term: str, limit: int) -> list[dict[str, str]]:
    soup = BeautifulSoup(text, "lxml")
    candidates: list[dict[str, str]] = []
    for result in soup.select(".result"):
        link = result.select_one("a.result__a") or result.find("a")
        if not link:
            continue
        title = clean_text(link.get_text(" ", strip=True))
        href = _indexed_result_url(str(link.get("href") or ""))
        block_text = clean_text(result.get_text(" ", strip=True))
        ids = _douyin_video_ids_from_text(f"{href} {block_text}")
        if not ids:
            continue
        item_id = ids[0]
        candidates.append({
            "raw_id": item_id,
            "title": title or block_text[:80],
            "url": href or f"https://www.douyin.com/video/{item_id}",
            "script": block_text,
            "search_term": term,
        })
        if len(candidates) >= limit:
            break
    return _dedupe(candidates, limit)


async def _search_indexed_douyin_candidates(term: str, limit: int, status: dict[str, Any]) -> list[dict[str, str]]:
    query = f"site:douyin.com/video {term} 抖音"
    jina_url = f"https://r.jina.ai/http://duckduckgo.com/html/?q={quote(query)}"
    endpoints = [
        (jina_url, None, "markdown"),
        ("https://html.duckduckgo.com/html/", {"q": query}, "html"),
        ("https://duckduckgo.com/html/", {"q": query}, "html"),
    ]
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    errors: list[str] = []
    for endpoint, params, parser in endpoints:
        try:
            async with httpx.AsyncClient(trust_env=False, follow_redirects=True) as client:
                resp = await client.get(endpoint, params=params, headers=headers, timeout=25)
            resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                errors.append(f"{endpoint}: HTTP {exc.response.status_code}")
            else:
                errors.append(f"{endpoint}: {exc.__class__.__name__}")
            continue

        candidates = (
            _indexed_candidates_from_markdown(resp.text, term, limit)
            if parser == "markdown"
            else _indexed_candidates_from_html(resp.text, term, limit)
        )
        if candidates:
            status.setdefault("douyin_index_source", endpoint)
            return candidates
        errors.append(f"{endpoint}: empty")

    if errors:
        status.setdefault("douyin_index_error", " | ".join(errors[:2]))
    return []


async def _search_indexed_douyin_videos_by_terms(terms: list[str], limit: int, status: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, str]] = []
    term_states: dict[str, str] = {}
    for term in terms:
        term_candidates = await _search_indexed_douyin_candidates(term, max(limit, 8), status)
        term_states[term] = "ok" if term_candidates else "empty"
        candidates.extend(term_candidates)
        candidates = _dedupe(candidates, limit * 4)
        if len(candidates) >= limit * 3:
            break

    items: list[dict[str, Any]] = []
    for candidate in candidates[: limit * 3]:
        base = {
            "platform": "douyin",
            "source": "公开搜索索引 + DouK详情",
            "source_type": "video_fallback",
            "title": candidate.get("title", ""),
            "url": candidate.get("url") or f"https://www.douyin.com/video/{candidate.get('raw_id', '')}",
            "likes": 0,
            "comment_count": 0,
            "share_count": 0,
            "collect_count": 0,
            "duration_seconds": 0,
            "script": candidate.get("script", ""),
            "comments_hot": [],
            "raw_id": candidate.get("raw_id", ""),
            "search_term": candidate.get("search_term", ""),
        }
        detail = await _detail_douyin_by_id(base["raw_id"], status)
        item = _merge_item(base, detail) if detail else base
        if detail:
            item["title"] = detail.get("title") or item.get("title", "")
            item["script"] = detail.get("script") or item.get("script", "")
        item["source_type"] = "video_fallback"
        item["search_term"] = base["search_term"]
        item["core_score"] = _core_video_score(item)
        item["detail_resolved"] = bool(detail)
        if item.get("core_score"):
            items.append(item)
        await asyncio.sleep(0.4)

    items.sort(key=lambda item: (item.get("core_score") or 0, item.get("likes") or 0), reverse=True)
    result = _dedupe(items, limit)
    status["douyin_index_term_status"] = term_states
    status["douyin_index_fallback"] = "ok" if result else "empty"
    return result


async def _search_douyin_videos_by_terms(keyword: str, limit: int, status: dict[str, Any]) -> list[dict[str, Any]]:
    terms = _video_search_terms(keyword)
    if not terms:
        status["douyin_video_fallback"] = "empty:no_keyword"
        return []
    found: list[dict[str, Any]] = []
    term_states: dict[str, str] = {}
    for term in terms:
        term_status: dict[str, Any] = {}
        term_items = await _search_douyin(term, limit, term_status)
        term_states[term] = term_status.get("douyin", "empty")
        for item in term_items:
            item["source_type"] = "video_fallback"
            item["search_term"] = term
            item["core_score"] = _core_video_score(item)
        found.extend(term_items)
        if len(_dedupe(found, limit * 2)) >= limit * 2:
            break
    unique = _dedupe(found, limit * 3)
    unique.sort(key=lambda item: (item.get("core_score") or _core_video_score(item), item.get("likes") or 0), reverse=True)
    result = _dedupe(unique, limit)
    if not result:
        result = await _search_indexed_douyin_videos_by_terms(terms, limit, status)
    status["douyin_video_terms"] = terms
    status["douyin_video_term_status"] = term_states
    status["douyin_video_fallback"] = "ok" if result else "empty"
    return result


async def _fetch_douyin_hot_words(keyword: str, limit: int, status: dict[str, Any]) -> list[dict[str, Any]]:
    headers = {**_headers(), "Referer": "https://www.douyin.com/"}
    errors: list[str] = []
    for endpoint in DOUYIN_HOT_ENDPOINTS:
        try:
            async with httpx.AsyncClient(trust_env=False, follow_redirects=True) as client:
                resp = await client.get(endpoint, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPStatusError, httpx.RequestError, ValueError) as exc:
            errors.append(f"{endpoint}: {exc.__class__.__name__}")
            continue

        source_name = "抖音热榜"
        container = data.get("data") if isinstance(data.get("data"), dict) else data
        raw_words: list[dict[str, Any]] = []
        for key in ("word_list", "trending_list"):
            value = container.get(key) if isinstance(container, dict) else None
            if isinstance(value, list):
                raw_words.extend([item for item in value if isinstance(item, dict)])
        if not raw_words:
            errors.append(f"{endpoint}: empty")
            continue

        items = [
            item
            for idx, raw in enumerate(raw_words, 1)
            if (item := _normalize_hot_word(raw, source_name, idx))
        ]
        items = _dedupe(items, max(limit * 3, limit))
        if clean_text(keyword):
            matched = [item for item in items if _keyword_matches_hot_word(item, keyword)]
            matched.sort(key=lambda item: (_hot_word_relevance(item, keyword), item.get("hot_value", 0)), reverse=True)
            result = _dedupe(matched, limit)
        else:
            result = _dedupe(items, limit)
        if result:
            status["douyin_hot"] = "ok"
            status["douyin_hot_source"] = endpoint
            if clean_text(keyword):
                status["douyin_hot_filter"] = "keyword_matched"
            return result

        if clean_text(keyword):
            status["douyin_hot"] = "empty:keyword_no_match"
            status["douyin_hot_source"] = endpoint
            return []

    status["douyin_hot"] = "unavailable" if errors else "empty"
    if errors:
        status["douyin_hot_error"] = " | ".join(errors[:2])
    return []


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
        async with httpx.AsyncClient(trust_env=False) as client:
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
        async with httpx.AsyncClient(trust_env=False) as client:
            data = await _post_json(client, url, payload, config.douk_api_token)
        candidates: list[dict[str, Any]] = []
        for raw in _walk_dicts(data):
            item = _normalize_item(raw, "douyin", "TikTokDownloader/detail")
            if item and item.get("raw_id") == detail_id:
                return item
            if item:
                candidates.append(item)
        if candidates:
            candidates.sort(key=lambda item: (_core_video_score(item), bool(item.get("raw_id"))), reverse=True)
            return candidates[0]
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
        async with httpx.AsyncClient(trust_env=False) as client:
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
        if item.get("platform") != "douyin" or item.get("source_type") == "hot_word" or item.get("detail_resolved"):
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
        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.get(f"{config.douk_api_base.rstrip('/')}/docs", timeout=5)
        status["douyin_api"] = "ok" if resp.status_code < 500 else f"HTTP {resp.status_code}"
    except httpx.RequestError as exc:
        status["douyin_api"] = f"unavailable: {exc.__class__.__name__}"
        return status

    probe: dict[str, Any] = {}
    items = await _search_douyin(keyword, 1, probe)
    status["search_probe"] = probe.get("douyin", "empty")
    hot_probe: dict[str, Any] = {}
    hot_items = [] if items else await _fetch_douyin_hot_words(keyword, 3, hot_probe)
    if hot_items:
        status["hot_probe"] = "ok"
        status["hot_count"] = len(hot_items)
    status["login_hint"] = "搜索探测成功" if items else (
        "作品搜索暂不可用，但抖音热榜可用" if hot_items else "若搜索为空/403/500/502，请重新导入登录态；若仍为 500，通常是 DouK 搜索接口拿到空结果后内部报错"
    )
    return status


async def _detail_xhs(source_url: str, status: dict[str, Any]) -> list[dict[str, Any]]:
    source_url = _extract_first_url(source_url)
    if not source_url or "xiaohongshu.com" not in source_url and "xhslink.com" not in source_url:
        return []
    url = f"{config.xhs_api_base.rstrip('/')}/xhs/detail"
    payload = {"url": source_url, "download": False, "skip": False}
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
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
    source_url = _extract_first_url(source_url)
    if not source_url or "douyin.com" not in source_url and "iesdouyin.com" not in source_url:
        return []
    resolved_url = await _resolve_source_url(source_url, status)
    match = re.search(r"(\d{16,22})", f"{source_url} {resolved_url}")
    if not match:
        status.setdefault("douyin_detail", "unavailable: missing detail id")
        return []
    url = f"{config.douk_api_base.rstrip('/')}/douyin/detail"
    payload = {"detail_id": match.group(1), "source": False}
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
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
    source_url = _extract_first_url(source_url)
    if not source_url:
        return ""
    resolved_url = await _resolve_source_url(source_url, status)
    urls = [u for i, u in enumerate([resolved_url, source_url]) if u and u not in [resolved_url, source_url][:i]]
    try:
        async with httpx.AsyncClient(follow_redirects=True, trust_env=False) as client:
            for url in urls:
                html = await _get_text(client, url)
                text = _readable_text_from_html(html)[:3000]
                if _is_useful_public_text(text):
                    status["public_page"] = "ok"
                    return text
    except Exception as exc:
        status["public_page"] = f"unavailable: {exc.__class__.__name__}"
    for url in urls:
        try:
            reader_url = f"https://r.jina.ai/http://{url}"
            async with httpx.AsyncClient(follow_redirects=True, trust_env=False) as client:
                text = clean_text(await _get_text(client, reader_url))[:3000]
            if _is_useful_public_text(text):
                status["public_page"] = "ok:jina"
                return text
        except Exception as exc:
            status.setdefault("public_page_reader", f"unavailable: {exc.__class__.__name__}")
    return ""


def _items_to_source_text(items: list[dict[str, Any]], public_text: str = "") -> str:
    lines: list[str] = []
    for idx, item in enumerate(items, 1):
        heat = item.get("hot_value") or item.get("heat_score") or 0
        if item.get("source_type") == "hot_word":
            heat_part = f"｜热度：{heat}" if heat else ""
            position_part = f"｜排名：{item.get('position')}" if item.get("position") else ""
            video_part = f"｜相关视频：{item.get('video_count')}条" if item.get("video_count") else ""
            lines.append(
                f"来源{idx}｜平台：抖音｜来源：{item.get('source', '')}｜标题：{item['title']}{position_part}{heat_part}{video_part}｜链接：{item.get('url', '')}"
            )
        else:
            lines.append(
                f"来源{idx}｜平台：{item['platform']}｜来源：{item.get('source', '')}｜标题：{item['title']}｜点赞：{item.get('likes', 0)}｜评论：{item.get('comment_count', 0)}｜分享：{item.get('share_count', 0)}｜收藏：{item.get('collect_count', 0)}｜链接：{item.get('url', '')}"
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
    source_url = _extract_first_url(source_url)
    status: dict[str, Any] = {}
    items: list[dict[str, Any]] = []

    items.extend(await _detail_douyin(source_url, status))
    items.extend(await _detail_xhs(source_url, status))
    if keyword:
        items.extend(await _search_douyin(keyword, limit, status))
    if keyword and not any(item.get("platform") == "douyin" for item in items):
        search_status = status.get("douyin")
        hot_items = await _fetch_douyin_hot_words(keyword, limit, status)
        if hot_items:
            items.extend(hot_items)
            if search_status:
                status["douyin_search"] = search_status
            status["douyin"] = "ok:hot_list"
        elif str(status.get("douyin_hot", "")).startswith("empty:keyword_no_match"):
            video_items = await _search_douyin_videos_by_terms(keyword, limit, status)
            if video_items:
                items.extend(video_items)
                if search_status:
                    status["douyin_search"] = search_status
                status["douyin"] = "ok:video_fallback"
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


async def extract_source_content(source_url: str) -> dict[str, Any]:
    source_url = _extract_first_url(source_url)
    status: dict[str, Any] = {}
    if not source_url:
        return {
            "ok": False,
            "source_url": "",
            "items": [],
            "source_text": "",
            "status": {"source_url": "invalid"},
        }

    items: list[dict[str, Any]] = []
    items.extend(await _detail_douyin(source_url, status))
    items.extend(await _detail_xhs(source_url, status))
    public_text = await _extract_public_page(source_url, status)
    items = await _enrich_douyin_items(_dedupe(items, 3), status)
    source_text = _items_to_source_text(items, public_text)
    return {
        "ok": bool(source_text),
        "source_url": source_url,
        "items": items,
        "source_text": source_text,
        "status": status,
    }