#!/usr/bin/env python3
"""用真实热点做 5 组提示词 A/B 对照，专业评分后产出胜者。

环境变量：
  OPENAI_API_KEY / DASHSCOPE_API_KEY
  OPENAI_BASE_URL (默认百炼兼容地址)
  LLM_MODEL (默认 qwen-plus)

用法：
  OPENAI_API_KEY=sk-xxx python scripts/ab_live_real.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.llm_proxy import ChatMessage, LLMChatRequest, chat_completions  # noqa: E402
from app.prompts import render_prompt  # noqa: E402
from scripts.prompt_variants import VARIANT_A, VARIANT_B  # noqa: E402

RISK_RE = re.compile(
    r"稳赚|必涨|保本|一定赚|荐股|私信|加群|留下.{0,8}代码|发持仓|免费诊股|关注我|无风险|稳赚不赔"
)
SPOKEN_MARKERS = ("你", "我", "吗", "呢", "啊", "吧", "其实", "说白了", "先", "别")


def env_cfg() -> Tuple[str, str, str]:
    key = os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or ""
    base = os.getenv(
        "OPENAI_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    model = os.getenv("LLM_MODEL", "qwen-plus")
    if not key:
        raise SystemExit("缺少 OPENAI_API_KEY / DASHSCOPE_API_KEY")
    return key, base, model


async def fetch_real_topics(limit: int = 40) -> List[Dict[str, Any]]:
    url = "http://127.0.0.1:8765/api/hot/topics?limit=80"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
    return data.get("topics") or []


def _topic_fingerprint(title: str) -> str:
    """归一化标题指纹，避免同一事件多平台重复进组。"""
    s = re.sub(r"[“”\"'‘’\s\-_|｜·、，,。！？!?:：]", "", title or "")
    # 取核心词：去掉常见后缀词后取前 10 字
    s = re.sub(r"(回应|事件|争议|最新|消息)$", "", s)
    return s[:10]


def build_fixtures(topics: List[Dict[str, Any]], n: int = 5) -> List[Dict[str, Any]]:
    """从真实热点挑 5 组：跨平台、事件去重、适合口播的标题。"""
    weak = re.compile(r"抽奖|优惠券|直播预告|OOTD|含金量|申请出战|美食展")
    scored = []
    for t in topics:
        title = str(t.get("title") or "").strip()
        if len(title) < 8 or weak.search(title):
            continue
        heat = float(t.get("heat_score") or 0)
        source = str(t.get("source") or "")
        bonus = 0.0
        # 跨平台加权，避免全是同一热榜
        if any(s in source for s in ("微博", "百度", "头条", "腾讯", "第一财经", "东方财富", "36氪", "FT")):
            bonus += 3
        if any(k in title for k in ("立案", "禁止", "回应", "降息", "AI", "数据", "台风", "经济", "谈判", "裁员", "房价", "投资", "制裁")):
            bonus += 5
        if t.get("summary"):
            bonus += 1
        scored.append((bonus * 1e12 + heat, t))
    scored.sort(key=lambda x: x[0], reverse=True)

    picked = []
    seen_fp = set()
    seen_source = {}
    for _, t in scored:
        title = str(t.get("title") or "")
        fp = _topic_fingerprint(title)
        if not fp or fp in seen_fp:
            continue
        # 与已选标题的字符重叠过高也跳过（同一事件变体）
        if any(len(set(fp) & set(old)) >= 6 for old in seen_fp):
            continue
        src = str(t.get("source") or "未知").split("/")[0]
        # 同一来源最多 2 条，保证多样性
        if seen_source.get(src, 0) >= 2:
            continue
        seen_fp.add(fp)
        seen_source[src] = seen_source.get(src, 0) + 1
        picked.append(t)
        if len(picked) >= n:
            break

    # 不足时放宽来源限制补齐（仍保持事件指纹去重）
    if len(picked) < n:
        for _, t in scored:
            title = str(t.get("title") or "")
            fp = _topic_fingerprint(title)
            if not fp or fp in seen_fp:
                continue
            if any(len(set(fp) & set(old)) >= 6 for old in seen_fp):
                continue
            seen_fp.add(fp)
            picked.append(t)
            if len(picked) >= n:
                break

    angles = ["痛点共鸣", "信息差揭秘", "普通人视角", "反差对比", "权威解读"]
    structs = [
        "问题前置+层层解答",
        "结果前置+倒叙还原",
        "场景带入+情绪推进",
        "观点前置+论据支撑",
        "钩子前置+顺叙展开",
    ]
    hooks = ["痛点类", "好奇类", "反差类", "借势类", "利益输送类"]

    fixtures = []
    for i, t in enumerate(picked):
        title = t["title"]
        summary = str(t.get("summary") or "")
        # 同组候选：当前题 + 另外 2 条干扰项
        distractors = [x for x in topics if x.get("title") != title][i : i + 2]
        lines = [f"1. {title}" + (f"｜{summary[:40]}" if summary else "")]
        for j, d in enumerate(distractors, start=2):
            lines.append(f"{j}. {d.get('title')}" + (f"｜{str(d.get('summary') or '')[:40]}"))
        fixtures.append(
            {
                "id": f"real_{i+1}",
                "topic": title,
                "source": t.get("source"),
                "url": t.get("url"),
                "topics_str": "\n".join(lines),
                "draft": (
                    f"今天聊「{title}」。先把普通人真正关心的点讲清楚："
                    f"{summary[:80] if summary else '这件事为什么突然冲上热搜，以及它跟你有什么关系。'}"
                ),
                "reference": summary[:400],
                "angle": angles[i % len(angles)],
                "structure": structs[i % len(structs)],
                "hook_type": hooks[i % len(hooks)],
            }
        )
    return fixtures


def parse_json_content(raw: str) -> Dict[str, Any]:
    cleaned = re.sub(r"```(?:json)?", "", raw or "").replace("```", "").strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {"_raw": cleaned[:800]}
    except Exception:
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if not m:
            return {"_raw": cleaned[:800], "_parse_error": True}
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else {"_raw": cleaned[:800]}
        except Exception:
            return {"_raw": cleaned[:800], "_parse_error": True}


async def call_stage(
    api_key: str,
    base_url: str,
    model: str,
    system: str,
    user: str,
) -> Dict[str, Any]:
    req = LLMChatRequest(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.7,
        messages=[
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=user),
        ],
        fallback_models=[],
    )
    result = await chat_completions(req)
    if not result.get("ok"):
        return {"_error": result.get("error") or "upstream failed"}
    data = parse_json_content(result.get("content") or "")
    data["_model"] = result.get("model")
    return data


def _zh_len(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text or ""))


def score_rewrite(topic: str, data: Dict[str, Any]) -> Dict[str, float]:
    if data.get("_error") or data.get("_parse_error"):
        return {"json": 1, "topic_lock": 1, "oral": 1, "compliance": 1, "total": 1.0}
    draft = str(data.get("oral_draft") or data.get("draft") or "")
    json_s = 10.0 if draft else 3.0
    topic_lock = 10.0 if (topic[:6] in draft or any(w in draft for w in re.findall(r"[\u4e00-\u9fff]{2,}", topic)[:3])) else 4.0
    n = _zh_len(draft)
    oral = 9.5 if 150 <= n <= 360 else (7.0 if 80 <= n <= 450 else 4.0)
    if sum(1 for m in SPOKEN_MARKERS if m in draft) >= 3:
        oral = min(10.0, oral + 1)
    compliance = 2.0 if RISK_RE.search(draft) else 10.0
    total = json_s * 0.15 + topic_lock * 0.25 + oral * 0.4 + compliance * 0.2
    return {
        "json": round(json_s, 2),
        "topic_lock": round(topic_lock, 2),
        "oral": round(oral, 2),
        "compliance": round(compliance, 2),
        "total": round(total, 2),
    }


def score_script(topic: str, data: Dict[str, Any]) -> Dict[str, float]:
    if data.get("_error") or data.get("_parse_error"):
        return {
            "json": 1, "cover": 1, "oral": 1, "hooks": 1,
            "topic_lock": 1, "compliance": 1, "direct": 1, "pinned": 1, "total": 1.0,
        }
    cover = str(data.get("cover") or data.get("cover_copy") or "")
    oral = str(data.get("oral_script") or "")
    direct = str(data.get("direct_post") or "")
    pinned = str(data.get("pinned") or data.get("pinned_comment") or "")
    hooks = data.get("hooks") or []

    fields = [cover, oral, direct, pinned, hooks]
    json_s = 10.0 if all([cover, oral, direct, pinned, isinstance(hooks, list) and hooks]) else 5.0

    cover_n = len(re.findall(r"[\u4e00-\u9fff]", cover))
    cover_s = 10.0 if 6 <= cover_n <= 12 else (6.5 if cover_n <= 16 else 3.0)

    oral_n = _zh_len(oral)
    oral_s = 9.5 if 140 <= oral_n <= 420 else (6.5 if oral_n >= 80 else 3.5)
    if sum(1 for m in SPOKEN_MARKERS if m in oral) >= 4:
        oral_s = min(10.0, oral_s + 0.8)
    # 开头钩子感：前 30 字含疑问/反差
    head = oral[:40]
    if any(x in head for x in ("？", "吗", "为什么", "别", "先", "其实")):
        oral_s = min(10.0, oral_s + 0.5)

    if isinstance(hooks, list) and len(hooks) >= 3:
        uniq = len({str(h).strip() for h in hooks if str(h).strip()})
        hooks_s = 9.0 if uniq >= 3 else 6.0
        avg_h = sum(len(str(h)) for h in hooks[:3]) / 3
        if avg_h <= 30:
            hooks_s = min(10.0, hooks_s + 0.5)
    else:
        hooks_s = 3.0

    blob = cover + oral + direct
    topic_tokens = re.findall(r"[\u4e00-\u9fff]{2,}", topic)
    hits = sum(1 for w in topic_tokens[:5] if w in blob)
    topic_lock = 10.0 if hits >= 2 or topic[:8] in blob else (6.0 if hits >= 1 else 3.0)

    risk_blob = f"{cover}\n{oral}\n{direct}\n{pinned}\n" + "\n".join(map(str, hooks if isinstance(hooks, list) else []))
    compliance = 2.0 if RISK_RE.search(risk_blob) else 10.0

    direct_s = 9.0 if 30 <= _zh_len(direct) <= 120 else 5.5
    pinned_s = 9.0 if ("？" in pinned or "?" in pinned) and _zh_len(pinned) >= 8 else 5.0
    if RISK_RE.search(pinned or ""):
        pinned_s = 2.0

    total = (
        json_s * 0.10
        + cover_s * 0.12
        + oral_s * 0.28
        + hooks_s * 0.12
        + topic_lock * 0.15
        + compliance * 0.13
        + direct_s * 0.05
        + pinned_s * 0.05
    )
    return {
        "json": round(json_s, 2),
        "cover": round(cover_s, 2),
        "oral": round(oral_s, 2),
        "hooks": round(hooks_s, 2),
        "topic_lock": round(topic_lock, 2),
        "compliance": round(compliance, 2),
        "direct": round(direct_s, 2),
        "pinned": round(pinned_s, 2),
        "total": round(total, 2),
    }


async def run_pair(
    api_key: str,
    base_url: str,
    model: str,
    variant: Dict[str, Any],
    fix: Dict[str, Any],
) -> Dict[str, Any]:
    # rewrite
    rw_user = render_prompt(
        variant["rewrite"]["user"],
        style_hint="",
        ref_hint=(f"参考素材（需语义改写，禁止照抄）：\n{fix['reference']}\n" if fix.get("reference") else ""),
        topic=fix["topic"],
    )
    rewrite = await call_stage(api_key, base_url, model, variant["rewrite"]["system"], rw_user)
    await asyncio.sleep(0.4)

    draft = str(rewrite.get("oral_draft") or rewrite.get("draft") or fix["draft"])
    sc_user = render_prompt(
        variant["script"]["user"],
        topic=fix["topic"],
        draft=draft,
        ref_block=(f"参考文案：{fix['reference']}\n" if fix.get("reference") else ""),
        angle=fix["angle"],
        structure=fix["structure"],
        hook_type=fix["hook_type"],
    )
    script = await call_stage(api_key, base_url, model, variant["script"]["system"], sc_user)

    rw_score = score_rewrite(fix["topic"], rewrite)
    sc_score = score_script(fix["topic"], script)
    # 脚本权重更高
    pair_total = round(rw_score["total"] * 0.35 + sc_score["total"] * 0.65, 2)
    return {
        "variant": variant["id"],
        "fixture_id": fix["id"],
        "topic": fix["topic"],
        "source": fix.get("source"),
        "rewrite_score": rw_score,
        "script_score": sc_score,
        "pair_total": pair_total,
        "sample": {
            "cover": str(script.get("cover") or "")[:40],
            "oral_head": str(script.get("oral_script") or "")[:80],
            "hooks": (script.get("hooks") or [])[:3],
        },
        "errors": {
            "rewrite": rewrite.get("_error"),
            "script": script.get("_error"),
            "parse_rewrite": rewrite.get("_parse_error"),
            "parse_script": script.get("_parse_error"),
        },
    }


async def main() -> None:
    api_key, base_url, model = env_cfg()
    print(f"[ab] model={model} base={base_url}")
    topics = await fetch_real_topics()
    print(f"[ab] fetched hot topics: {len(topics)}")
    fixtures = build_fixtures(topics, n=5)
    if len(fixtures) < 5:
        raise SystemExit(f"真实热点不足 5 条，仅 {len(fixtures)}")
    for f in fixtures:
        print(f"  - {f['id']}: [{f.get('source')}] {f['topic'][:36]}")

    results: List[Dict[str, Any]] = []
    for fix in fixtures:
        print(f"\n[ab] group {fix['id']} ...")
        for variant in (VARIANT_A, VARIANT_B):
            print(f"  running variant {variant['id']} ...")
            row = await run_pair(api_key, base_url, model, variant, fix)
            results.append(row)
            print(f"  {variant['id']} total={row['pair_total']} script={row['script_score']['total']} rewrite={row['rewrite_score']['total']}")
            await asyncio.sleep(0.6)

    # aggregate
    by_var: Dict[str, List[float]] = {"A": [], "B": []}
    by_dim: Dict[str, Dict[str, List[float]]] = {
        "A": {"oral": [], "topic_lock": [], "compliance": [], "cover": [], "hooks": []},
        "B": {"oral": [], "topic_lock": [], "compliance": [], "cover": [], "hooks": []},
    }
    pairwise = []
    for fix in fixtures:
        a = next(r for r in results if r["fixture_id"] == fix["id"] and r["variant"] == "A")
        b = next(r for r in results if r["fixture_id"] == fix["id"] and r["variant"] == "B")
        by_var["A"].append(a["pair_total"])
        by_var["B"].append(b["pair_total"])
        for dim in by_dim["A"]:
            by_dim["A"][dim].append(a["script_score"].get(dim, 0))
            by_dim["B"][dim].append(b["script_score"].get(dim, 0))
        pairwise.append(
            {
                "fixture_id": fix["id"],
                "topic": fix["topic"],
                "A": a["pair_total"],
                "B": b["pair_total"],
                "winner": "B" if b["pair_total"] >= a["pair_total"] else "A",
                "margin": round(abs(b["pair_total"] - a["pair_total"]), 2),
            }
        )

    def avg(xs: List[float]) -> float:
        return round(sum(xs) / len(xs), 2) if xs else 0.0

    overall = {k: avg(v) for k, v in by_var.items()}
    dim_avg = {vid: {d: avg(vs) for d, vs in dims.items()} for vid, dims in by_dim.items()}
    wins = {"A": sum(1 for p in pairwise if p["winner"] == "A"), "B": sum(1 for p in pairwise if p["winner"] == "B")}
    # 平局算 B 若分数相等已在上面归 B；再按均分决胜
    winner = "B" if (overall["B"], wins["B"]) >= (overall["A"], wins["A"]) else "A"

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "method": "live_real_hot_topics_5_groups",
        "model": model,
        "base_url": base_url,
        "fixtures": [{"id": f["id"], "topic": f["topic"], "source": f.get("source")} for f in fixtures],
        "pairwise": pairwise,
        "overall": overall,
        "dimension_avg": dim_avg,
        "wins": wins,
        "winner": winner,
        "recommendation": f"固化 Variant {winner} 为唯一提示词，移除前端选择。",
        "results": results,
    }
    out = ROOT / "app" / "ab_results.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== LIVE A/B SUMMARY ===")
    print(json.dumps({"overall": overall, "wins": wins, "winner": winner, "pairwise": pairwise, "dimension_avg": dim_avg}, ensure_ascii=False, indent=2))
    print("wrote", out)


if __name__ == "__main__":
    asyncio.run(main())
