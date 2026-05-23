"""热点选题金融相关性过滤。

目标是把公开热榜先收束到金融、证券市场、宏观经济、监管政策和资产配置方向，避免纯科技、商业、社会、灾害、娱乐热点进入脚本生成队列。
"""
from __future__ import annotations

import math
from typing import Iterable, List

from data_models import HotTopic


CORE_FINANCE_KEYWORDS = [
    "财经", "金融", "股市", "股票", "A股", "港股", "美股", "基金", "债券",
    "期货", "外汇", "汇率", "人民币", "美元", "黄金", "油价", "原油", "楼市", "房价",
    "房贷", "利率", "降息", "加息", "央行", "美联储", "通胀", "CPI", "PPI", "GDP",
    "财政", "税", "关税", "投资者", "投资人", "资产配置", "理财", "保险",
    "银行", "券商", "上市", "IPO", "退市", "并购", "融资", "估值", "市值", "财报",
    "营收", "利润", "亏损", "分红", "指数", "纳指",
    "道指", "标普", "费城半导体", "半导体指数", "证券", "证监会", "银保", "金融市场",
    "资本市场", "沪指", "深成指", "创业板指", "科创板", "北交所", "个股", "附股",
    "板块", "概念股", "国债", "可转债", "收益率", "成交额", "贷款", "存款", "信用卡",
    "理财产品", "私募", "公募", "北向资金", "外资", "主力资金", "净流入", "净流出",
]

INDUSTRY_CONTEXT_KEYWORDS = [
    "芯片", "半导体", "AI", "人工智能", "大模型", "算力", "机器人", "自动驾驶",
    "新能源", "电池", "光伏", "储能", "医药", "创新药", "游戏", "电商", "直播带货",
    "互联网", "平台经济", "地产", "制造业", "供应链", "航运", "物流", "出海", "汽车",
    "电动汽车", "消费电子", "PCB", "MLCC", "量子计算",
]

MARKET_ACTION_KEYWORDS = [
    "上涨", "下跌", "暴涨", "暴跌", "大涨", "大跌", "反弹", "回调", "创新高",
    "新低", "涨停", "跌停", "增持", "减持", "回购", "收购", "涨价", "降价", "订单",
    "交付", "销量", "业绩", "增长", "放缓", "破产", "停产", "扩产", "监管", "处罚",
    "封板", "盘前", "盘后", "开盘", "收盘", "重罚", "降费", "降准", "加仓", "减仓",
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
    "感染", "病例", "邮轮", "大雾", "蓝色预警", "黄色预警", "总统", "总理", "政府职务",
    "法官", "泄密",
]

FINANCE_SOURCES = [
    "第一财经", "经济观察网", "中国新闻网财经", "东方财富", "财联社", "证券时报",
    "中国人民银行", "证监会", "FT中文网",
]


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    lower_text = text.lower()
    return any(keyword in text or keyword.lower() in lower_text for keyword in keywords)


def topic_focus_score(topic: HotTopic) -> float:
    """返回热点与金融内容方向的相关性分数。"""
    title_text = str(topic.title or "").replace("毛利率", "毛利")
    summary_text = str(topic.summary or "").replace("毛利率", "毛利")
    text = f"{title_text} {summary_text}"
    source = topic.source or ""
    score = 0.0

    has_core_title = _contains_any(title_text, CORE_FINANCE_KEYWORDS)
    has_core_summary = _contains_any(summary_text, CORE_FINANCE_KEYWORDS)
    has_core = has_core_title or has_core_summary
    has_industry_context = _contains_any(text, INDUSTRY_CONTEXT_KEYWORDS)
    has_action = _contains_any(text, MARKET_ACTION_KEYWORDS)
    has_bridge_entity = _contains_any(text, BRIDGE_ENTITIES)
    has_low_relevance = _contains_any(text, LOW_RELEVANCE_KEYWORDS)

    if any(name in source for name in FINANCE_SOURCES):
        score += 16
    elif "财经" in text or "财经" in source:
        score += 14

    if has_core_title:
        score += 55
    elif has_core_summary:
        score += 25
    if has_action:
        score += 22
    if has_industry_context and (has_core_title or has_action):
        score += 10
    if has_bridge_entity and (has_core_title or has_action):
        score += 8

    # 纯社会/灾害/娱乐类热点只有在同时具备强金融信号时才保留。
    if has_low_relevance and not has_core:
        score -= 45
    elif has_low_relevance:
        score -= 25

    heat = float(topic.heat_score or 0)
    if score > 0 and heat > 0:
        score += min(10, math.log10(heat + 1) * 2)

    return score


def rank_relevant_topics(
    topics: Iterable[HotTopic],
    limit: int = 60,
    min_score: float = 55,
) -> List[HotTopic]:
    """按金融相关性过滤并排序；不输出未达到金融阈值的热点。"""
    scored = [(topic_focus_score(topic), topic) for topic in topics]
    focused = [(score, topic) for score, topic in scored if score >= min_score]

    focused.sort(key=lambda item: (item[0], float(item[1].heat_score or 0)), reverse=True)
    return [topic for _, topic in focused[:limit]]