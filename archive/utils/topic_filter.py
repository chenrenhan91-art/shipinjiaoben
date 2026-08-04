"""热点选题金融科技相关性过滤。

目标是把公开热榜先收束到金融、资本市场、宏观经济、金融科技、AI、半导体、新能源和平台经济方向，避免纯社会、灾害、娱乐热点进入脚本生成队列。
"""
from __future__ import annotations

import math
import re
from typing import Iterable, List

from data_models import HotTopic


CORE_FINANCE_KEYWORDS = [
    "经济", "财经", "金融", "股市", "股票", "A股", "港股", "美股", "基金", "债券",
    "期货", "外汇", "汇率", "人民币", "美元", "黄金", "油价", "原油", "楼市", "房价",
    "房贷", "利率", "降息", "加息", "央行", "美联储", "通胀", "CPI", "PPI", "GDP",
    "财政", "税", "关税", "贸易", "出口", "消费", "投资", "投资者", "投资人", "资产配置", "理财", "保险",
    "银行", "券商", "上市", "IPO", "退市", "并购", "融资", "估值", "市值", "财报",
    "营收", "利润", "亏损", "分红", "指数", "纳指",
    "道指", "标普", "费城半导体", "半导体指数", "证券", "证监会", "银保", "金融市场",
    "资本市场", "沪指", "深成指", "创业板指", "科创板", "北交所", "个股", "附股",
    "板块", "概念股", "国债", "可转债", "收益率", "成交额", "贷款", "存款", "信用卡",
    "理财产品", "私募", "公募", "北向资金", "外资", "主力资金", "净流入", "净流出",
]

TECH_FINANCE_KEYWORDS = [
    "科技", "金融科技", "科创", "芯片", "半导体", "AI", "人工智能", "大模型", "算力", "云计算",
    "数据中心", "量子计算", "机器人", "自动驾驶", "低空经济", "商业航天",
    "新能源", "电池", "光伏", "储能", "医药", "创新药", "游戏", "电商", "直播带货",
    "互联网", "平台经济", "地产", "制造业", "供应链", "航运", "物流", "出海", "汽车",
    "电动汽车", "消费电子", "PCB", "MLCC", "无人驾驶", "智能驾驶", "支付", "数字人民币",
]

MARKET_ACTION_KEYWORDS = [
    "上涨", "下跌", "涨", "跌", "暴涨", "暴跌", "大涨", "大跌", "反弹", "回调", "创新高",
    "新低", "涨停", "跌停", "增持", "减持", "回购", "收购", "涨价", "降价", "订单",
    "交付", "销量", "业绩", "增长", "放缓", "破产", "停产", "扩产", "监管", "处罚",
    "封板", "盘前", "盘后", "开盘", "收盘", "重罚", "降费", "降准", "加仓", "减仓",
    "收涨", "收跌", "激增", "飙升", "跳水", "领涨", "领跌", "走强", "走低",
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
    "法官", "泄密", "召回", "缺陷汽车",
]

MARKET_SIGNAL_TITLE_KEYWORDS = [
    "股价", "股票", "A股", "港股", "美股", "上市", "财报", "营收", "利润", "估值",
    "融资", "并购", "收购", "IPO", "退市", "涨停", "跌停", "大涨", "大跌", "基金", "证券",
]

FINANCE_SOURCES = [
    "第一财经", "经济观察网", "中国新闻网财经", "东方财富", "财联社", "证券时报",
    "中国人民银行", "证监会", "FT中文网", "36氪",
]

HOT_LIST_SOURCES = [
    "百度热搜", "微博热搜", "今日头条热榜", "腾讯热榜",
]


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
    """返回热点与金融科技内容方向的相关性分数。"""
    title_text = str(topic.title or "").replace("毛利率", "毛利")
    summary_text = str(topic.summary or "").replace("毛利率", "毛利")
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
    has_market_signal_title = _contains_any(title_text, MARKET_SIGNAL_TITLE_KEYWORDS)

    if any(name in source for name in FINANCE_SOURCES):
        score += 16
    elif any(name in source for name in HOT_LIST_SOURCES):
        score += 6
    elif "财经" in text or "财经" in source:
        score += 14

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

    if ("召回" in text or "缺陷汽车" in text) and not has_market_signal_title:
        score -= 45

    # 纯社会/灾害/娱乐类热点只有在同时具备强金融或科技产业信号时才保留。
    if has_low_relevance and not (has_core_title or (has_tech_title and has_action)):
        score -= 45
    elif has_low_relevance:
        score -= 20

    heat = float(topic.heat_score or 0)
    if score > 0 and heat > 0:
        score += min(10, math.log10(heat + 1) * 2)

    return score


def rank_relevant_topics(
    topics: Iterable[HotTopic],
    limit: int = 60,
    min_score: float = 36,
) -> List[HotTopic]:
    """按金融科技相关性过滤并排序；不输出未达到阈值的热点。"""
    scored = [(topic_focus_score(topic), topic) for topic in topics]
    focused = [(score, topic) for score, topic in scored if score >= min_score]

    focused.sort(key=lambda item: (item[0], float(item[1].heat_score or 0)), reverse=True)
    return [topic for _, topic in focused[:limit]]