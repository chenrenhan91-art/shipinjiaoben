"""
主入口 + 调度器

用法：
  python main.py                    # 立即运行一次（模式由 .env 决定）
  python main.py --mode 1           # 热点驱动模式
  python main.py --mode 2           # 达人适配模式
  python main.py --schedule         # 定时模式（每日 08:00 / 12:00 / 18:00）
  python main.py --topic "中美关税"  # 指定选题（跳过热点抓取）
  python main.py --viral viral.json # 指定爆款视频文件
"""
import asyncio
import argparse
import json
import schedule
import time
import sys
import os
from datetime import datetime
from typing import Optional, List

from config import config
from data_models import TopicReport, ViralVideo
from agents.hot_topic_agent import HotTopicAgent
from agents.topic_judge_agent import TopicJudgeAgent
from agents.content_agent import ContentAgent
from agents.script_agent import ScriptAgent
from agents.review_agent import ReviewAgent
from agents.push_agent import PushAgent
from utils.crawler import load_viral_videos_from_file
from utils.llm import chat_json
from prompts.system_prompts import INFLUENCER_ADAPT_SYSTEM, INFLUENCER_ADAPT_USER


# ──────────────────────────────────────────────
# 默认示例爆款视频（无爆款文件时使用）
# ──────────────────────────────────────────────
DEMO_VIRAL_VIDEOS = [
    ViralVideo(
        platform="douyin",
        title="为什么散户总是亏钱",
        script="散户为什么总是亏钱？我给你讲三个原因……",
        likes=120000,
        duration_seconds=45,
        comments_hot=["说到心坎上了", "扎心了老铁", "学到了"],
    ),
    ViralVideo(
        platform="douyin",
        title="普通人如何用基金实现财务自由",
        script="想通过基金实现财务自由？先弄清楚这三件事……",
        likes=85000,
        duration_seconds=240,
        comments_hot=["干货满满", "收藏了", "涨知识"],
    ),
]


async def run_mode1(
    viral_videos: List[ViralVideo],
    manual_topic: Optional[str] = None,
) -> List[dict]:
    """模式1：热点驱动全流程"""
    print(f"\n{'='*60}")
    print(f"  模式1：热点驱动 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # Step 1：热点抓取
    topic_reports: list[TopicReport] = []
    if manual_topic:
        # 直接用指定选题，跳过抓取
        topic_reports = [TopicReport(
            topic=manual_topic,
            potential_score=90.0,
            viral_basis="手动指定选题",
            matched_criteria=["信息差/揭秘", "情绪共鸣点", "常见痛点", "权威解读"],
            key_hooks=["这件事你不知道", "99%的人都搞错了"],
            recommended_structure="问题前置+层层解答",
        )]
    else:
        hot_agent = HotTopicAgent()
        hot_topics = await hot_agent.run()
        if not hot_topics:
            print("[main] 热点抓取为空，请检查网络")
            return []

        judge_agent = TopicJudgeAgent()
        topic_reports = await judge_agent.run(hot_topics)
        if not topic_reports:
            print("[main] 未筛选到合适选题")
            return []

    # Step 2：对每个 Top 选题生成脚本（最多处理 3 个）
    content_agent = ContentAgent()
    script_agent = ScriptAgent()
    review_agent = ReviewAgent()
    push_agent = PushAgent()

    push_results: List[dict] = []
    original_texts: List[str] = [v.script for v in viral_videos if v.script]

    for report in topic_reports[:3]:
        print(f"\n▶ 处理选题：{report.topic}（潜力分 {report.potential_score:.0f}）")

        # Step 3：内容解构 + 洗稿
        oral_draft = await content_agent.run(report.topic, viral_videos, report)
        if not oral_draft:
            print(f"  [跳过] 洗稿失败：{report.topic}")
            continue

        # Step 4：脚本生成
        generated = await script_agent.run(report.topic, oral_draft, report)
        if not generated.scripts:
            print(f"  [跳过] 脚本生成失败：{report.topic}")
            continue

        # Step 5：三重审核
        review_results = await review_agent.run(generated, original_texts)

        # Step 6：推送
        push_result = await push_agent.run(report, review_results)
        push_results.append({
            "topic": report.topic,
            "scripts_count": len(review_results),
            **push_result,
        })
        print(f"  ✅ 完成 | 本地文件：{push_result['local_file']}")

    return push_results


async def run_mode2(
    viral_videos: List[ViralVideo],
    manual_topic: Optional[str] = None,
) -> List[dict]:
    """模式2：达人适配全流程"""
    print(f"\n{'='*60}")
    print(f"  模式2：达人适配 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  达人：{config.influencer_name or '（未设置）'}")
    print(f"{'='*60}\n")

    if not config.influencer_name or not config.influencer_style:
        print("[main] 模式2 需要在 .env 中配置 INFLUENCER_NAME 和 INFLUENCER_STYLE")
        return []

    # Step 1：选题
    topic_reports: list[TopicReport] = []
    if manual_topic:
        topic_reports = [TopicReport(
            topic=manual_topic,
            potential_score=90.0,
            viral_basis="手动指定",
            matched_criteria=["信息差/揭秘", "痛点", "情绪共鸣点", "反认知观点"],
            key_hooks=[],
            recommended_structure="观点前置+论据支撑",
        )]
    else:
        hot_agent = HotTopicAgent()
        hot_topics = await hot_agent.run()
        judge_agent = TopicJudgeAgent()
        topic_reports = await judge_agent.run(hot_topics)

    content_agent = ContentAgent()
    script_agent = ScriptAgent()
    review_agent = ReviewAgent()
    push_agent = PushAgent()

    push_results: List[dict] = []
    original_texts: List[str] = [v.script for v in viral_videos if v.script]

    for report in topic_reports[:3]:
        print(f"\n▶ 处理选题（达人适配）：{report.topic}")

        # 解构爆款基因
        genes = await content_agent.deconstruct_videos(viral_videos)
        if not genes:
            continue

        opening_gene = next((g for g in genes if g.suitable_for == "opening"), genes[0])
        content_gene = next((g for g in genes if g.suitable_for == "content"), genes[-1])

        # 达人适配改写
        user_msg = INFLUENCER_ADAPT_USER.format(
            influencer_name=config.influencer_name,
            influencer_style=config.influencer_style,
            influencer_domain=config.influencer_domain,
            opening_template=opening_gene.opening_hook_template,
            core_logic=content_gene.core_logic,
            emotion_points=", ".join(content_gene.emotion_points),
            rhythm_design=content_gene.rhythm_design,
            topic=report.topic,
        )
        data = await chat_json(INFLUENCER_ADAPT_SYSTEM, user_msg)
        oral_draft = data.get("adapted_draft", "")
        if not oral_draft:
            print(f"  [跳过] 达人适配失败：{report.topic}")
            continue

        generated = await script_agent.run(report.topic, oral_draft, report)
        if not generated.scripts:
            continue

        review_results = await review_agent.run(generated, original_texts)
        push_result = await push_agent.run(report, review_results)
        push_results.append({"topic": report.topic, **push_result})
        print(f"  ✅ 完成 | {push_result['local_file']}")

    return push_results


async def main(
    mode: Optional[int] = None,
    viral_file: Optional[str] = None,
    manual_topic: Optional[str] = None,
):
    run_mode = mode or config.mode

    # 加载爆款视频
    viral_videos: List[ViralVideo]
    if viral_file and os.path.exists(viral_file):
        viral_videos = load_viral_videos_from_file(viral_file)
        print(f"[main] 加载爆款视频 {len(viral_videos)} 条 from {viral_file}")
    else:
        viral_videos = DEMO_VIRAL_VIDEOS
        print(f"[main] 使用内置示例爆款视频（如需使用真实数据，请提供 --viral viral.json）")

    if run_mode == 1:
        results = await run_mode1(viral_videos, manual_topic)
    else:
        results = await run_mode2(viral_videos, manual_topic)

    print(f"\n[main] 本次运行完成，共处理 {len(results)} 个选题")
    for r in results:
        print(f"  • {r['topic'][:30]} → {r.get('local_file', '')}")
    return results


def scheduled_job(viral_file: Optional[str]):
    print(f"[scheduler] 触发定时任务 {datetime.now().strftime('%H:%M')}")
    asyncio.run(main(viral_file=viral_file))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="短视频爆款脚本生产 AI Agent")
    parser.add_argument("--mode", type=int, choices=[1, 2], help="运行模式：1=热点驱动，2=达人适配")
    parser.add_argument("--schedule", action="store_true", help="启用定时模式")
    parser.add_argument("--viral", type=str, help="爆款视频 JSON 文件路径")
    parser.add_argument("--topic", type=str, help="手动指定选题（跳过热点抓取）")
    args = parser.parse_args()

    if not config.openai_api_key:
        print("[错误] 请先配置 OPENAI_API_KEY（复制 .env.example 为 .env 并填入密钥）")
        sys.exit(1)

    if args.schedule:
        print(f"[scheduler] 定时模式启动，推送时间：{config.schedule_times}")
        for t in config.schedule_times:
            schedule.every().day.at(t).do(scheduled_job, viral_file=args.viral)
        while True:
            schedule.run_pending()
            time.sleep(30)
    else:
        asyncio.run(main(mode=args.mode, viral_file=args.viral, manual_topic=args.topic))
