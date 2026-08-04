"""
Agent 1：热点感知 Agent
- 从第一财经、东方财富、财联社、证券时报、央行、证监会、36氪和泛热榜聚合候选热点
- 只保留金融、证券市场、宏观经济、金融科技、AI、半导体、新能源等相关选题
- 按金融科技相关性和热度排序，输出 Top60
"""
from typing import List
from agents.base_agent import BaseAgent
from data_models import HotTopic
from utils.crawler import fetch_all_hot_topics
from utils.topic_filter import rank_relevant_topics


class HotTopicAgent(BaseAgent):
    def __init__(self):
        super().__init__("HotTopicAgent")

    async def run(self) -> List[HotTopic]:
        self.log("开始抓取公开金融科技热点（金融源/36氪/百度/头条/腾讯/微博）…")
        topics = await fetch_all_hot_topics()
        self.log(f"原始热点 {len(topics)} 条")

        # 金融科技收束：先过滤泛社会/娱乐/灾害热点，再按相关性排序
        topics = rank_relevant_topics(topics, limit=60)
        self.log(f"金融科技相关热点 {len(topics)} 条")

        from collections import Counter
        src_dist = Counter(t.source.split("/")[0] for t in topics[:60])
        self.log(f"Top60 来源分布: {dict(src_dist)}")
        return topics[:60]  # 最多送 60 条给决策层
