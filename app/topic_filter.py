"""热点排序与可选领域过滤。

默认通用模式不过滤；scope=finance 时按金融科技相关性收束。
"""
from __future__ import annotations

import math
import re
from typing import Iterable, List

from app.hot_topics import HotTopic

CORE_FINANCE_KEYWORDS = [
    "经济", "财经", "金融", "股市", "股票", "A股", "港股", "美股", "基金", "债券",
    "期货", "外汇", "汇率", "人民币", "美元", "黄金", "油价", "原油", "楼市", "房价",
    "房贷", "利率", "降息", "加息", "央行", "美联储", "通胀", "CPI", "PPI", "GDP",
    "财政", "税", "关税", "贸易", "出口", "消费", "投资", "理财", "保险",
    "银行", "券商", "上市", "IPO", "退市", "并购", "融资", "估值", "市值", "财报",
    "营收", "利润", "亏损", "分红", "指数", "证券", "证监会",
]

TECH_FINANCE_KEYWORDS = [
    "科技", "金融科技", "科创", "芯片", "半导体", "AI", "人工智能", "大模型", "算力",
    "云计算", "新能源", "电池", "光伏", "储能", "电商", "平台经济", "出海",
    "电动汽车", "支付", "数字人民币",
]

MARKET_ACTION_KEYWORDS = [
    "上涨", "下跌", "暴涨", "暴跌", "大涨", "大跌", "反弹", "回调", "创新高",
    "涨停", "跌停", "增持", "减持", "回购", "收购", "涨价", "降价", "业绩",
    "增长", "破产", "监管", "处罚", "降准", "加仓", "减仓",
]

BRIDGE_ENTITIES = [
    "腾讯", "阿里", "字节", "百度", "美团", "京东", "拼多多", "华为", "小米", "比亚迪",
    "宁德时代", "苹果", "微软", "谷歌", "英伟达", "特斯拉", "OpenAI", "DeepSeek",
]

LOW_RELEVANCE_KEYWORDS = [
    "洪水", "防汛", "暴雨", "台风", "地震", "救援", "火灾", "车祸", "事故", "遇难",
    "执法", "清退", "违法", "犯罪", "案件", "警方", "明星", "恋情", "离婚", "综艺",
]

FINANCE_SOURCES = [
    "第一财经", "经济观察网", "中国新闻网财经", "东方财富", "财联社", "证券时报",
    "中国人民银行", "证监会", "FT中文网", "36氪",
]

HOT_LIST_SOURCES = ["百度热搜", "微博热搜", "今日头条热榜", "腾讯热榜", "抖音热榜", "B站热门"]


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    lower_text = text.lower()
    for keyword in keywords:
        if keyword in text:
            return True
        lower_keyword = keyword.lower()
        if keyword.isascii() and keyword.isalnum():
            if re.search(rf"(?<![a-z0-9]){re.escape(lower_keyword)}(?![a-z0-9])", lower_text):
                return True
        elif lower_keyword in lower_text:
            return True
    return False


def topic_focus_score(topic: HotTopic) -> float:
    title_text = str(topic.title or "")
    summary_text = str(topic.summary or "")
    text = f"{title_text} {summary_text}"
    source = topic.source or ""
    score = 0.0

    has_core_title = _contains_any(title_text, CORE_FINANCE_KEYWORDS)
    has_core_summary = _contains_any(summary_text, CORE_FINANCE_KEYWORDS)
    has_core = has_core_title or has_core_summary
    has_tech_title = _contains_any(title_text, TECH_FINANCE_KEYWORDS)
    has_tech_summary = _contains_any(summary_text, TECH_FINANCE_KEYWORDS)
    has_tech = has_tech_title or has_tech_summary
    has_action = _contains_any(text, MARKET_ACTION_KEYWORDS)
    has_bridge_entity = _contains_any(text, BRIDGE_ENTITIES)
    has_low_relevance = _contains_any(text, LOW_RELEVANCE_KEYWORDS)

    if any(name in source for name in FINANCE_SOURCES):
        score += 16
    elif any(name in source for name in HOT_LIST_SOURCES):
        score += 6

    if has_core_title:
        score += 44
    elif has_core_summary:
        score += 24
    if has_tech_title:
        score += 30
    elif has_tech_summary:
        score += 16
    if has_action:
        score += 18
    if has_bridge_entity and (has_core or has_tech or has_action):
        score += 8
    if has_low_relevance and not (has_core_title or (has_tech_title and has_action)):
        score -= 45
    elif has_low_relevance:
        score -= 20

    heat = float(topic.heat_score or 0)
    if score > 0 and heat > 0:
        score += min(10, math.log10(heat + 1) * 2)
    return score


def rank_by_heat(topics: Iterable[HotTopic], limit: int = 80) -> List[HotTopic]:
    """通用排序：各平台内按热度排序后穿插，保证多源都能出现。"""
    by_source: dict[str, List[HotTopic]] = {}
    for topic in topics:
        by_source.setdefault(topic.source, []).append(topic)
    for group in by_source.values():
        group.sort(key=lambda t: float(t.heat_score or 0), reverse=True)

    priority = [
        "抖音热榜", "微博热搜", "百度热搜", "今日头条热榜",
        "腾讯热榜", "B站热门", "第一财经", "东方财富",
    ]
    ordered_names = [n for n in priority if n in by_source]
    ordered_names += [n for n in by_source if n not in ordered_names]
    groups = [by_source[n] for n in ordered_names]

    mixed: List[HotTopic] = []
    max_len = max((len(g) for g in groups), default=0)
    for i in range(max_len):
        for group in groups:
            if i < len(group):
                mixed.append(group[i])
            if len(mixed) >= limit:
                return mixed
    return mixed[:limit]


def rank_relevant_topics(
    topics: Iterable[HotTopic],
    limit: int = 60,
    min_score: float = 36,
) -> List[HotTopic]:
    scored = [(topic_focus_score(topic), topic) for topic in topics]
    focused = [(score, topic) for score, topic in scored if score >= min_score]
    focused.sort(key=lambda item: (item[0], float(item[1].heat_score or 0)), reverse=True)
    return [topic for _, topic in focused[:limit]]


def _split_keywords(query: str) -> List[str]:
    parts = re.split(r"[\s,，、;；|/]+", (query or "").strip())
    return [p for p in parts if p]


def keyword_match_score(topic: HotTopic, query: str) -> float:
    """按用户关键词给热点打分；未命中返回 0。"""
    terms = _split_keywords(query)
    if not terms:
        return 0.0
    title = str(topic.title or "")
    summary = str(topic.summary or "")
    hay = f"{title} {summary}".lower()
    score = 0.0
    hits = 0
    for term in terms:
        t = term.lower()
        if t in title.lower():
            score += 40 + min(20, len(term) * 2)
            hits += 1
        elif t in hay:
            score += 18 + min(10, len(term))
            hits += 1
    if hits == 0:
        return 0.0
    # 多词命中加权；热度作轻微加成
    score += (hits - 1) * 12
    heat = float(topic.heat_score or 0)
    if heat > 0:
        score += min(15, math.log10(heat + 1) * 3)
    return score


def filter_by_keyword(
    topics: Iterable[HotTopic],
    query: str,
    limit: int = 80,
) -> List[HotTopic]:
    """按用户输入关键词筛选并排序热点。"""
    scored = [(keyword_match_score(topic, query), topic) for topic in topics]
    matched = [(score, topic) for score, topic in scored if score > 0]
    matched.sort(key=lambda item: (item[0], float(item[1].heat_score or 0)), reverse=True)
    return [topic for _, topic in matched[:limit]]
