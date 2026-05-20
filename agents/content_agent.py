"""
Agent 3：内容解构 + 裁缝洗稿 Agent
- 解构爆款视频，提取爆款基因骨架（无原文）
- 裁缝拼接法：short视频取opening骨架，long视频取content骨架
- 语义级改写，生成原创口播底稿
"""
import json
import asyncio
from typing import List, Optional
from agents.base_agent import BaseAgent
from data_models import ViralGene, ViralVideo, TopicReport
from utils.llm import chat_json
from prompts.system_prompts import (
    DECONSTRUCT_SYSTEM, DECONSTRUCT_USER,
    REWRITE_SYSTEM, REWRITE_USER,
)
from utils.text_utils import oral_length_instruction, oral_length_profile


class ContentAgent(BaseAgent):
    def __init__(self):
        super().__init__("ContentAgent")

    async def _deconstruct_one(self, video: ViralVideo) -> Optional[ViralGene]:
        """解构单个爆款视频"""
        user_msg = DECONSTRUCT_USER.format(
            title=video.title,
            platform=video.platform,
            likes=video.likes,
            duration_seconds=video.duration_seconds,
            script=video.script[:1500] if video.script else "（无逐字稿）",
            comments=", ".join(video.comments_hot[:5]) if video.comments_hot else "无",
        )
        data = await chat_json(DECONSTRUCT_SYSTEM, user_msg)
        if not data:
            return None
        try:
            return ViralGene(
                hook_type=data.get("hook_type", "好奇类"),
                structure_type=data.get("structure_type", "钩子前置+顺叙展开"),
                opening_hook_template=data.get("opening_hook_template", ""),
                core_logic=data.get("core_logic", ""),
                emotion_points=data.get("emotion_points", []),
                interaction_points=data.get("interaction_points", []),
                key_phrase_pattern=data.get("key_phrase_pattern", ""),
                rhythm_design=data.get("rhythm_design", ""),
                duration_category=data.get("duration_category", video.duration_category),
                suitable_for=data.get("suitable_for", "content"),
            )
        except Exception as exc:
            self.warn(f"解构解析失败: {exc}")
            return None

    async def deconstruct_videos(self, videos: List[ViralVideo]) -> List[ViralGene]:
        """并发解构多个爆款视频"""
        self.log(f"解构 {len(videos)} 个爆款视频…")
        tasks = [self._deconstruct_one(v) for v in videos]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        genes = [r for r in results if isinstance(r, ViralGene)]
        self.log(f"成功解构 {len(genes)} 个骨架")
        return genes

    async def rewrite(
        self,
        topic: str,
        genes: List[ViralGene],
        topic_report: Optional[TopicReport] = None,
        source_text: str = "",
    ) -> str:
        """
        裁缝拼接洗稿：
        - opening_gene：来自 short 视频（<60s）
        - content_gene：来自 long 视频（>180s）
        - 若无匹配，各取最优
        """
        opening_gene = next(
            (g for g in genes if g.suitable_for == "opening"), genes[0] if genes else None
        )
        content_gene = next(
            (g for g in genes if g.suitable_for == "content"),
            genes[-1] if len(genes) > 1 else opening_gene,
        )

        if not opening_gene or not content_gene:
            self.warn("缺少足够骨架，使用单骨架改写")
            gene = opening_gene or content_gene
            if not gene:
                return ""
            opening_gene = content_gene = gene

        profile = oral_length_profile(source_text)
        user_msg = REWRITE_USER.format(
            topic=topic,
            opening_gene_json=json.dumps(
                opening_gene.model_dump(), ensure_ascii=False, indent=2
            ),
            content_gene_json=json.dumps(
                content_gene.model_dump(), ensure_ascii=False, indent=2
            ),
            length_instruction=oral_length_instruction(profile),
        )
        data = await chat_json(REWRITE_SYSTEM, user_msg)
        draft = data.get("oral_draft", "")
        self.log(f"洗稿完成，底稿 {len(draft)} 字，目标 {profile['min_chars']}-{profile['max_chars']} 字")
        return draft

    async def run(
        self,
        topic: str,
        videos: List[ViralVideo],
        topic_report: Optional[TopicReport] = None,
    ) -> str:
        """完整流程：解构 → 洗稿 → 返回原创底稿"""
        genes = await self.deconstruct_videos(videos)
        if not genes:
            self.warn("解构结果为空，跳过洗稿")
            return ""
        source_text = next((video.script for video in videos if video.script), "")
        return await self.rewrite(topic, genes, topic_report, source_text=source_text)
