from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum


class HotTopic(BaseModel):
    title: str
    source: str
    url: str = ""
    published_at: datetime = Field(default_factory=datetime.now)
    summary: str = ""
    tags: List[str] = Field(default_factory=list)
    heat_score: float = 0.0


class ViralVideo(BaseModel):
    """爆款视频信息"""
    platform: str          # douyin / xiaohongshu / shipinhao
    title: str
    script: str = ""       # 逐字稿
    likes: int = 0
    duration_seconds: int = 0
    comments_hot: List[str] = Field(default_factory=list)
    url: str = ""

    @property
    def duration_category(self) -> str:
        """short=<60s（取开头钩子），long=>180s（取内容段）"""
        if self.duration_seconds < 60:
            return "short"
        if self.duration_seconds > 180:
            return "long"
        return "mid"


class HookType(str, Enum):
    CURIOSITY = "好奇类"
    EXTREME = "极限词类"
    TRENDING = "借势类"
    PAIN_POINT = "痛点类"
    FEAR = "恐吓类"
    CONTRAST = "反差类"
    BENEFIT = "利益输送类"


class ScriptStructure(str, Enum):
    HOOK_FIRST = "钩子前置+顺叙展开"
    PROBLEM_FIRST = "问题前置+层层解答"
    RESULT_FIRST = "结果前置+倒叙还原"
    OPINION_FIRST = "观点前置+论据支撑"
    SCENE_FIRST = "场景带入+情绪推进"


class OralScript(BaseModel):
    hook_variant: int
    content: str


class ScriptVersion(BaseModel):
    version: int
    cover_copy: str           # 封面文案（≤12字）
    direct_post: str          # 直发语
    oral_scripts: List[OralScript]   # 多版本口播（含多钩子变体）
    pinned_comment: str       # 置顶评论
    hook_type: str
    structure_type: str


class GeneratedScripts(BaseModel):
    topic: str
    scripts: List[ScriptVersion]
    source_video_urls: List[str] = Field(default_factory=list)


class TopicReport(BaseModel):
    topic: str
    potential_score: float    # 0–100
    viral_basis: str
    matched_criteria: List[str]
    key_hooks: List[str]
    recommended_structure: str


class ViralGene(BaseModel):
    """爆款解构骨架（无原文）"""
    hook_type: str
    structure_type: str
    opening_hook_template: str    # 开头钩子逻辑模板（非原文）
    core_logic: str
    emotion_points: List[str]
    interaction_points: List[str]
    key_phrase_pattern: str
    rhythm_design: str
    duration_category: str        # short / mid / long
    suitable_for: str             # opening / content


class ReviewReport(BaseModel):
    compliance_passed: bool
    oral_passed: bool
    professional_passed: bool
    issues: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    severity: str = "pass"        # pass / minor / major
    final_approved: bool
    similarity_score: float = 0.0
