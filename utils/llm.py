"""LLM 统一调用封装，支持 OpenAI 兼容接口（DeepSeek / Moonshot / 本地模型等）"""
import json
import asyncio
from typing import Optional
from openai import AsyncOpenAI
from config import config

_client: Optional[AsyncOpenAI] = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
        )
    return _client


async def chat(system: str, user: str, json_mode: bool = False, retries: int = 3) -> str:
    """
    向 LLM 发送请求并返回文本。
    json_mode=True 时强制 JSON 输出（需模型支持）。
    """
    kwargs: dict = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.7,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(retries):
        try:
            resp = await get_client().chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as exc:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            print(f"[LLM] 第{attempt+1}次失败: {exc}，{wait}s 后重试…")
            await asyncio.sleep(wait)
    return ""


async def chat_json(system: str, user: str) -> dict:
    """返回解析好的 JSON dict，失败时返回空 dict"""
    raw = await chat(system, user, json_mode=True)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 兼容模型不严格输出 JSON 的情况：尝试提取第一个 {...}
        import re
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
        print(f"[LLM] JSON 解析失败，原始输出：{raw[:200]}")
        return {}
