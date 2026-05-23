"""
Agent 1：热点感知 Agent
- 从第一财经、东方财富、财联社、证券时报、央行、证监会等公开金融源聚合热点
- 只保留金融、证券市场、宏观经济、监管政策和资产配置高度相关选题
- 按金融相关性和热度排序，输出 Top60
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
        self.log("开始抓取公开金融热点（第一财经/东方财富/财联社/证券时报/央行/证监会）…")
        topics = await fetch_all_hot_topics()
        self.log(f"原始热点 {len(topics)} 条")

        # 金融收束：先过滤非金融热点，再按相关性排序
        topics = rank_relevant_topics(topics, limit=60)
        self.log(f"金融相关热点 {len(topics)} 条")

        from collections import Counter
        src_dist = Counter(t.source.split("/")[0] for t in topics[:60])
        self.log(f"Top60 来源分布: {dict(src_dist)}")
        return topics[:60]  # 最多送 60 条给决策层
