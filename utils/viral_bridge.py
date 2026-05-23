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
from datetime import datetime, timedelta, timezone
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
DOUYIN_MIN_VIDEO_LIKES = 10000   # 保留供参考，过滤主要依赖综合互动评分
# 综合互动评分门槛：赞 + 评论×5 + 转发×8 + 收藏×3
# 约等于：1万赞+正常互动比例，用于拦截无热度低质视频
DOUYIN_MIN_ENGAGEMENT_SCORE = 15000
DOUYIN_MAX_VIDEO_AGE_DAYS = 21
DOUYIN_DIRECT_SEARCH_MAX_TERMS = 2
DOUYIN_INDEX_FALLBACK_MAX_SECONDS = 60
URL_RE = re.compile(r"https?://[^\s'\"<>，。；、）)】」]+", re.I)
DOUYIN_TERM_EXPANSIONS = {
    "财经": ["财经", "金融", "股市", "A股", "基金", "理财"],
    "金融": ["金融", "财经", "银行", "基金", "证券", "理财"],
    "股市": ["股市", "A股", "股票", "指数", "沪指", "创业板"],
    "A股": ["A股", "股市", "股票", "沪指", "创业板", "涨停"],
    "黄金": ["黄金", "金价", "国际金价", "黄金投资"],
    "AI": ["AI", "人工智能", "大模型", "算力", "芯片", "英伟达"],
    "人工智能": ["人工智能", "AI", "大模型", "算力", "芯片"],
    "芯片": ["芯片", "半导体", "国产芯片", "英伟达", "台积电"],
    "新能源": ["新能源", "电动车", "电池", "光伏", "储能"],
    "房产": ["房产", "楼市", "房价", "房贷", "地产"],
}
DOUYIN_SEARCH_KEY_TERMS = [
    "上海黄金交易所", "黄金交易所", "证券交易所", "北京证券交易所", "深圳证券交易所", "上海证券交易所",
    "美联储", "央行", "证监会", "中国人民银行", "财政部", "商务部",
    "A股", "港股", "美股", "股市", "股票", "基金", "证券", "券商", "银行", "保险", "理财",
    "黄金", "金价", "油价", "原油", "汇率", "人民币", "美元", "债券", "国债", "期货",
    "AI", "人工智能", "大模型", "算力", "芯片", "半导体", "英伟达", "特斯拉", "OpenAI", "DeepSeek",
    "新能源", "电池", "光伏", "储能", "机器人", "自动驾驶", "电动车", "低空经济", "商业航天",
    "成交", "上涨", "下跌", "收涨", "收跌", "涨停", "跌停", "融资", "回购", "并购", "增持", "减持",
]
DOUYIN_BROAD_KEYWORDS = set(DOUYIN_KEYWORD_GROUPS.keys()) | {"财经", "金融", "股市", "A股", "AI", "房产", "职场"}


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


def _normalize_timestamp(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        timestamp = int(value)
        return timestamp // 1000 if timestamp > 100000000000 else timestamp
    text = clean_text(str(value))
    if not text:
        return 0
    if re.fullmatch(r"\d{10,13}", text):
        timestamp = int(text)
        return timestamp // 1000 if timestamp > 100000000000 else timestamp
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        pass
    for fmt, size in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10), ("%Y/%m/%d %H:%M:%S", 19), ("%Y/%m/%d", 10)):
        try:
            return int(datetime.strptime(text[:size], fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    return 0


def _first_timestamp(data: dict[str, Any], paths: list[str]) -> int:
    for path in paths:
        timestamp = _normalize_timestamp(_safe_get(data, path))
        if timestamp:
            return timestamp
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
    publish_timestamp = _first_timestamp(raw, [
        "create_timestamp", "create_time", "publish_time", "publishTime", "timestamp",
        "aweme_info.create_time", "aweme_detail.create_time", "aweme_info.create_timestamp", "aweme_detail.create_timestamp",
        "data.create_timestamp", "data.create_time",
    ])
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
        "publish_timestamp": publish_timestamp,
        "publish_time": datetime.fromtimestamp(publish_timestamp, tz=timezone.utc).strftime("%Y-%m-%d") if publish_timestamp else "",
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


def _dedupe_terms(terms: list[str], limit: int = 16) -> list[str]:
    cleaned: list[str] = []
    for term in terms:
        term = clean_text(str(term or "")).strip("#.,;:!?，。；：！？）)]】」\"'")
        if term and term not in cleaned:
            cleaned.append(term)
        if len(cleaned) >= limit:
            break
    return cleaned


def _strip_time_prefix(term: str) -> str:
    return re.sub(r"^(?:\d{1,2}月|\d{1,2}日|\d{4}年|今年|今日|今天|本周|本月|月|日)+", "", term).strip()


def _specific_keyword_terms(keyword: str) -> list[str]:
    text = clean_text(keyword)
    if not text:
        return []
    terms: list[str] = []
    lower_text = text.lower()
    for term in sorted(DOUYIN_SEARCH_KEY_TERMS, key=len, reverse=True):
        if term in text or term.lower() in lower_text:
            terms.append(term)

    for match in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,18}(?:交易所|证券|银行|基金|指数|期货|集团|公司|股份|科技)", text):
        match = _strip_time_prefix(match)
        if len(match) >= 3:
            terms.append(match)

    entity_terms = [term for term in terms if len(term) >= 4 or any(suffix in term for suffix in ("交易所", "证券", "银行", "基金", "集团", "公司"))]
    key_terms = [term for term in terms if 2 <= len(term) <= 6]
    for entity in entity_terms[:4]:
        for term in key_terms[:6]:
            if term != entity and term not in entity and entity not in term:
                terms.append(f"{entity} {term}")
    for first in key_terms[:5]:
        for second in key_terms[:5]:
            if first != second:
                terms.append(f"{first} {second}")
    return _dedupe_terms(terms, 14)


def _keyword_is_broad(keyword: str) -> bool:
    keyword = clean_text(keyword)
    return keyword in DOUYIN_BROAD_KEYWORDS


def _keyword_terms(keyword: str) -> list[str]:
    keyword = clean_text(keyword)
    if not keyword:
        return []
    keyword_lower = keyword.lower()
    terms = [keyword]
    specific_terms = _specific_keyword_terms(keyword)

    if keyword in DOUYIN_KEYWORD_GROUPS or keyword_lower in {group.lower() for group in DOUYIN_KEYWORD_GROUPS}:
        for group, values in DOUYIN_KEYWORD_GROUPS.items():
            if keyword == group or keyword_lower == group.lower():
                terms.extend(values)
                break
    elif keyword in DOUYIN_TERM_EXPANSIONS:
        terms.extend(DOUYIN_TERM_EXPANSIONS[keyword])
    elif _keyword_is_broad(keyword):
        terms.extend(DOUYIN_TERM_EXPANSIONS.get(keyword, []))
    else:
        terms.extend(specific_terms)

    if specific_terms:
        terms.extend(specific_terms)
    return _dedupe_terms(terms, 16)


def _video_keyword_relevance(item: dict[str, Any], keyword: str, terms: list[str]) -> int:
    keyword = clean_text(keyword)
    text = clean_text(" ".join([
        str(item.get("title") or ""),
        str(item.get("script") or ""),
        " ".join(str(comment) for comment in item.get("comments_hot") or []),
    ]))
    if not keyword or not text:
        return 0
    text_lower = text.lower()
    compact_text = re.sub(r"\s+", "", text)
    score = 0
    matched_terms: list[str] = []
    if keyword in text or keyword.lower() in text_lower:
        score += 80
        matched_terms.append(keyword)
    compact_keyword = re.sub(r"\s+", "", keyword)
    if len(compact_keyword) >= 6 and compact_keyword in compact_text:
        score += 60
        matched_terms.append(compact_keyword)
    for term in _dedupe_terms(terms, 20):
        if len(term) < 2:
            continue
        term_lower = term.lower()
        compact_term = re.sub(r"\s+", "", term)
        if term in text or term_lower in text_lower or len(compact_term) >= 4 and compact_term in compact_text:
            score += 24 if len(term) >= 5 else 14
            matched_terms.append(term)
    for number in re.findall(r"\d+(?:\.\d+)?", keyword):
        if len(number) >= 2 and number in text:
            score += 12
            matched_terms.append(number)
    if matched_terms:
        item["matched_terms"] = _dedupe_terms(matched_terms, 8)
    return score


def _video_matches_keyword(item: dict[str, Any], keyword: str, terms: list[str]) -> bool:
    if not clean_text(keyword) or _keyword_is_broad(keyword):
        return True
    item["keyword_relevance"] = _video_keyword_relevance(item, keyword, terms)
    cleaned_keyword = clean_text(keyword)
    if len(cleaned_keyword) >= 10 or re.search(r"\d", cleaned_keyword):
        required = 36
    elif len(cleaned_keyword) >= 4:
        required = 24
    else:
        required = 14
    return item["keyword_relevance"] >= required


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


def _video_item_passes_heat(item: dict[str, Any]) -> bool:
    # 优先使用已缓存的 core_score，避免重复计算
    score = item.get("core_score") or _core_video_score(item)
    return score >= DOUYIN_MIN_ENGAGEMENT_SCORE


def _video_item_is_recent(item: dict[str, Any]) -> bool:
    timestamp = int(item.get("publish_timestamp") or 0)
    return _timestamp_is_recent(timestamp)


def _timestamp_is_recent(timestamp: int) -> bool:
    if not timestamp:
        return False
    published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    return now - timedelta(days=DOUYIN_MAX_VIDEO_AGE_DAYS) <= published_at <= now + timedelta(days=1)


def _video_item_passes_constraints(item: dict[str, Any]) -> bool:
    return _video_item_passes_heat(item) and _video_item_is_recent(item)


def _extract_hashtag_terms(*texts: str, limit: int = 8) -> list[str]:
    terms: list[str] = []
    for text in texts:
        for tag in re.findall(r"#[^#\s，。；、!！?？@]+", clean_text(str(text or ""))):
            term = clean_text(tag.lstrip("#")).strip(".,;:!?，。；：！？）)]】」\"'")
            if term and len(term) <= 14 and term not in {"抖音", "热门", "上热门", "DOU"}:
                terms.append(term)
    return [term for term in dict.fromkeys(terms) if term][:limit]


def _video_search_terms(keyword: str, limit: int = 16) -> list[str]:
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


def _indexed_publish_timestamp(text: str) -> int:
    expanded = unquote(clean_text(text))
    match = re.search(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}(?:[T\s]\d{1,2}:\d{2}(?::\d{2})?)?", expanded)
    return _normalize_timestamp(match.group(0)) if match else 0


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
        publish_timestamp = _indexed_publish_timestamp(block_text)
        candidates.append({
            "raw_id": item_id,
            "title": title or block_text[:80],
            "url": href or f"https://www.douyin.com/video/{item_id}",
            "script": block_text,
            "search_term": term,
            "publish_timestamp": str(publish_timestamp),
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
        publish_timestamp = _indexed_publish_timestamp(block_text)
        candidates.append({
            "raw_id": item_id,
            "title": title or block_text[:80],
            "url": href or f"https://www.douyin.com/video/{item_id}",
            "script": block_text,
            "search_term": term,
            "publish_timestamp": str(publish_timestamp),
        })
        if len(candidates) >= limit:
            break
    return _dedupe(candidates, limit)


async def _search_indexed_douyin_candidates(term: str, limit: int, status: dict[str, Any], timeout_seconds: float = 12) -> list[dict[str, str]]:
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
                resp = await client.get(endpoint, params=params, headers=headers, timeout=timeout_seconds)
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


async def _search_indexed_douyin_videos_by_terms(terms: list[str], limit: int, status: dict[str, Any], keyword: str = "", max_seconds: int = DOUYIN_INDEX_FALLBACK_MAX_SECONDS) -> list[dict[str, Any]]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max_seconds
    pending_terms = [term for term in dict.fromkeys(terms) if term]
    searched_terms: list[str] = []
    term_states: dict[str, str] = {}
    items: list[dict[str, Any]] = []
    best_effort_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    filtered_low_heat = 0
    filtered_old = 0
    filtered_relevance = 0
    detail_checks = 0
    max_terms = max(18, limit * 4)
    max_detail_checks = max(30, limit * 5)

    while pending_terms and loop.time() < deadline and len(searched_terms) < max_terms and detail_checks < max_detail_checks and len(_dedupe(items, limit)) < limit:
        term = pending_terms.pop(0)
        if term in term_states:
            continue
        remaining = deadline - loop.time()
        if remaining <= 3:
            status["douyin_index_timeout"] = f"stopped_after_{max_seconds}s"
            break
        searched_terms.append(term)
        term_candidates = await _search_indexed_douyin_candidates(term, max(limit * 2, 10), status, timeout_seconds=min(12, max(4, remaining / 3)))
        term_states[term] = "ok" if term_candidates else "empty"
        for candidate in term_candidates:
            raw_id = candidate.get("raw_id", "")
            if loop.time() >= deadline:
                status["douyin_index_timeout"] = f"stopped_after_{max_seconds}s"
                break
            if not raw_id or raw_id in seen_ids or detail_checks >= max_detail_checks:
                continue
            candidate_timestamp = _normalize_timestamp(candidate.get("publish_timestamp"))
            # 预筛：DuckDuckGo 缓存时间戳可能有延迟，放宽到 60 天，靠 detail 接口拿到真实时间再二次过滤
            if candidate_timestamp and (datetime.now(timezone.utc) - datetime.fromtimestamp(candidate_timestamp, tz=timezone.utc)) > timedelta(days=60):
                filtered_old += 1
                continue
            seen_ids.add(raw_id)
            detail_checks += 1
            base = {
                "platform": "douyin",
                "source": "公开搜索索引 + DouK详情",
                "source_type": "video_fallback",
                "title": candidate.get("title", ""),
                "url": candidate.get("url") or f"https://www.douyin.com/video/{raw_id}",
                "likes": 0,
                "comment_count": 0,
                "share_count": 0,
                "collect_count": 0,
                "duration_seconds": 0,
                "script": candidate.get("script", ""),
                "comments_hot": [],
                "raw_id": raw_id,
                "search_term": candidate.get("search_term", ""),
                "publish_timestamp": candidate_timestamp,
                "publish_time": datetime.fromtimestamp(candidate_timestamp, tz=timezone.utc).strftime("%Y-%m-%d") if candidate_timestamp else "",
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
            if not _video_matches_keyword(item, keyword or term, terms):
                filtered_relevance += 1
                continue
            related_tags = _extract_hashtag_terms(item.get("title", ""), item.get("script", ""), candidate.get("script", ""))
            for tag in related_tags:
                if tag not in term_states and tag not in pending_terms and len(pending_terms) + len(searched_terms) < max_terms:
                    pending_terms.append(tag)
            if item.get("core_score") and _video_item_passes_constraints(item):
                items.append(item)
            elif item.get("core_score") and _video_item_passes_heat(item):
                # 有热度但可能超期，作为最佳兜底保留
                best_effort_items.append(item)
                filtered_old += 1
            elif item.get("core_score"):
                if not _video_item_passes_heat(item):
                    filtered_low_heat += 1
                if not _video_item_is_recent(item):
                    filtered_old += 1
            await asyncio.sleep(0.4)
            if len(_dedupe(items, limit)) >= limit:
                break

    items.sort(key=lambda item: (item.get("keyword_relevance") or 0, item.get("core_score") or 0, item.get("likes") or 0), reverse=True)
    result = _dedupe(items, limit)
    if not result and best_effort_items:
        best_effort_items.sort(key=lambda item: (item.get("keyword_relevance") or 0, item.get("core_score") or 0, item.get("likes") or 0), reverse=True)
        result = _dedupe(best_effort_items, limit)
        status["douyin_index_fallback"] = "ok:best_effort"
    status["douyin_index_term_status"] = term_states
    status["douyin_index_terms_used"] = searched_terms
    if "douyin_index_fallback" not in status:
        status["douyin_index_fallback"] = "ok" if result else "empty"
    status["douyin_video_min_engagement"] = DOUYIN_MIN_ENGAGEMENT_SCORE
    status["douyin_video_max_age_days"] = DOUYIN_MAX_VIDEO_AGE_DAYS
    status["douyin_video_filtered_low_heat"] = filtered_low_heat
    status["douyin_video_filtered_old"] = filtered_old
    status["douyin_video_filtered_relevance"] = filtered_relevance
    return result


async def _search_douyin_videos_by_terms(keyword: str, limit: int, status: dict[str, Any]) -> list[dict[str, Any]]:
    terms = _video_search_terms(keyword)
    if not terms:
        status["douyin_video_fallback"] = "empty:no_keyword"
        return []
    found: list[dict[str, Any]] = []
    best_effort_direct: list[dict[str, Any]] = []
    term_states: dict[str, str] = {}
    filtered_relevance = 0
    direct_search_status = str(status.get("douyin") or "")
    direct_terms = [] if direct_search_status.startswith("unavailable") else terms[:DOUYIN_DIRECT_SEARCH_MAX_TERMS]
    if not direct_terms and direct_search_status:
        status["douyin_video_direct_search"] = f"skipped:{direct_search_status}"
    for term in direct_terms:
        term_status: dict[str, Any] = {}
        term_items = await _search_douyin(term, limit, term_status)
        term_states[term] = term_status.get("douyin", "empty")
        if str(term_states[term]).startswith("unavailable"):
            status["douyin_video_direct_search"] = f"stopped:{term_states[term]}"
            break
        for item in term_items:
            item["source_type"] = "video_fallback"
            item["search_term"] = term
            item["core_score"] = _core_video_score(item)
        for item in term_items:
            if not _video_matches_keyword(item, keyword, terms):
                filtered_relevance += 1
                continue
            if _video_item_passes_constraints(item):
                found.append(item)
            elif _video_item_passes_heat(item):
                best_effort_direct.append(item)
        if len(_dedupe(found, limit * 2)) >= limit * 2:
            break
    unique = _dedupe(found, limit * 3)
    unique.sort(key=lambda item: (item.get("keyword_relevance") or 0, item.get("core_score") or _core_video_score(item), item.get("likes") or 0), reverse=True)
    result = _dedupe(unique, limit)
    if len(result) < limit:
        indexed_items = await _search_indexed_douyin_videos_by_terms(terms, limit, status, keyword=keyword)
        result = _dedupe([*result, *indexed_items], limit)
    if not result and best_effort_direct:
        best_effort_direct.sort(key=lambda item: (item.get("keyword_relevance") or 0, item.get("core_score") or 0, item.get("likes") or 0), reverse=True)
        result = _dedupe(best_effort_direct, limit)
        status["douyin_video_fallback"] = "ok:best_effort_direct"
    status["douyin_video_terms"] = terms
    status["douyin_video_term_status"] = term_states
    status["douyin_video_filtered_relevance"] = filtered_relevance + int(status.get("douyin_video_filtered_relevance") or 0)
    if "douyin_video_fallback" not in status:
        status["douyin_video_fallback"] = "ok" if result else "empty"
    status["douyin_video_min_engagement"] = DOUYIN_MIN_ENGAGEMENT_SCORE
    status["douyin_video_max_age_days"] = DOUYIN_MAX_VIDEO_AGE_DAYS
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
        elif value and (not merged.get(key) or key in {"likes", "comment_count", "share_count", "collect_count", "duration_seconds", "publish_timestamp", "publish_time"}):
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


async def _post_json(client: httpx.AsyncClient, url: str, payload: dict[str, Any], token: str = "", timeout: float = 18) -> dict[str, Any]:
    resp = await client.post(url, json=payload, headers=_headers(token), timeout=timeout)
    resp.raise_for_status()
    return resp.json()


async def _get_text(client: httpx.AsyncClient, url: str) -> str:
    resp = await client.get(url, headers=_headers(), timeout=18, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


async def _search_douyin(keyword: str, limit: int, status: dict[str, Any], publish_time: int = 7) -> list[dict[str, Any]]:
    url = f"{config.douk_api_base.rstrip('/')}/douyin/search/video"
    payload = {
        "keyword": keyword,
        "pages": 1,
        "count": min(max(limit * 3, 10), 30),
        "sort_type": 0,
        "publish_time": publish_time,
        "duration": 0,
        "search_range": 0,
        "source": False,
    }
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            data = await _post_json(client, url, payload, config.douk_api_token, timeout=10)
        # 检测 Cookie 缺失（抖音搜索返回"获取数据失败！"），立即停止重试
        if isinstance(data, dict) and "获取数据失败" in str(data.get("message", "")):
            status["douyin"] = "unavailable:no_cookie"
            return []
        items = [i for d in _walk_dicts(data) if (i := _normalize_item(d, "douyin", "TikTokDownloader"))]
        threshold = config.douyin_like_threshold
        viral = [i for i in items if i["likes"] >= threshold]
        result = _dedupe(viral or items, limit)
        if result:
            status["douyin"] = "ok"
            return result
        # 近期窗口无结果，降级为全量时间范围重试
        if publish_time != 0:
            return await _search_douyin(keyword, limit, status, publish_time=0)
        status["douyin"] = "empty"
        return []
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
        # 检测 Cookie 缺失，快速失败避免占用索引搜索时间预算
        if isinstance(data, dict) and "获取数据失败" in str(data.get("message", "")):
            return None
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
    detail = await _detail_douyin_by_id(match.group(1), status)
    if detail:
        status["douyin_detail"] = "ok"
        return [detail]
    status.setdefault("douyin_detail", "empty")
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


async def search_viral_content(keyword: str, source_url: str = "", limit: int = 6, video_only: bool = False) -> dict[str, Any]:
    keyword = clean_text(keyword)
    source_url = _extract_first_url(source_url)
    status: dict[str, Any] = {}
    items: list[dict[str, Any]] = []

    if video_only:
        status["douyin_video_mode"] = "keyword_index"
        status["douyin_hot"] = "skipped:keyword_video_search"
        if keyword:
            # 优先 TikTokDownloader 直接搜索（含全量时间回退），再走索引兜底
            items.extend(await _search_douyin_videos_by_terms(keyword, limit, status))
        status["douyin"] = "ok:keyword_videos" if items else "empty:keyword_videos"
        items = await _enrich_douyin_items(_dedupe(items, limit), status)
        search_links = [
            {"label": "抖音关键词搜索", "url": DOUYIN_SEARCH_URL.format(keyword=quote(keyword))},
        ] if keyword else []
        return {
            "keyword": keyword,
            "items": items,
            "source_text": _items_to_source_text(items),
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


def _find_subtitle_urls(data: Any, depth: int = 0) -> list[str]:
    """递归在 TikTokDownloader detail 响应中查找抖音 ASR 字幕下载 URL。"""
    if depth > 6:
        return []
    urls_zh: list[str] = []
    urls_other: list[str] = []
    if isinstance(data, dict):
        for key in ("subtitle_infos", "subtitles", "video_subtitles", "caption_infos"):
            entries = data.get(key)
            if isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    url_list = entry.get("url_list")
                    url = (entry.get("url") or
                           (url_list[0] if isinstance(url_list, list) and url_list else "") or
                           entry.get("subtitle_url") or "")
                    if not (url and isinstance(url, str) and url.startswith("http")):
                        continue
                    lang = str(entry.get("language") or entry.get("language_code") or "").lower()
                    if "zh" in lang or "zho" in lang or "chn" in lang or not lang:
                        urls_zh.append(url)
                    else:
                        urls_other.append(url)
            elif isinstance(entries, dict):
                # {"zho": {"url": "...", "format": "webvtt"}}
                for lang, entry in entries.items():
                    if not isinstance(entry, dict):
                        continue
                    url = entry.get("url") or ""
                    if not (url and url.startswith("http")):
                        continue
                    if "zh" in lang.lower() or "zho" in lang.lower():
                        urls_zh.append(url)
                    else:
                        urls_other.append(url)
        if urls_zh or urls_other:
            return urls_zh + urls_other
        for v in data.values():
            result = _find_subtitle_urls(v, depth + 1)
            if result:
                return result
    elif isinstance(data, list):
        for item in data:
            result = _find_subtitle_urls(item, depth + 1)
            if result:
                return result
    return []


def _parse_vtt_srt(text: str) -> str:
    """将 VTT / SRT 字幕文本解析为连续文字，去重相邻重复行。"""
    lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "-->" in line or line.startswith("WEBVTT") or re.match(r"^\d+$", line):
            continue
        lines.append(line)
    deduped: list[str] = []
    prev = ""
    for line in lines:
        if line != prev:
            deduped.append(line)
            prev = line
    return "".join(deduped)


async def _whisper_transcribe_url(video_url: str, api_key: str = "") -> str | None:
    """下载抖音视频并调用 OpenAI Whisper API 转录，返回中文口播文案或 None。"""
    effective_key = api_key or config.openai_api_key
    if not (effective_key and video_url and video_url.startswith("http")):
        return None
    try:
        video_data = b""
        async with httpx.AsyncClient(trust_env=False, follow_redirects=True) as c:
            async with c.stream("GET", video_url, headers=_headers(), timeout=30) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(8192):
                    video_data += chunk
                    if len(video_data) > 22 * 1024 * 1024:  # 22 MB 上限
                        break
        if len(video_data) < 2000:
            return None
        from openai import AsyncOpenAI
        oai = AsyncOpenAI(api_key=effective_key, base_url=config.openai_base_url, timeout=50)
        result = await oai.audio.transcriptions.create(
            model="whisper-1",
            file=("audio.mp4", video_data, "video/mp4"),
            language="zh",
            response_format="text",
        )
        text = result.strip() if isinstance(result, str) else getattr(result, "text", "") or ""
        return text if len(text) >= 8 else None
    except Exception:
        return None


async def get_video_transcript(video_url: str, api_key: str | None = None) -> dict[str, Any]:
    """提取抖音视频口播文案。优先使用平台字幕→Whisper ASR→视频描述文字。"""
    status: dict[str, Any] = {}
    video_url = _extract_first_url(video_url)
    if not video_url:
        return {"ok": False, "error": "无效的链接"}
    resolved = await _resolve_source_url(video_url, status)
    m = re.search(r"(\d{16,22})", f"{video_url} {resolved}")
    if not m:
        return {"ok": False, "error": "无法提取视频 ID，请使用抖音视频直链（含 /video/ 或分享短链）"}
    detail_id = m.group(1)
    api_url = f"{config.douk_api_base.rstrip('/')}/douyin/detail"
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            raw = await _post_json(client, api_url, {"detail_id": detail_id, "source": True}, config.douk_api_token)
        if isinstance(raw, dict) and "获取数据失败" in str(raw.get("message", "")):
            return {"ok": False, "error": "Cookie 未配置或已失效，请先在助手中完成抖音登录态配置"}
        # 1. 平台 ASR 字幕（逐字稿，准确率最高，实际上大多数视频无此字段）
        sub_urls = _find_subtitle_urls(raw)
        if sub_urls:
            async with httpx.AsyncClient(trust_env=False, follow_redirects=True) as c:
                for su in sub_urls[:3]:
                    try:
                        resp = await c.get(su, timeout=10)
                        resp.raise_for_status()
                        transcript = _parse_vtt_srt(resp.text)
                        if len(transcript) >= 8:
                            return {"ok": True, "transcript": transcript, "method": "subtitle", "detail_id": detail_id}
                    except Exception:
                        continue
        # 2. OpenAI Whisper ASR（从视频 CDN 下载音频流转录）
        data_obj = raw.get("data") if isinstance(raw, dict) else None
        cdn_url = ""
        if isinstance(data_obj, dict):
            # source: True 返回原始 aweme_detail，从 video.play_addr.url_list 取 CDN URL
            vid_obj = data_obj.get("video") or {}
            if isinstance(vid_obj, dict):
                play_addr = vid_obj.get("play_addr") or {}
                url_list = (play_addr.get("url_list") or []) if isinstance(play_addr, dict) else []
                cdn_url = url_list[0] if url_list and isinstance(url_list[0], str) else ""
                if not cdn_url:
                    cdn_url = vid_obj.get("play_addr_h264", {}).get("url_list", [""])[0] if isinstance(vid_obj.get("play_addr_h264"), dict) else ""
        effective_key = api_key or config.openai_api_key
        if cdn_url and effective_key:
            whisper_text = await _whisper_transcribe_url(cdn_url, api_key=effective_key)
            if whisper_text:
                return {"ok": True, "transcript": whisper_text, "method": "whisper", "detail_id": detail_id}
        # 3. 回退：视频描述（非逐字稿）
        for d in _walk_dicts(raw):
            item = _normalize_item(d, "douyin", "detail")
            if item and item.get("script"):
                return {
                    "ok": True,
                    "transcript": item["script"],
                    "method": "description",
                    "detail_id": detail_id,
                    "warning": "该视频暂无平台 ASR 字幕，以下为视频描述（非完整逐字口播稿）",
                }
        return {"ok": False, "error": "未能获取文案（无字幕数据且视频描述为空）"}
    except httpx.RequestError as exc:
        return {"ok": False, "error": f"采集服务连接失败：{exc.__class__.__name__}，请确认本机助手正在运行"}
    except Exception as exc:
        return {"ok": False, "error": f"提取失败：{str(exc)[:120]}"}


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