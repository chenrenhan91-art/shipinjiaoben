"""
文本工具：
1. 中文字符 n-gram 相似度（不依赖 jieba，直接字符级）
2. 简单文本清洗
"""
import re
from collections import Counter


def _char_ngrams(text: str, n: int = 3) -> Counter:
    """生成字符 n-gram Counter"""
    clean = re.sub(r"\s+", "", text)
    return Counter(clean[i:i+n] for i in range(len(clean) - n + 1))


def similarity(text_a: str, text_b: str, n: int = 3) -> float:
    """
    基于字符 n-gram Jaccard 相似度。
    返回 0.0（完全不同）~ 1.0（完全相同）。
    """
    if not text_a or not text_b:
        return 0.0
    a = _char_ngrams(text_a, n)
    b = _char_ngrams(text_b, n)
    intersection = sum((a & b).values())
    union = sum((a | b).values())
    return intersection / union if union else 0.0


def clean_text(text: str) -> str:
    """去除多余空白、HTML标签"""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def count_chars(text: str) -> int:
    """统计中文字符数（不含标点和空格）"""
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def count_oral_chars(text: str) -> int:
    """统计口播有效字数：中文、英文和数字，不含空白、标点、链接符号。"""
    text = re.sub(r"https?://\S+", "", text or "")
    return len(re.findall(r"[\u3400-\u9fffA-Za-z0-9]", text))


def oral_length_profile(source_text: str, fallback: int = 240) -> dict:
    """根据源文案长度计算新口播稿目标范围。"""
    source_chars = count_oral_chars(source_text)
    has_reference = source_chars >= 30
    target = source_chars if has_reference else fallback
    lower_ratio = 0.85 if target < 80 else 0.9
    upper_ratio = 1.25 if target < 80 else 1.15
    min_chars = max(20, round(target * lower_ratio))
    max_chars = max(min_chars + 10, round(target * upper_ratio))
    return {
        "source_chars": source_chars,
        "has_reference": has_reference,
        "target": target,
        "min_chars": min_chars,
        "max_chars": max_chars,
    }


def oral_length_instruction(profile: dict) -> str:
    """生成给 LLM 的口播长度约束。"""
    if not profile.get("has_reference"):
        return "未提供足够长的原视频文案时，口播稿保持自然完整即可，避免所有版本机械写成同一长度。"
    return (
        f"原视频文案有效长度约{profile['source_chars']}字；"
        f"新口播稿必须控制在{profile['min_chars']}-{profile['max_chars']}字之间，"
        "整体长度要接近原文案，不能统一写成固定字数。"
    )


DOUYIN_RISK_PATTERNS = [
    re.compile(r"(?:评论区|评论|留言|私信|留下|留|发|打出|扣[一1])[^。！？!?；;\n]{0,28}(?:股票代码|基金代码|代码|持仓|个股|票)[^。！？!?；;\n]{0,42}", re.I),
    re.compile(r"(?:股票代码|基金代码|代码|持仓|个股|票)[^。！？!?；;\n]{0,28}(?:发我|告诉我|留给我|留下来|放评论区|打在评论区)", re.I),
    re.compile(r"(?:我|老师|博主|这边)[^。！？!?；;\n]{0,16}(?:帮你|给你|替你|免费)[^。！？!?；;\n]{0,28}(?:分析|查看|诊断|看看|解读|判断|估值|把关)", re.I),
    re.compile(r"(?:免费诊股|诊股|荐股|带单|跟单|内幕消息|进群|加群|加微信|加我|VX|V信|私信|点击主页|主页领取|关注我|点关注|一键三连|双击屏幕|稳赚|必涨|必赚|保本|稳定收益|肯定涨|抄底|逃顶)", re.I),
]


def has_douyin_risk(text: str) -> bool:
    """检查抖音财经内容中容易触发限流或违规的导流诊断话术。"""
    value = text or ""
    return any(pattern.search(value) for pattern in DOUYIN_RISK_PATTERNS)


def safe_pinned_comment(topic: str = "这个话题") -> str:
    short_topic = clean_text(topic)[:18] or "这个话题"
    return f"关于「{short_topic}」，你最想弄明白哪一层影响？可以聊聊你的观察。"


def sanitize_douyin_text(text: str, role: str = "oral", topic: str = "") -> str:
    """移除留代码、诊股、私信加群等风险句，置顶评论命中风险时直接换成讨论问题。"""
    value = (text or "").strip()
    if not value:
        return safe_pinned_comment(topic) if role == "pinned" else ""
    if role == "pinned" and has_douyin_risk(value):
        return safe_pinned_comment(topic)

    segments = re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?|\n+", value) or [value]
    kept = [segment.strip() for segment in segments if segment.strip() and not has_douyin_risk(segment)]
    cleaned = "".join(kept).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"([。！？!?；;]){2,}", r"\1", cleaned)

    if not cleaned and role == "pinned":
        return safe_pinned_comment(topic)
    if not cleaned:
        return "这部分只做逻辑观察，不做具体投资建议，重点看背后的风险和变量。"
    return cleaned


def check_cover_length(cover: str) -> bool:
    """封面文案字数检查：≤12个汉字"""
    return count_chars(cover) <= 12
