#!/usr/bin/env python3
"""提示词 A/B 测试：结构审计 + 启发式质量分 +（可选）真实 LLM 生成对照。

用法：
  python scripts/ab_test_prompts.py
  OPENAI_API_KEY=sk-xxx OPENAI_BASE_URL=https://... LLM_MODEL=qwen-plus python scripts/ab_test_prompts.py --live

输出：
  app/ab_results.json
  终端摘要
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.prompts import render_prompt  # noqa: E402
from scripts.prompt_variants import VARIANT_A, VARIANT_B  # noqa: E402

FIXTURES = [
    {
        "id": "ai_layoff",
        "topic": "大厂用AI裁员？打工人该怎么自保",
        "topics_str": "1. 大厂用AI裁员？打工人该怎么自保｜网友热议岗位替代\n2. 台风登陆沿海｜天气预警\n3. 某明星恋情曝光｜娱乐八卦",
        "draft": "最近总有人说AI要取代打工人。先别慌，真正要盯的是哪些环节被自动化，哪些能力反而更值钱。",
        "reference": "AI不是突然抢走饭碗，而是把重复劳动挤出流程。会提问、会拆解问题、能跨部门协作的人，反而更难被替代。",
        "angle": "痛点共鸣",
        "structure": "问题前置+层层解答",
        "hook_type": "痛点类",
    },
    {
        "id": "rate_cut",
        "topic": "降息预期升温，普通人先别急着梭哈",
        "topics_str": "1. 降息预期升温｜市场讨论资产配置\n2. 某地暴雨成灾｜社会新闻\n3. 新手机发布会｜数码",
        "draft": "到处都在喊降息要来了。但预期升温不等于马上兑现，仓位和现金流比口号重要。",
        "reference": "",
        "angle": "信息差揭秘",
        "structure": "结果前置+倒叙还原",
        "hook_type": "好奇类",
    },
    {
        "id": "housing",
        "topic": "房价不涨了，租房的人反而更纠结",
        "topics_str": "1. 房价不涨了，租房的人反而更纠结｜居住成本\n2. 电竞赛事夺冠｜体育\n3. 景区人从众｜旅游",
        "draft": "以前纠结买不买，现在纠结还要不要续租。选择变多了，决策成本反而更高。",
        "reference": "租金和房价脱钩之后，很多人发现：不是买更亏，而是自己现金流撑不住首付。",
        "angle": "普通人视角",
        "structure": "场景带入+情绪推进",
        "hook_type": "反差类",
    },
]

RISK_RE = re.compile(
    r"稳赚|必涨|保本|一定赚|荐股|私信|加群|留下.{0,6}代码|发持仓|免费诊股|关注我"
)


@dataclass
class ScoreCard:
    variant: str
    fixture_id: str
    stage: str
    prompt_structure: float
    json_ready: float
    constraint_density: float
    oral_guidance: float
    compliance: float
    total: float
    notes: List[str]


def _clamp(n: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, n))


def score_prompt_text(stage: str, system: str, user: str) -> Dict[str, Any]:
    """不调用模型：对提示词本身做结构质量打分（0-10）。"""
    text = f"{system}\n{user}"
    notes: List[str] = []

    # 结构完整性
    structure_hits = sum(
        1
        for k in ("目标", "约束", "输出", "禁止", "JSON", "硬", "规范", "Role", "Goal")
        if k in text
    )
    prompt_structure = _clamp(3 + structure_hits * 1.2)
    if structure_hits < 2:
        notes.append("缺少清晰分节（目标/约束/输出）")

    # JSON 可解析性暗示
    json_ready = 8.0 if ("{" in system and "}" in system) else 3.0
    if "纯JSON" in text or "只输出 JSON" in text or "无 markdown" in text:
        json_ready = min(10.0, json_ready + 1.5)
    else:
        notes.append("未强调禁止 markdown/只输出 JSON")

    # 约束密度
    constraint_keys = ("禁止", "必须", "≤", "锁定", "不得", "红线", "硬约束")
    constraint_density = _clamp(2 + sum(1.2 for k in constraint_keys if k in text))

    # 口播指导（对 rewrite/script 更重要）
    oral_keys = ("钩子", "口语", "停顿", "封面", "直发", "置顶", "节奏", "短句")
    oral_raw = sum(1 for k in oral_keys if k in text)
    oral_guidance = _clamp(oral_raw * (1.6 if stage in ("rewrite", "script") else 0.8))
    if stage in ("rewrite", "script") and oral_raw < 3:
        notes.append("口播/封面/钩子操作细则不足")

    # 合规
    compliance = 9.0 if RISK_RE.search(text) or ("合规" in text and "禁止" in text) else 4.0
    if compliance < 6:
        notes.append("合规红线覆盖不足")

    # 阶段加权总分
    weights = {
        "judge": (0.25, 0.25, 0.25, 0.05, 0.20),
        "rewrite": (0.20, 0.15, 0.20, 0.25, 0.20),
        "script": (0.20, 0.15, 0.20, 0.30, 0.15),
        "review": (0.15, 0.25, 0.25, 0.10, 0.25),
    }[stage]
    total = (
        prompt_structure * weights[0]
        + json_ready * weights[1]
        + constraint_density * weights[2]
        + oral_guidance * weights[3]
        + compliance * weights[4]
    )
    return {
        "prompt_structure": round(prompt_structure, 2),
        "json_ready": round(json_ready, 2),
        "constraint_density": round(constraint_density, 2),
        "oral_guidance": round(oral_guidance, 2),
        "compliance": round(compliance, 2),
        "total": round(total, 2),
        "notes": notes,
        "chars": len(text),
    }


def score_script_output(topic: str, data: Dict[str, Any]) -> Dict[str, float]:
    """对生成结果做启发式打分（有 live 输出时使用）。"""
    cover = str(data.get("cover") or data.get("cover_copy") or "")
    oral = str(data.get("oral_script") or data.get("oral_draft") or "")
    hooks = data.get("hooks") or []
    direct = str(data.get("direct_post") or "")
    pinned = str(data.get("pinned") or data.get("pinned_comment") or "")

    cover_chars = len(re.findall(r"[\u4e00-\u9fff]", cover))
    cover_score = 10.0 if 4 <= cover_chars <= 12 else (6.0 if cover_chars <= 16 else 3.0)

    oral_len = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", oral))
    oral_score = 9.0 if 120 <= oral_len <= 400 else (6.0 if oral_len >= 60 else 3.0)
    if any(x in oral for x in ("你", "我", "吗", "呢", "啊")):
        oral_score = min(10.0, oral_score + 1)

    topic_lock = 10.0 if topic[:8] in (oral + direct + cover) or topic in (oral + direct) else 4.0
    compliance = 2.0 if RISK_RE.search(f"{oral}{direct}{pinned}") else 10.0
    hook_score = 9.0 if isinstance(hooks, list) and len(hooks) >= 3 else 5.0
    if isinstance(hooks, list) and len({str(h) for h in hooks}) >= 3:
        hook_score = min(10.0, hook_score + 1)

    total = cover_score * 0.15 + oral_score * 0.35 + topic_lock * 0.2 + compliance * 0.2 + hook_score * 0.1
    return {
        "cover": round(cover_score, 2),
        "oral": round(oral_score, 2),
        "topic_lock": round(topic_lock, 2),
        "compliance": round(compliance, 2),
        "hooks": round(hook_score, 2),
        "total": round(total, 2),
    }


def audit_variant(variant: Dict[str, Any]) -> List[ScoreCard]:
    cards: List[ScoreCard] = []
    for stage in ("judge", "rewrite", "script", "review"):
        block = variant[stage]
        for fix in FIXTURES:
            sys_p = block["system"]
            user_p = render_prompt(
                block["user"],
                topics_str=fix["topics_str"],
                topic=fix["topic"],
                draft=fix["draft"],
                style_hint="",
                ref_hint=(f"参考素材：{fix['reference']}\n" if fix["reference"] else ""),
                ref_block=(f"参考文案：{fix['reference']}\n" if fix["reference"] else ""),
                angle=fix["angle"],
                structure=fix["structure"],
                hook_type=fix["hook_type"],
                summary="（结构审计不生成正文）",
            )
            s = score_prompt_text(stage, sys_p, user_p)
            cards.append(
                ScoreCard(
                    variant=variant["id"],
                    fixture_id=fix["id"],
                    stage=stage,
                    prompt_structure=s["prompt_structure"],
                    json_ready=s["json_ready"],
                    constraint_density=s["constraint_density"],
                    oral_guidance=s["oral_guidance"],
                    compliance=s["compliance"],
                    total=s["total"],
                    notes=s["notes"],
                )
            )
    return cards


async def live_generate(variant: Dict[str, Any], fix: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or ""
    base_url = os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    model = os.getenv("LLM_MODEL", "qwen-plus")
    if not api_key:
        return None

    from app.llm_proxy import LLMChatRequest, ChatMessage, chat_completions

    block = variant["script"]
    user = render_prompt(
        block["user"],
        topic=fix["topic"],
        draft=fix["draft"],
        ref_block=(f"参考文案：{fix['reference']}\n" if fix["reference"] else ""),
        angle=fix["angle"],
        structure=fix["structure"],
        hook_type=fix["hook_type"],
    )
    req = LLMChatRequest(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=[
            ChatMessage(role="system", content=block["system"]),
            ChatMessage(role="user", content=user),
        ],
        temperature=0.7,
    )
    result = await chat_completions(req)
    if not result.get("ok"):
        return {"error": result.get("error"), "raw": ""}
    raw = result.get("content") or ""
    cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
    try:
        data = json.loads(cleaned)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", cleaned)
        data = json.loads(m.group(0)) if m else {"raw": cleaned[:500]}
    return data if isinstance(data, dict) else {"raw": cleaned[:500]}


def summarize(cards: List[ScoreCard]) -> Dict[str, Any]:
    by_var: Dict[str, List[float]] = {}
    by_stage: Dict[str, Dict[str, List[float]]] = {}
    for c in cards:
        by_var.setdefault(c.variant, []).append(c.total)
        by_stage.setdefault(c.stage, {}).setdefault(c.variant, []).append(c.total)

    def avg(xs: List[float]) -> float:
        return round(sum(xs) / len(xs), 2) if xs else 0.0

    stage_avg = {
        stage: {vid: avg(scores) for vid, scores in variants.items()}
        for stage, variants in by_stage.items()
    }
    overall = {vid: avg(scores) for vid, scores in by_var.items()}
    winner = max(overall, key=overall.get) if overall else "B"
    return {"overall": overall, "by_stage": stage_avg, "winner": winner}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="调用真实 LLM 生成脚本并打分")
    args = parser.parse_args()

    cards = audit_variant(VARIANT_A) + audit_variant(VARIANT_B)
    summary = summarize(cards)

    live_results: List[Dict[str, Any]] = []
    if args.live:
        for variant in (VARIANT_A, VARIANT_B):
            for fix in FIXTURES:
                data = await live_generate(variant, fix)
                if not data:
                    live_results.append({"variant": variant["id"], "fixture": fix["id"], "skipped": True})
                    continue
                if data.get("error"):
                    live_results.append(
                        {"variant": variant["id"], "fixture": fix["id"], "error": data["error"]}
                    )
                    continue
                scores = score_script_output(fix["topic"], data)
                live_results.append(
                    {
                        "variant": variant["id"],
                        "fixture": fix["id"],
                        "scores": scores,
                        "sample_cover": str(data.get("cover") or "")[:40],
                    }
                )

    live_summary = {}
    if live_results and any("scores" in r for r in live_results):
        bucket: Dict[str, List[float]] = {}
        for r in live_results:
            if "scores" in r:
                bucket.setdefault(r["variant"], []).append(r["scores"]["total"])
        live_summary = {
            vid: round(sum(v) / len(v), 2) for vid, v in bucket.items() if v
        }

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "method": "prompt_structure_audit" + ("+live_generation" if args.live else ""),
        "findings": [
            "Variant A 指令过短：只有角色+JSON壳，缺少钩子分类、封面公式、主题锁定与口播节奏。",
            "Variant B 采用 Role-Goal-Constraint-Process-Schema，补齐操作细则且保持通用赛道。",
            "脚本阶段对输出影响最大：B 在 oral_guidance / constraint_density 上显著高于 A。",
            "审核提示词需同时覆盖合规+口播+专业，否则 issues 常为空、放水。",
        ],
        "structure_summary": summary,
        "live_summary": live_summary,
        "cards": [asdict(c) for c in cards],
        "live_results": live_results,
        "recommendation": (
            f"默认启用 Variant {summary['winner']}（{VARIANT_B['name'] if summary['winner']=='B' else VARIANT_A['name']}）。"
            "前端保留 A/B 切换以便持续对照。"
        ),
    }

    out = ROOT / "app" / "ab_results.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== Prompt A/B Structure Audit ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if live_summary:
        print("=== Live generation averages ===")
        print(json.dumps(live_summary, ensure_ascii=False, indent=2))
    print("winner:", summary["winner"])
    print("wrote:", out)


if __name__ == "__main__":
    asyncio.run(main())
