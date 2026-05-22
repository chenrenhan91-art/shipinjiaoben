"""
Agent 5：三重审核 Agent
- 合规初审（财经禁词 + 违规内容）
- 口播质量复审（结构/废话/卡点）
- 专业校验（概念/数据/逻辑）
- 同时计算与原始爆款的相似度
"""
import json
from typing import List, Optional, Tuple
from agents.base_agent import BaseAgent
from data_models import ScriptVersion, ReviewReport, GeneratedScripts
from utils.llm import chat_json
from utils.text_utils import has_douyin_risk, similarity
from prompts.system_prompts import REVIEW_SYSTEM, REVIEW_USER


class ReviewAgent(BaseAgent):
    def __init__(self):
        super().__init__("ReviewAgent")

    async def _review_one(
        self,
        script: ScriptVersion,
        original_texts: List[str],
    ) -> Tuple[ScriptVersion, ReviewReport]:
        """审核单个脚本版本"""
        # 取第一个钩子变体的口播内容作为审核对象
        oral_content = script.oral_scripts[0].content if script.oral_scripts else ""

        user_msg = REVIEW_USER.format(
            cover_copy=script.cover_copy,
            direct_post=script.direct_post,
            oral_content=oral_content,
            pinned_comment=script.pinned_comment,
        )
        data = await chat_json(REVIEW_SYSTEM, user_msg)

        # 计算与原始爆款的最高相似度
        max_sim = 0.0
        if original_texts and oral_content:
            sims = [similarity(oral_content, orig) for orig in original_texts]
            max_sim = max(sims) if sims else 0.0

        dedup_passed = max_sim <= 0.20

        compliance_passed = data.get("compliance_passed", False)
        oral_passed = data.get("oral_passed", False)
        professional_passed = data.get("professional_passed", True)
        issues = data.get("issues", [])
        suggestions = data.get("suggestions", [])

        risk_text = "\n".join([
            script.cover_copy,
            script.direct_post,
            oral_content,
            script.pinned_comment,
        ])
        if has_douyin_risk(risk_text):
            compliance_passed = False
            issues.append("包含抖音财经内容易限流/违规的话术，如留代码、诊股、私信或加群导流")

        if not dedup_passed:
            issues.append(f"文本相似度 {max_sim:.1%}，超过 20% 阈值，需进一步洗稿")

        final_approved = compliance_passed and oral_passed and dedup_passed
        severity = "pass"
        if not compliance_passed:
            severity = "major"
        elif not oral_passed or not dedup_passed:
            severity = "minor"

        report = ReviewReport(
            compliance_passed=compliance_passed,
            oral_passed=oral_passed,
            professional_passed=professional_passed,
            issues=issues,
            suggestions=suggestions,
            severity=severity,
            final_approved=final_approved,
            similarity_score=max_sim,
        )
        return script, report

    async def run(
        self,
        generated: GeneratedScripts,
        original_texts: Optional[List[str]] = None,
    ) -> List[Tuple[ScriptVersion, ReviewReport]]:
        """
        批量审核所有脚本版本，返回 (脚本, 审核报告) 列表。
        original_texts：原始爆款逐字稿，用于查重。
        """
        self.log(f"开始审核 {len(generated.scripts)} 个脚本版本…")
        orig: List[str] = original_texts or []

        results: List[Tuple[ScriptVersion, ReviewReport]] = []
        for script in generated.scripts:
            script_ver, report = await self._review_one(script, orig)
            status = "✅ 通过" if report.final_approved else f"❌ {report.severity}"
            self.log(
                f"版本{script_ver.version} {status} | 相似度 {report.similarity_score:.1%}"
            )
            results.append((script_ver, report))

        approved_count = sum(1 for _, r in results if r.final_approved)
        self.log(f"审核完成，{approved_count}/{len(results)} 个版本通过")
        return results
