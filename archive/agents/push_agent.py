"""
Agent 6：推送 Agent
- 格式化输出：选题 + 脚本 + 审核报告
- 推送至飞书机器人 Webhook（JSON Card 格式）
- 可选：企业微信 Webhook
- 同时写入本地文件（output/ 目录）
"""
import json
import os
import aiohttp
from typing import List, Tuple
from datetime import datetime
from agents.base_agent import BaseAgent
from data_models import TopicReport, ScriptVersion, ReviewReport
from config import config


class PushAgent(BaseAgent):
    def __init__(self):
        super().__init__("PushAgent")

    def _format_script_text(
        self,
        topic_report: TopicReport,
        script: ScriptVersion,
        review: ReviewReport,
    ) -> str:  # type: ignore
        """生成纯文本版本（保存本地 + 飞书备用）"""
        oral_0 = script.oral_scripts[0].content if script.oral_scripts else ""
        status = "✅ 审核通过" if review.final_approved else f"⚠️ {review.severity}"
        lines = [
            f"# 【{topic_report.topic}】脚本 V{script.version}",
            f"潜力分：{topic_report.potential_score:.0f} | {status} | 相似度：{review.similarity_score:.1%}",
            "",
            f"## 封面文案",
            script.cover_copy,
            "",
            f"## 直发语",
            script.direct_post,
            "",
            f"## 口播文案（钩子变体1）",
            oral_0,
            "",
        ]
        if len(script.oral_scripts) > 1:
            for s in script.oral_scripts[1:]:
                lines += [f"## 口播文案（钩子变体{s.hook_variant}）", s.content, ""]

        lines += [
            f"## 置顶评论",
            script.pinned_comment,
            "",
            f"## 审核报告",
            f"合规：{'✅' if review.compliance_passed else '❌'} | "
            f"口播质量：{'✅' if review.oral_passed else '❌'} | "
            f"专业性：{'✅' if review.professional_passed else '❌'}",
        ]
        if review.issues:
            lines.append("问题：" + "；".join(review.issues))
        if review.suggestions:
            lines.append("建议：" + "；".join(review.suggestions))

        return "\n".join(lines)

    def _build_feishu_card(
        self,
        topic_report: TopicReport,
        results: List[Tuple[ScriptVersion, ReviewReport]],
    ) -> dict:
        """构建飞书消息卡片（富文本 Card）"""
        approved = [(s, r) for s, r in results if r.final_approved]
        script, review = approved[0] if approved else results[0]
        oral_0 = script.oral_scripts[0].content if script.oral_scripts else ""

        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"🎬 今日脚本 | {topic_report.topic[:20]}",
                    },
                    "template": "blue",
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": (
                                f"**潜力分**：{topic_report.potential_score:.0f}分　"
                                f"**状态**：{'✅ 通过' if review.final_approved else '⚠️ 需修改'}\n"
                                f"**钩子类型**：{script.hook_type}　**结构**：{script.structure_type}"
                            ),
                        },
                    },
                    {"tag": "hr"},
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": f"**📌 封面文案**\n{script.cover_copy}"},
                    },
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": f"**💬 直发语**\n{script.direct_post}"},
                    },
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**🎤 口播文案**\n{oral_0[:800]}{'…' if len(oral_0) > 800 else ''}",
                        },
                    },
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": f"**📣 置顶评论**\n{script.pinned_comment}"},
                    },
                    {"tag": "hr"},
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": (
                                f"审核 | 合规{'✅' if review.compliance_passed else '❌'} "
                                f"口播{'✅' if review.oral_passed else '❌'} "
                                f"专业{'✅' if review.professional_passed else '❌'} "
                                f"相似度 {review.similarity_score:.1%}"
                            ),
                        },
                    },
                ],
            },
        }
        return card

    async def _push_feishu(self, payload: dict) -> bool:
        if not config.feishu_webhook:
            return False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    config.feishu_webhook,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    body = await resp.json(content_type=None)
                    if body.get("code") == 0:
                        self.log("飞书推送成功")
                        return True
                    self.warn(f"飞书推送失败: {body}")
        except Exception as exc:
            self.warn(f"飞书推送异常: {exc}")
        return False

    async def _push_weixin(self, content: str) -> bool:
        if not config.weixin_webhook:
            return False
        payload = {"msgtype": "text", "text": {"content": content[:4000]}}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    config.weixin_webhook,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    body = await resp.json(content_type=None)
                    if body.get("errcode") == 0:
                        self.log("企业微信推送成功")
                        return True
                    self.warn(f"企业微信推送失败: {body}")
        except Exception as exc:
            self.warn(f"企业微信推送异常: {exc}")
        return False

    def _save_local(
        self,
        topic_report: TopicReport,
        results: List[Tuple[ScriptVersion, ReviewReport]],
    ) -> str:
        """保存到本地 output/ 目录"""
        os.makedirs("output", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        safe_topic = topic_report.topic[:20].replace("/", "_").replace(" ", "_")
        filepath = f"output/{ts}_{safe_topic}.md"

        parts = []
        for script, review in results:
            parts.append(self._format_script_text(topic_report, script, review))
            parts.append("\n\n---\n\n")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("".join(parts))

        self.log(f"已保存至本地: {filepath}")
        return filepath

    async def run(
        self,
        topic_report: TopicReport,
        results: List[Tuple[ScriptVersion, ReviewReport]],
    ) -> dict:
        """推送结果：本地保存 + 飞书 + 企业微信"""
        filepath = self._save_local(topic_report, results)

        # 只推送审核通过的脚本，没有通过则推全部
        approved = [(s, r) for s, r in results if r.final_approved]
        push_results = approved if approved else results

        # 飞书
        card = self._build_feishu_card(topic_report, push_results)
        feishu_ok = await self._push_feishu(card)

        # 企业微信（用文本格式）
        script0, review0 = push_results[0]
        text_content = self._format_script_text(topic_report, script0, review0)
        weixin_ok = await self._push_weixin(text_content)

        return {
            "local_file": filepath,
            "feishu_pushed": feishu_ok,
            "weixin_pushed": weixin_ok,
        }
