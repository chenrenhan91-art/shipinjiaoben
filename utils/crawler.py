"""
热点爬虫工具
已验证可用数据源（2026-05）：
    资讯 RSS : 36氪、中国新闻网、中国新闻网财经、经济观察网
    资讯 API : 第一财经
  热搜榜单 : 百度实时热搜、今日头条热榜、腾讯新闻热榜、微博实时热搜
  爆款视频 : 手动导入 JSON（抖音/小红书/视频号暂无公开 API）
"""
import json
import asyncio
import feedparser
import aiohttp
from datetime import datetime
from typing import List
from urllib.parse import quote
from data_models import HotTopic, ViralVideo
from utils.text_utils import clean_text

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://weibo.com/",
}


def _keyword_url(template: str, keyword: str) -> str:
    return template.format(keyword=quote(keyword or ""))


def _interleave_topic_groups(groups: List[List[HotTopic]]) -> List[HotTopic]:
    topics: List[HotTopic] = []
    max_len = max((len(group) for group in groups), default=0)
    for index in range(max_len):
        for group in groups:
            if index < len(group):
                topics.append(group[index])
    return topics

# ──────────────────────────────────────────────
# RSS 财经/科技资讯源（经实测可用）
# ──────────────────────────────────────────────
RSS_SOURCES = {
    "36氪": "https://36kr.com/feed",
    "中国新闻网": "https://www.chinanews.com.cn/rss/scroll-news.xml",
    "中国新闻网财经": "https://www.chinanews.com.cn/rss/finance.xml",
    "经济观察网": "https://www.eeo.com.cn/rss.xml",
}


async def _fetch_rss(name: str, url: str, session: aiohttp.ClientSession) -> List[HotTopic]:
    """解析单个 RSS 源"""
    topics: List[HotTopic] = []
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            text = await resp.text(errors="replace")
        feed = feedparser.parse(text)
        for entry in feed.entries[:20]:
            title = clean_text(getattr(entry, "title", ""))
            summary = clean_text(getattr(entry, "summary", ""))
            link = getattr(entry, "link", "")
            published = getattr(entry, "published_parsed", None)
            pub_dt = datetime(*published[:6]) if published else datetime.now()
            if title:
                topics.append(HotTopic(
                    title=title,
                    source=name,
                    url=link,
                    published_at=pub_dt,
                    summary=summary[:200],
                    tags=["财经"],
                ))
    except Exception as exc:
        print(f"[Crawler] RSS {name} 失败: {exc}")
    return topics


async def fetch_financial_news() -> List[HotTopic]:
    """抓取近期权威资讯 RSS"""
    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_rss(name, url, session) for name, url in RSS_SOURCES.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    topics: List[HotTopic] = []
    groups = [r for r in results if isinstance(r, list)]
    topics.extend(_interleave_topic_groups(groups))
    seen, unique = set(), []
    for t in topics:
        key = t.title[:20]
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique


async def fetch_yicai_latest() -> List[HotTopic]:
    """抓取第一财经最新资讯（公开 JSON 接口，带原文链接）"""
    url = "https://www.yicai.com/api/ajax/getlatest?page=1&pagesize=30"
    topics: List[HotTopic] = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)
        items = data if isinstance(data, list) else []
        for item in items[:30]:
            title = clean_text(item.get("NewsTitle", ""))
            summary = clean_text(item.get("NewsNotes", ""))
            link = item.get("ShareUrl") or item.get("OuterUrl") or item.get("NewsUrl") or item.get("url") or ""
            if link.startswith("/"):
                link = f"https://www.yicai.com{link}"
            published = item.get("CreateDate") or item.get("LastDate") or ""
            try:
                pub_dt = datetime.fromisoformat(published) if published else datetime.now()
            except ValueError:
                pub_dt = datetime.now()
            if title and link:
                topics.append(HotTopic(
                    title=title,
                    source="第一财经",
                    url=link,
                    published_at=pub_dt,
                    summary=summary[:200],
                    tags=["财经", "权威资讯"],
                ))
    except Exception as exc:
        print(f"[Crawler] 第一财经失败: {exc}")
    return topics


async def fetch_weibo_hot() -> List[HotTopic]:
    """抓取微博实时热搜（公开 JSON 接口）"""
    url = "https://weibo.com/ajax/side/hotSearch"
    topics: List[HotTopic] = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)
        items = data.get("data", {}).get("realtime", [])
        for item in items[:30]:
            word = item.get("word", "")
            note = item.get("note", "")
            num = item.get("num", 0)
            if word:
                topics.append(HotTopic(
                    title=word,
                    source="微博热搜",
                    url=_keyword_url("https://s.weibo.com/weibo?q={keyword}", word),
                    summary=note,
                    heat_score=float(num),
                    tags=["热搜", "微博"],
                ))
    except Exception as exc:
        print(f"[Crawler] 微博热搜失败: {exc}")
    return topics


async def fetch_baidu_hot() -> List[HotTopic]:
    """抓取百度实时热搜（公开 JSON 接口，含真实热度分值）"""
    url = "https://top.baidu.com/api/board?tab=realtime"
    topics: List[HotTopic] = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)
        cards = data.get("data", {}).get("cards", [])
        items = cards[0].get("content", []) if cards else []
        for item in items[:30]:
            title = clean_text(item.get("word", "") or item.get("title", ""))
            desc = clean_text(item.get("desc", ""))
            hot_score = float(item.get("hotScore", 0))
            url_link = item.get("url", "") or _keyword_url("https://www.baidu.com/s?wd={keyword}", title)
            if title:
                topics.append(HotTopic(
                    title=title,
                    source="百度热搜",
                    url=url_link,
                    summary=desc[:200],
                    heat_score=hot_score,
                    tags=["热搜", "百度"],
                ))
    except Exception as exc:
        print(f"[Crawler] 百度热搜失败: {exc}")
    return topics


async def fetch_toutiao_hot() -> List[HotTopic]:
    """抓取今日头条热榜（公开 JSON 接口，热度数值大、覆盖广）"""
    url = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
    topics: List[HotTopic] = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)
        items = data.get("data", [])
        for item in items[:30]:
            title = clean_text(item.get("Title", ""))
            label = clean_text(item.get("Label", "") or item.get("LabelDesc", "") or item.get("LabelUrl", ""))
            hot_score = float(item.get("HotScore", item.get("HotValue", 0)))
            cluster_id = item.get("ClusterId") or item.get("ClusterID") or item.get("cluster_id")
            url_link = (
                item.get("Url")
                or item.get("url")
                or item.get("ArticleUrl")
                or item.get("OpenUrl")
                or (f"https://www.toutiao.com/trending/{cluster_id}/" if cluster_id else "")
                or _keyword_url("https://so.toutiao.com/search?keyword={keyword}", title)
            )
            if title:
                topics.append(HotTopic(
                    title=title,
                    source="今日头条热榜",
                    url=url_link,
                    summary=label[:200],
                    heat_score=hot_score,
                    tags=["热搜", "头条"],
                ))
    except Exception as exc:
        print(f"[Crawler] 今日头条热榜失败: {exc}")
    return topics


async def fetch_tencent_hot() -> List[HotTopic]:
    """抓取腾讯新闻热榜（公开 JSON 接口，每 10 分钟更新）"""
    url = (
        "https://i.news.qq.com/gw/event/pc_hot_ranking_list"
        "?startTime=0&compareTime=0&from=0&count=20"
    )
    topics: List[HotTopic] = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)
        newslist = data.get("idlist", [{}])[0].get("newslist", [])
        # 第一条是固定说明文字，跳过
        for item in newslist[1:21]:
            title = clean_text(item.get("title", ""))
            abstract = clean_text(item.get("abstract", ""))
            source = item.get("source", "腾讯新闻热榜")
            link = item.get("url", "")
            if title:
                topics.append(HotTopic(
                    title=title,
                    source=f"腾讯热榜/{source}",
                    url=link,
                    summary=abstract[:200],
                    tags=["热搜", "腾讯"],
                ))
    except Exception as exc:
        print(f"[Crawler] 腾讯新闻热榜失败: {exc}")
    return topics


def load_viral_videos_from_file(filepath: str) -> List[ViralVideo]:
    """
    从本地 JSON 文件加载爆款视频数据。
    用于用户手动导入抖音/小红书/视频号爆款。

    JSON 格式示例：
    [
      {
        "platform": "douyin",
        "title": "标题",
        "script": "逐字稿...",
        "likes": 150000,
        "duration_seconds": 45,
        "comments_hot": ["评论1", "评论2"],
        "url": "https://..."
      }
    ]
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [ViralVideo(**item) for item in data]
    except FileNotFoundError:
        print(f"[Crawler] 爆款文件不存在: {filepath}")
        return []
    except Exception as exc:
        print(f"[Crawler] 加载爆款文件失败: {exc}")
        return []


async def fetch_all_hot_topics() -> List[HotTopic]:
    """并发聚合所有热点来源，按热度降序排列"""
    news_task = fetch_financial_news()
    yicai_task = fetch_yicai_latest()
    weibo_task = fetch_weibo_hot()
    baidu_task = fetch_baidu_hot()
    toutiao_task = fetch_toutiao_hot()
    tencent_task = fetch_tencent_hot()

    news, yicai, weibo, baidu, toutiao, tencent = await asyncio.gather(
        news_task, yicai_task, weibo_task, baidu_task, toutiao_task, tencent_task
    )

    # 只聚合当前实测能返回标题和源头 URL 的公开来源，并穿插各来源，避免前端 limit 截断后只剩少数平台
    all_topics = _interleave_topic_groups([news, yicai, baidu, toutiao, tencent, weibo])

    # 全局去重（标题前15字为 key）
    seen, unique = set(), []
    for t in all_topics:
        key = t.title[:15]
        if key not in seen:
            seen.add(key)
            unique.append(t)

    return unique
