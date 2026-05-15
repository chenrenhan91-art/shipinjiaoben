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


def check_cover_length(cover: str) -> bool:
    """封面文案字数检查：≤12个汉字"""
    return count_chars(cover) <= 12
