"""OpenAI compatible LLM proxy for mainstream providers."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import aiohttp
from pydantic import BaseModel, Field

LLM_PROVIDERS: List[Dict[str, Any]] = [
    {
        "id": "dashscope",
        "name": "\u901a\u4e49\u767e\u70bc / \u5343\u95ee",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-turbo", "qwen-max", "qwen-long", "qwen2.5-72b-instruct"],
        "hint": "\u963f\u91cc\u4e91\u767e\u70bc\u63a7\u5236\u53f0",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1", "o4-mini"],
        "hint": "platform.openai.com",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "hint": "platform.deepseek.com",
    },
    {
        "id": "moonshot",
        "name": "\u6708\u4e4b\u6697\u9762 Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k", "kimi-latest"],
        "hint": "platform.moonshot.cn",
    },
    {
        "id": "zhipu",
        "name": "\u667a\u8c31 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-flash", "glm-4-air", "glm-4-plus", "glm-4.5-flash"],
        "hint": "open.bigmodel.cn",
    },
    {
        "id": "siliconflow",
        "name": "\u7845\u57fa\u6d41\u52a8",
        "base_url": "https://api.siliconflow.cn/v1",
        "models": [
            "deepseek-ai/DeepSeek-V3",
            "Qwen/Qwen2.5-72B-Instruct",
            "Qwen/Qwen3-8B",
            "THUDM/GLM-4-9B-0414",
        ],
        "hint": "siliconflow.cn",
    },
    {
        "id": "yi",
        "name": "\u96f6\u4e00\u4e07\u7269 Yi",
        "base_url": "https://api.lingyiwanwu.com/v1",
        "models": ["yi-lightning", "yi-large", "yi-medium"],
        "hint": "platform.lingyiwanwu.com",
    },
    {
        "id": "doubao",
        "name": "\u706b\u5c71\u65b9\u821f / \u8c46\u5305",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": ["doubao-1-5-pro-32k", "doubao-1-5-lite-32k"],
        "hint": "\u586b\u5199\u65b9\u821f\u63a8\u7406\u63a5\u5165\u70b9 ID \u4f5c\u4e3a\u6a21\u578b\u540d",
    },
    {
        "id": "custom",
        "name": "\u81ea\u5b9a\u4e49 OpenAI \u517c\u5bb9",
        "base_url": "",
        "models": [],
        "hint": "\u4efb\u610f\u517c\u5bb9 /v1/chat/completions \u7684\u670d\u52a1",
    },
]


class ChatMessage(BaseModel):
    role: str
    content: str


class LLMChatRequest(BaseModel):
    api_key: str = Field(..., min_length=1)
    base_url: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    messages: List[ChatMessage]
    temperature: float = Field(default=0.8, ge=0, le=2)
    fallback_models: List[str] = Field(default_factory=list)


def normalize_base_url(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/completions"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


def provider_catalog() -> List[Dict[str, Any]]:
    return LLM_PROVIDERS


async def chat_completions(req: LLMChatRequest) -> Dict[str, Any]:
    base = normalize_base_url(req.base_url)
    if not base.startswith("http"):
        raise ValueError("base_url must start with http:// or https://")

    models: List[str] = []
    for m in [req.model, *req.fallback_models]:
        name = (m or "").strip()
        if name and name not in models:
            models.append(name)
    if not models:
        raise ValueError("model is required")

    endpoint = f"{base}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {req.api_key.strip()}",
    }
    payload_messages = [{"role": m.role, "content": m.content} for m in req.messages]

    last_error = ""
    async with aiohttp.ClientSession() as session:
        for model in models:
            body = {
                "model": model,
                "messages": payload_messages,
                "temperature": req.temperature,
            }
            try:
                async with session.post(
                    endpoint,
                    headers=headers,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=120),
                    ssl=None,
                ) as resp:
                    text = await resp.text()
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = {"raw": text[:500]}

                    if resp.status >= 400:
                        err = _extract_error(data, text)
                        last_error = f"{model} HTTP {resp.status}: {err}"
                        if _is_switchable(resp.status, err):
                            continue
                        return {
                            "ok": False,
                            "status": resp.status,
                            "model": model,
                            "error": last_error,
                        }

                    content = _extract_content(data)
                    if content is None:
                        last_error = f"{model}: empty content"
                        continue

                    return {
                        "ok": True,
                        "model": model,
                        "content": content,
                        "usage": data.get("usage") if isinstance(data, dict) else None,
                    }
            except Exception as exc:
                last_error = f"{model}: {exc}"
                continue

    return {"ok": False, "status": 502, "error": last_error or "all models failed"}


def _extract_error(data: Any, text: str) -> str:
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or err)[:240]
        if err:
            return str(err)[:240]
        return str(data)[:240]
    return (text or "")[:240]


def _extract_content(data: Any) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    choices = data.get("choices") or []
    if not choices:
        return None
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if content is None:
        return None
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text") or "")
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content)


def _is_switchable(status: int, err: str) -> bool:
    if status in (401, 403):
        return False
    markers = (
        "quota", "rate", "limit", "balance", "arrearage", "model",
        "not found", "not exist", "unavailable", "overloaded", "429",
        "insufficient", "freetier", "allocation",
    )
    lower = (err or "").lower()
    return status == 429 or any(m in lower for m in markers)
