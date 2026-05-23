"""热点选题相关性过滤。

目标是把公开热榜先收束到财经、科技产业、商业和职场经济方向，避免纯社会/灾害/娱乐热点进入脚本生成队列。
"""
from __future__ import annotations

import math
from typing import Iterable, List

from data_models import HotTopic


CORE_FINANCE_KEYWORDS = [
    "经济", "财经", "金融", "股市", "股票", "A股", "港股", "美股", "基金", "债券",
    "期货", "外汇", "汇率", "人民币", "美元", "黄金", "油价", "原油", "楼市", "房价",
    "房贷", "利率", "降息", "加息", "央行", "美联储", "通胀", "CPI", "PPI", "GDP",
    "财政", "税", "关税", "贸易", "出口", "进口", "消费", "投资", "理财", "保险",
    "银行", "券商", "上市", "IPO", "退市", "并购", "融资", "估值", "市值", "财报",
    "营收", "利润", "亏损", "分红", "裁员", "薪资", "就业", "招聘", "指数", "纳指",
    "道指", "标普", "费城半导体", "半导体指数",
]

INDUSTRY_KEYWORDS = [
    "芯片", "半导体", "AI", "人工智能", "大模型", "算力", "机器人", "自动驾驶",
    "新能源", "电池", "光伏", "储能", "医药", "创新药", "游戏", "电商", "直播带货",
    "互联网", "平台经济", "地产", "制造业", "供应链", "航运", "物流", "出海",
]

MARKET_ACTION_KEYWORDS = [
    "上涨", "下跌", "涨", "跌", "暴涨", "暴跌", "大涨", "大跌", "反弹", "回调", "创新高",
    "新低", "涨停", "跌停", "增持", "减持", "回购", "收购", "涨价", "降价", "订单",
    "交付", "销量", "业绩", "增长", "放缓", "破产", "停产", "扩产", "监管", "处罚",
]

BRIDGE_ENTITIES = [
    "腾讯", "阿里", "字节", "百度", "美团", "京东", "拼多多", "华为", "小米", "比亚迪",
    "宁德时代", "蔚来", "理想", "小鹏", "苹果", "微软", "谷歌", "英伟达", "特斯拉",
    "高通", "英特尔", "AMD", "台积电", "三星", "OpenAI", "DeepSeek",
]

LOW_RELEVANCE_KEYWORDS = [
    "洪水", "防汛", "暴雨", "台风", "地震", "救援", "火灾", "车祸", "事故", "遇难",
    "执法", "清退", "违法", "犯罪", "案件", "警方", "通缉", "判决", "医院", "手术",
    "明星", "恋情", "离婚", "出轨", "综艺", "演唱会", "体育", "比赛", "高考", "中考",
]

FINANCE_SOURCES = ["第一财经", "经济观察网", "中国新闻网财经", "36氪"]


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    lower_text = text.lower()
    return any(keyword in text or keyword.lower() in lower_text for keyword in keywords)


def topic_focus_score(topic: HotTopic) -> float:
    """返回热点与财经/科技商业内容方向的相关性分数。"""
    text = f"{topic.title} {topic.summary} {' '.join(topic.tags)}"
    source = topic.source or ""
    score = 0.0

    has_core = _contains_any(text, CORE_FINANCE_KEYWORDS)
    has_industry = _contains_any(text, INDUSTRY_KEYWORDS)
    has_action = _contains_any(text, MARKET_ACTION_KEYWORDS)
    has_bridge_entity = _contains_any(text, BRIDGE_ENTITIES)
    has_low_relevance = _contains_any(text, LOW_RELEVANCE_KEYWORDS)

    if any(name in source for name in FINANCE_SOURCES):
        score += 24
    elif "财经" in text or "财经" in source:
        score += 18

    if has_core:
        score += 45
    if has_industry:
        score += 24 if (has_core or has_action) else 14
    if has_action:
        score += 22
    if has_bridge_entity:
        score += 18 if (has_core or has_action or has_industry) else 8

    # 纯社会/灾害/娱乐类热点只有在同时具备明确财经信号时才保留。
    if has_low_relevance and not (has_core or (has_industry and has_action)):
        score -= 45
    elif has_low_relevance:
        score -= 15

    heat = float(topic.heat_score or 0)
    if score > 0 and heat > 0:
        score += min(10, math.log10(heat + 1) * 2)

    return score


def rank_relevant_topics(
    topics: Iterable[HotTopic],
    limit: int = 60,
    min_score: float = 28,
) -> List[HotTopic]:
    """按相关性过滤并排序；若过滤过严，则保留少量正相关兜底。"""
    scored = [(topic_focus_score(topic), topic) for topic in topics]
    focused = [(score, topic) for score, topic in scored if score >= min_score]
    if not focused:
        focused = [(score, topic) for score, topic in scored if score > 0]

    focused.sort(key=lambda item: (item[0], float(item[1].heat_score or 0)), reverse=True)
    return [topic for _, topic in focused[:limit]]