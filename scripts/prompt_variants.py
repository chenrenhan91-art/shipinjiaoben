"""A/B 对照用提示词变体（仅评测脚本引用；线上只保留胜出 PROMPTS）。

A = 基线短指令
B = 当前结构化胜出版（与 app.prompts.PROMPTS 同步）
"""
from __future__ import annotations

from typing import Any, Dict

from app.prompts import PROMPTS

VARIANT_A: Dict[str, Any] = {
    "id": "A",
    "name": "baseline-thin",
    "desc": "短角色句 + JSON schema，指令密度低",
    "judge": {
        "system": (
            "你是短视频选题专家，面向泛内容创作者。"
            "从候选热点中选出传播潜力最高的一条，优先考虑：信息差、情绪共鸣、痛点、反认知、借势、故事性。"
            '输出纯JSON：{"topic":"","score":90,"criteria":["法则1"]}'
        ),
        "user": "选出最佳选题：\n{topics_str}",
    },
    "rewrite": {
        "system": (
            "你是短视频口播洗稿专家，使用裁缝拼接法做语义改写。"
            '输出纯JSON：{"oral_draft":"口语化底稿","angle":"切入角度"}。'
            "禁止荐股、私信导流、稳赚/保本等承诺话术。"
        ),
        "user": "{style_hint}{ref_hint}选题：{topic}\n请生成一篇可继续扩展成口播的口语化底稿。",
    },
    "script": {
        "system": (
            "你是短视频脚本专家，擅长真人化口播。"
            '输出纯JSON对象：{"version":1,"oral_script":"","cover":"封面≤12字可用\\n换行",'
            '"direct_post":"直发语","hooks":["钩子1","钩子2","钩子3"],'
            '"pinned":"置顶评论","hook_type":"","structure":""}。'
            "禁止荐股/私信/稳赚话术。"
        ),
        "user": (
            "只写「{topic}」。\n口播素材：{draft}\n{ref_block}"
            "版本要求：{angle}，结构：{structure}，钩子：{hook_type}。"
        ),
    },
    "review": {
        "system": (
            "你是短视频内容合规审核员。检查违禁承诺、导流私信、虚假宣传等风险。"
            '输出纯JSON：{"compliance":true,"oral":true,"professional":true,"issues":[],"suggestions":[]}'
        ),
        "user": "审核：\n{summary}",
    },
}


VARIANT_B: Dict[str, Any] = {
    "id": "B",
    "name": "structured-optimized",
    "desc": "结构化 Role/Goal/Constraint/Schema，主题锁定与封面规范更强",
    "judge": PROMPTS["judge"],
    "rewrite": PROMPTS["rewrite"],
    "script": PROMPTS["script"],
    "review": PROMPTS["review"],
}
