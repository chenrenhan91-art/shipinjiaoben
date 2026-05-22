"""
Agent 4：标准化脚本生成 Agent
- 输入：选题报告 + 原创口播底稿
- 输出：完整脚本（封面+直发语+口播3版本×3钩子变体+置顶评论）
"""
import json
from typing import List
from agents.base_agent import BaseAgent
from data_models import TopicReport, GeneratedScripts, ScriptVersion, OralScript
from utils.llm import chat_json
from utils.text_utils import (
    check_cover_length,
    oral_length_instruction,
    oral_length_profile,
    sanitize_douyin_text,
)
from prompts.system_prompts import SCRIPT_GEN_SYSTEM, SCRIPT_GEN_USER


class ScriptAgent(BaseAgent):
    def __init__(self):
        super().__init__("ScriptAgent")

    async def run(
        self,
        topic: str,
        oral_draft: str,
        topic_report: TopicReport,
    ) -> GeneratedScripts:
        self.log(f"生成脚本：{topic[:20]}…")
        length_profile = oral_length_profile(oral_draft)

        user_msg = SCRIPT_GEN_USER.format(
            topic=topic,
            topic_report_json=json.dumps(
                topic_report.model_dump(), ensure_ascii=False, indent=2
            ),
            oral_draft=oral_draft[:2000],
            length_instruction=oral_length_instruction(length_profile),
        )

        data = await chat_json(SCRIPT_GEN_SYSTEM, user_msg)
        raw_scripts = data.get("scripts", [])

        versions: List[ScriptVersion] = []
        for item in raw_scripts:
            try:
                cover = item.get("cover_copy", "")
                # 自动截断超长封面
                if not check_cover_length(cover):
                    self.warn(f"封面文案超12字，已提示修改：{cover}")

                oral_list = [
                    OralScript(
                        hook_variant=o.get("hook_variant", idx + 1),
                        content=sanitize_douyin_text(
                            o.get("content", ""), role="oral", topic=topic
                        ),
                    )
                    for idx, o in enumerate(item.get("oral_scripts", []))
                ]
                versions.append(ScriptVersion(
                    version=item.get("version", len(versions) + 1),
                    cover_copy=cover,
                    direct_post=sanitize_douyin_text(
                        item.get("direct_post", ""), role="direct_post", topic=topic
                    ),
                    oral_scripts=oral_list,
                    pinned_comment=sanitize_douyin_text(
                        item.get("pinned_comment", ""), role="pinned", topic=topic
                    ),
                    hook_type=item.get("hook_type", ""),
                    structure_type=item.get("structure_type", ""),
                ))
            except Exception as exc:
                self.warn(f"脚本版本解析失败: {exc}")

        self.log(f"生成 {len(versions)} 个脚本版本")
        return GeneratedScripts(topic=topic, scripts=versions)
