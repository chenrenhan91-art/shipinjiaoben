import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # LLM
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_base_url: str = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o"))

    # 推送
    feishu_webhook: str = field(default_factory=lambda: os.getenv("FEISHU_WEBHOOK", ""))
    weixin_webhook: str = field(default_factory=lambda: os.getenv("WEIXIN_WEBHOOK", ""))

    # 模式
    mode: int = field(default_factory=lambda: int(os.getenv("AGENT_MODE", "1")))

    # 达人信息（模式2）
    influencer_name: str = field(default_factory=lambda: os.getenv("INFLUENCER_NAME", ""))
    influencer_style: str = field(default_factory=lambda: os.getenv("INFLUENCER_STYLE", ""))
    influencer_domain: str = field(default_factory=lambda: os.getenv("INFLUENCER_DOMAIN", "财经"))

    # 爆款判定阈值
    douyin_like_threshold: int = field(default_factory=lambda: int(os.getenv("DOUYIN_LIKE_THRESHOLD", "100000")))
    xiaohongshu_like_threshold: int = field(default_factory=lambda: int(os.getenv("XIAOHONGSHU_LIKE_THRESHOLD", "10000")))
    shipinhao_like_threshold: int = field(default_factory=lambda: int(os.getenv("SHIPINHAO_LIKE_THRESHOLD", "50000")))
    similarity_max: float = 0.20

    # GitHub 抓取工具桥接服务
    douk_api_base: str = field(default_factory=lambda: os.getenv("DOUK_API_BASE", "http://127.0.0.1:5555"))
    douk_api_token: str = field(default_factory=lambda: os.getenv("DOUK_API_TOKEN", ""))
    xhs_api_base: str = field(default_factory=lambda: os.getenv("XHS_API_BASE", "http://127.0.0.1:5556"))
    local_api_port: int = field(default_factory=lambda: int(os.getenv("LOCAL_API_PORT", "8765")))

    # 输出
    scripts_per_topic: int = field(default_factory=lambda: int(os.getenv("SCRIPTS_PER_TOPIC", "5")))
    hooks_per_script: int = field(default_factory=lambda: int(os.getenv("HOOKS_PER_SCRIPT", "3")))

    # 定时推送时间
    schedule_times: List[str] = field(default_factory=lambda: ["08:00", "12:00", "18:00"])


config = Config()
