"""多平台公开热点聚合（无需本机助手）。

覆盖：微博 / 百度 / 头条 / 腾讯 / 抖音 / B站 / 资讯 RSS / 第一财经。
默认返回全网热点；可用 scope=finance 收束到金融科技方向。
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin

import aiohttp
import feedparser
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

RSS_SOURCES = {
    "36氪": "https://36kr.com/feed",
    "中国新闻网财经": "https://www.chinanews.com.cn/rss/finance.xml",
    "经济观察网": "https://www.eeo.com.cn/rss.xml",
    "FT中文网": "https://www.ftchinese.com/rss/news",
}

Fetcher = Callable[[], Awaitable[List["HotTopic"]]]


@dataclass
class HotTopic:
    title: str
    source: str
    url: str = ""
    published_at: str = ""
    summary: str = ""
    tags: List[str] = field(default_factory=list)
    heat_score: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SourceResult:
    name: str
    ok: bool
    count: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _keyword_url(template: str, keyword: str) -> str:
    return template.format(keyword=quote(keyword or ""))


def _interleave(groups: List[List[HotTopic]]) -> List[HotTopic]:
    topics: List[HotTopic] = []
    max_len = max((len(g) for g in groups), default=0)
    for i in range(max_len):
        for group in groups:
            if i < len(group):
                topics.append(group[i])
    return topics


def _dedupe(topics: List[HotTopic]) -> List[HotTopic]:
    seen, unique = set(), []
    for t in topics:
        key = re.sub(r"\s+", "", t.title)[:18]
        if key and key not in seen:
            seen.add(key)
            unique.append(t)
    return unique


async def _get_json(
    url: str,
    *,
    headers: Optional[dict] = None,
    ssl: Optional[bool] = None,
) -> Any:
    h = {**HEADERS, **(headers or {})}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            headers=h,
            timeout=aiohttp.ClientTimeout(total=12),
            ssl=ssl,
        ) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)


async def _get_text(url: str, *, headers: Optional[dict] = None, ssl: Optional[bool] = None) -> str:
    h = {**HEADERS, **(headers or {})}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            headers=h,
            timeout=aiohttp.ClientTimeout(total=12),
            ssl=ssl,
        ) as resp:
            resp.raise_for_status()
            return await resp.text(errors="replace")


# ── 泛热点榜 ──────────────────────────────────────────────

async def fetch_weibo_hot() -> List[HotTopic]:
    data = await _get_json(
        "https://weibo.com/ajax/side/hotSearch",
        headers={"Referer": "https://weibo.com/"},
    )
    topics: List[HotTopic] = []
    for item in data.get("data", {}).get("realtime", [])[:50]:
        word = clean_text(item.get("word", "") or item.get("word_scheme", ""))
        note = clean_text(item.get("note", "") or item.get("icon_desc", ""))
        if not word:
            continue
        topics.append(HotTopic(
            title=word,
            source="微博热搜",
            url=_keyword_url("https://s.weibo.com/weibo?q={keyword}", word),
            published_at=_now(),
            summary=note[:200],
            heat_score=float(item.get("num") or item.get("raw_hot") or 0),
            tags=["热搜", "微博"],
        ))
    return topics


async def fetch_baidu_hot() -> List[HotTopic]:
    data = await _get_json(
        "https://top.baidu.com/api/board?tab=realtime",
        headers={"Referer": "https://top.baidu.com/board?tab=realtime"},
    )
    topics: List[HotTopic] = []
    cards = data.get("data", {}).get("cards", [])
    items = cards[0].get("content", []) if cards else []
    for item in items[:50]:
        title = clean_text(item.get("word", "") or item.get("title", ""))
        if not title:
            continue
        topics.append(HotTopic(
            title=title,
            source="百度热搜",
            url=item.get("url") or item.get("appUrl") or _keyword_url(
                "https://www.baidu.com/s?wd={keyword}", title
            ),
            published_at=_now(),
            summary=clean_text(item.get("desc", ""))[:200],
            heat_score=float(item.get("hotScore") or 0),
            tags=["热搜", "百度"],
        ))
    return topics


async def fetch_toutiao_hot() -> List[HotTopic]:
    data = await _get_json(
        "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc",
        headers={"Referer": "https://www.toutiao.com/"},
    )
    topics: List[HotTopic] = []
    for item in data.get("data", [])[:50]:
        title = clean_text(item.get("Title", ""))
        if not title:
            continue
        cluster_id = item.get("ClusterId") or item.get("ClusterID") or item.get("cluster_id")
        url = (
            item.get("Url")
            or item.get("url")
            or (f"https://www.toutiao.com/trending/{cluster_id}/" if cluster_id else "")
            or _keyword_url("https://so.toutiao.com/search?keyword={keyword}", title)
        )
        topics.append(HotTopic(
            title=title,
            source="今日头条热榜",
            url=url,
            published_at=_now(),
            summary=clean_text(item.get("Label") or item.get("LabelDesc") or "")[:200],
            heat_score=float(item.get("HotScore") or item.get("HotValue") or 0),
            tags=["热搜", "头条"],
        ))
    return topics


async def fetch_tencent_hot() -> List[HotTopic]:
    data = await _get_json(
        "https://i.news.qq.com/gw/event/pc_hot_ranking_list"
        "?startTime=0&compareTime=0&from=0&count=40",
        headers={"Referer": "https://news.qq.com/"},
    )
    topics: List[HotTopic] = []
    newslist = data.get("idlist", [{}])[0].get("newslist", [])
    for item in newslist[1:41]:
        title = clean_text(item.get("title", ""))
        if not title:
            continue
        topics.append(HotTopic(
            title=title,
            source="腾讯热榜",
            url=item.get("url") or item.get("surl") or "",
            published_at=_now(),
            summary=clean_text(item.get("abstract", ""))[:200],
            heat_score=float(item.get("readCount") or item.get("hotEvent", {}).get("hotScore") or 0)
            if isinstance(item.get("hotEvent"), dict)
            else float(item.get("readCount") or 0),
            tags=["热搜", "腾讯"],
        ))
    return topics


async def fetch_douyin_hot() -> List[HotTopic]:
    """抖音网页热搜榜（公开接口，无需 Cookie / 本机助手）。"""
    data = await _get_json(
        "https://www.douyin.com/aweme/v1/web/hot/search/list/",
        headers={"Referer": "https://www.douyin.com/"},
    )
    word_list = data.get("data", {}).get("word_list") or data.get("word_list") or []
    topics: List[HotTopic] = []
    for item in word_list[:50]:
        word = clean_text(item.get("word", "") or item.get("sentence", ""))
        if not word:
            continue
        sentence_id = item.get("sentence_id") or item.get("group_id") or ""
        url = (
            f"https://www.douyin.com/hot/{sentence_id}"
            if sentence_id
            else _keyword_url("https://www.douyin.com/search/{keyword}", word)
        )
        topics.append(HotTopic(
            title=word,
            source="抖音热榜",
            url=url,
            published_at=_now(),
            summary=clean_text(item.get("word_cover", {}).get("uri", "") if isinstance(item.get("word_cover"), dict) else "")[:200]
            or clean_text(str(item.get("label") or "")),
            heat_score=float(item.get("hot_value") or item.get("hot_score") or 0),
            tags=["热搜", "抖音"],
        ))
    return topics


async def fetch_bilibili_hot() -> List[HotTopic]:
    data = await _get_json(
        "https://api.bilibili.com/x/web-interface/popular?ps=30&pn=1",
        headers={"Referer": "https://www.bilibili.com/"},
    )
    topics: List[HotTopic] = []
    for item in data.get("data", {}).get("list", [])[:40]:
        title = clean_text(item.get("title", ""))
        if not title:
            continue
        bvid = item.get("bvid") or ""
        topics.append(HotTopic(
            title=title,
            source="B站热门",
            url=f"https://www.bilibili.com/video/{bvid}" if bvid else item.get("short_link_v2") or "",
            published_at=_now(),
            summary=clean_text(item.get("desc") or item.get("tname") or "")[:200],
            heat_score=float((item.get("stat") or {}).get("view") or 0),
            tags=["热门", "B站"],
        ))
    return topics


# ── 资讯源 ──────────────────────────────────────────────

async def _fetch_rss(name: str, url: str, session: aiohttp.ClientSession) -> List[HotTopic]:
    topics: List[HotTopic] = []
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            text = await resp.text(errors="replace")
        feed = feedparser.parse(text)
        for entry in feed.entries[:20]:
            title = clean_text(getattr(entry, "title", ""))
            summary = clean_text(getattr(entry, "summary", "")).replace(name, "", 1).strip()
            link = getattr(entry, "link", "")
            published = getattr(entry, "published_parsed", None)
            pub = datetime(*published[:6]).isoformat(timespec="seconds") if published else _now()
            if title and not re.search(r"第\d+期", title):
                topics.append(HotTopic(
                    title=title,
                    source=name,
                    url=link,
                    published_at=pub,
                    summary=summary[:200],
                    tags=["资讯"],
                ))
    except Exception as exc:
        print(f"[hot] RSS {name} 失败: {exc}")
    return topics


async def fetch_rss_news() -> List[HotTopic]:
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(
            *[_fetch_rss(n, u, session) for n, u in RSS_SOURCES.items()],
            return_exceptions=True,
        )
    groups = [r for r in results if isinstance(r, list)]
    return _dedupe(_interleave(groups))


async def fetch_yicai() -> List[HotTopic]:
    data = await _get_json(
        "https://www.yicai.com/api/ajax/getlatest?page=1&pagesize=30",
        headers={"Referer": "https://www.yicai.com/"},
    )
    topics: List[HotTopic] = []
    for item in (data if isinstance(data, list) else [])[:30]:
        title = clean_text(item.get("NewsTitle", ""))
        summary = clean_text(item.get("NewsNotes", ""))
        link = (
            item.get("ShareUrl")
            or item.get("OuterUrl")
            or item.get("url")
            or item.get("NewsUrl")
            or ""
        )
        news_id = item.get("NewsID") or item.get("UniqueTag") or ""
        if link.startswith("/"):
            link = f"https://www.yicai.com{link}"
        if not link and news_id:
            link = f"https://www.yicai.com/news/{news_id}.html"
        if title:
            topics.append(HotTopic(
                title=title,
                source="第一财经",
                url=link or _keyword_url("https://www.baidu.com/s?wd={keyword}", title),
                published_at=_now(),
                summary=summary[:200],
                tags=["资讯", "财经"],
            ))
    return topics


def _links_from_html(name: str, html: str, base: str, markers: List[str], limit: int = 25) -> List[HotTopic]:
    topics: List[HotTopic] = []
    soup = BeautifulSoup(html, "html.parser")
    seen_titles, seen_urls = set(), set()
    for link in soup.select("a"):
        title = clean_text(link.get_text(" ", strip=True))
        href = (link.get("href") or "").strip()
        if not title or len(title) < 8 or not href or re.search(r"第\d+期", title):
            continue
        url = urljoin(base, href)
        if markers and not any(m in url for m in markers):
            continue
        if title in seen_titles or url in seen_urls:
            continue
        seen_titles.add(title)
        seen_urls.add(url)
        topics.append(HotTopic(
            title=title,
            source=name,
            url=url,
            published_at=_now(),
            tags=["资讯"],
        ))
        if len(topics) >= limit:
            break
    return topics


async def fetch_eastmoney() -> List[HotTopic]:
    url = "https://finance.eastmoney.com/a/cywjh.html"
    html = await _get_text(url, headers={"Referer": "https://finance.eastmoney.com/"}, ssl=False)
    return _links_from_html("东方财富", html, url, ["finance.eastmoney.com/a/"])


PLATFORM_FETCHERS: Dict[str, Fetcher] = {
    "微博热搜": fetch_weibo_hot,
    "百度热搜": fetch_baidu_hot,
    "今日头条热榜": fetch_toutiao_hot,
    "腾讯热榜": fetch_tencent_hot,
    "抖音热榜": fetch_douyin_hot,
    "B站热门": fetch_bilibili_hot,
    "第一财经": fetch_yicai,
    "东方财富": fetch_eastmoney,
    "资讯RSS": fetch_rss_news,
}


async def _run_fetcher(name: str, fetcher: Fetcher) -> Tuple[SourceResult, List[HotTopic]]:
    try:
        topics = await fetcher()
        return SourceResult(name=name, ok=True, count=len(topics)), topics
    except Exception as exc:
        print(f"[hot] {name} 失败: {exc}")
        return SourceResult(name=name, ok=False, count=0, error=str(exc)[:160]), []


async def fetch_all_hot_topics() -> Tuple[List[HotTopic], List[SourceResult]]:
    """并发抓取全部公开源，返回 (去重后热点, 各源状态)。"""
    names = list(PLATFORM_FETCHERS.keys())
    results = await asyncio.gather(
        *[_run_fetcher(name, PLATFORM_FETCHERS[name]) for name in names]
    )
    source_results: List[SourceResult] = []
    name_to_group: Dict[str, List[HotTopic]] = {}
    for status, topics in results:
        source_results.append(status)
        if topics:
            name_to_group[status.name] = topics

    # 热榜优先穿插，再资讯
    priority = ["抖音热榜", "微博热搜", "百度热搜", "今日头条热榜", "腾讯热榜", "B站热门"]
    ordered: List[List[HotTopic]] = []
    for name in priority:
        group = name_to_group.get(name)
        if group:
            ordered.append(group)
    for name, group in name_to_group.items():
        if name not in priority:
            ordered.append(group)

    return _dedupe(_interleave(ordered)), source_results
