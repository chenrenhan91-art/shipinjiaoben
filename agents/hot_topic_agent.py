"""
Agent 1：热点感知 Agent
- 从 36氪 RSS、百度热搜、今日头条热榜、腾讯热榜、微博热搜聚合热点
- 支持财经、科技、娱乐、社会、教育、法律、体育等各类自媒体选题
- 热搜平台全量保留（不按主题过滤），关键词只用于加权排序
- 按加权热度降序，输出 Top60
"""
from typing import List
from agents.base_agent import BaseAgent
from data_models import HotTopic
from utils.crawler import fetch_all_hot_topics

# 财经/科技关键词：热度 ×3（财经IP首选）
FINANCE_KEYWORDS = [
    "经济", "股市", "股票", "A股", "港股", "基金", "债券", "楼市", "房价",
    "利率", "央行", "美联储", "通胀", "GDP", "财政", "汇率", "黄金", "石油",
    "科技股", "新能源", "消费", "就业", "银行", "保险", "理财", "投资",
    "上市", "IPO", "退市", "暴跌", "暴涨", "熔断", "降息", "加息",
    "芯片", "AI", "人工智能", "大模型", "科技", "贸易", "关税", "制裁",
    "汽车", "电动车", "互联网", "数字经济", "碳中和", "双碳",
]

# 政经/时事关键词：热度 ×2.5
HOT_EVENT_KEYWORDS = [
    "特朗普", "美国", "中美", "普京", "俄罗斯", "乌克兰", "日本", "欧盟",
    "习近平", "国务院", "政府", "政策", "会议", "峰会", "谈判", "制裁",
    "战争", "冲突", "灾难", "地震", "疫情", "事故",
]

# 通用高传播关键词（娱乐/社会/生活）：热度 ×1.5
GENERAL_VIRAL_KEYWORDS = [
    "明星", "网红", "出轨", "离婚", "结婚", "恋爱", "塌房", "翻车",
    "综艺", "电影", "票房", "爆火", "爆款", "出圈",
    "考研", "高考", "留学", "升学", "教育", "学校",
    "医院", "医疗", "手术", "癌症", "健康", "减肥",
    "法院", "判决", "案件", "警方", "犯罪", "诈骗",
    "工资", "裁员", "失业", "跳槽", "副业", "创业",
    "买房", "租房", "装修", "旅游", "景区",
    "奥运", "世界杯", "体育", "冠军", "夺冠",
    "AI", "机器人", "自动驾驶", "芯片", "苹果", "华为", "小米",
]


def _boost_score(topic: HotTopic) -> float:
    """按关键词对热度加权，实现分层优先级排序"""
    text = topic.title + topic.summary
    base = topic.heat_score + 1  # +1 避免 heat_score=0 时排序失效
    if any(kw in text for kw in FINANCE_KEYWORDS):
        return base * 3
    if any(kw in text for kw in HOT_EVENT_KEYWORDS):
        return base * 2.5
    if any(kw in text for kw in GENERAL_VIRAL_KEYWORDS):
        return base * 1.5
    return base


class HotTopicAgent(BaseAgent):
    def __init__(self):
        super().__init__("HotTopicAgent")

    async def run(self) -> List[HotTopic]:
        self.log("开始抓取热点（36氪/百度/头条/腾讯/微博）…")
        topics = await fetch_all_hot_topics()
        self.log(f"原始热点 {len(topics)} 条")

        # 36氪资讯全量保留；热搜平台全量保留（不按主题硬过滤）
        # 通过加权排序让相关话题自然浮到前排
        topics.sort(key=_boost_score, reverse=True)

        from collections import Counter
        src_dist = Counter(t.source.split("/")[0] for t in topics[:60])
        self.log(f"Top60 来源分布: {dict(src_dist)}")
        return topics[:60]  # 最多送 60 条给决策层
