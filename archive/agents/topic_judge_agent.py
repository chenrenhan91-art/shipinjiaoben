"""
Agent 2：选题决策 Agent
- 输入：热点列表
- 输出：Top10 爆款选题报告（含潜力分、爆款依据、匹配法则、推荐结构）
"""
import json
from typing import List
from agents.base_agent import BaseAgent
from data_models import HotTopic, TopicReport
from utils.llm import chat_json
from prompts.system_prompts import TOPIC_JUDGE_SYSTEM, TOPIC_JUDGE_USER


class TopicJudgeAgent(BaseAgent):
    def __init__(self):
        super().__init__("TopicJudgeAgent")

    async def run(self, topics: List[HotTopic]) -> List[TopicReport]:
        self.log(f"开始选题决策，输入热点 {len(topics)} 条…")

        # 构建简洁的热点摘要送给 LLM（控制 token）
        topics_summary = [
            {
                "title": t.title,
                "source": t.source,
                "summary": t.summary[:100],
                "heat_score": t.heat_score,
            }
            for t in topics[:40]
        ]

        user_msg = TOPIC_JUDGE_USER.format(
            hot_topics_json=json.dumps(topics_summary, ensure_ascii=False, indent=2)
        )

        data = await chat_json(TOPIC_JUDGE_SYSTEM, user_msg)
        raw_topics = data.get("top_topics", [])

        reports: List[TopicReport] = []
        for item in raw_topics[:10]:
            try:
                reports.append(TopicReport(
                    topic=item.get("topic", ""),
                    potential_score=float(item.get("potential_score", 0)),
                    viral_basis=item.get("viral_basis", ""),
                    matched_criteria=item.get("matched_criteria", []),
                    key_hooks=item.get("key_hooks", []),
                    recommended_structure=item.get("recommended_structure", ""),
                ))
            except Exception as exc:
                self.warn(f"选题解析失败: {exc}")

        self.log(f"筛选出 {len(reports)} 条爆款选题")
        return reports
