"""LLM 统一调用封装，支持 OpenAI 兼容接口（百炼 / DeepSeek / Moonshot / 本地模型等）"""
import json
import asyncio
from typing import Optional
from openai import AsyncOpenAI
from config import config

_client: Optional[AsyncOpenAI] = None
# 当前使用的模型在 fallback 列表中的索引（额度耗尽后递增）
_model_idx: int = 0


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
        )
    return _client


def _is_auth_error(exc: Exception) -> bool:
    """API Key 无效类错误不应继续切换模型。"""
    status_code = getattr(exc, "status_code", None)
    text = str(exc)
    return status_code == 401 or any(
        marker in text
        for marker in ("InvalidApiKey", "Invalid API key", "Unauthorized", "Authentication", "NoApiKey")
    )


def _is_switchable_model_error(exc: Exception) -> bool:
    """判断是否可通过切换百炼模型继续重试。"""
    if _is_auth_error(exc):
        return False
    status_code = getattr(exc, "status_code", None)
    text = str(exc)
    markers = (
        "AllocationQuota", "FreeTier", "quota", "Arrearage", "InsufficientBalance",
        "RateLimit", "TooManyRequests", "Throttl", "ModelNotFound", "ModelUnavailable",
        "InvalidModel", "model not found", "model not exist", "model not available",
        "unsupported", "not support", "AccessDenied", "NoPermission", "PermissionDenied",
        "Forbidden",
    )
    return status_code == 429 or any(marker.lower() in text.lower() for marker in markers)


async def chat(system: str, user: str, json_mode: bool = False, retries: int = 3) -> str:
    """
    向 LLM 发送请求并返回文本。
    json_mode=True 时强制 JSON 输出（需模型支持）。
    免费额度耗尽、限流或模型未开通时自动切换 fallback 模型。
    """
    global _model_idx
    models = config.llm_fallback_models or [config.model]

    for mi in range(_model_idx, len(models)):
        model = models[mi]
        kwargs: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.7,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        quota_exhausted = False
        for attempt in range(retries):
            try:
                resp = await get_client().chat.completions.create(**kwargs)
                if mi != _model_idx:
                    _model_idx = mi
                    print(f"[LLM] 已切换到模型: {model}")
                return resp.choices[0].message.content or ""
            except Exception as exc:
                if _is_switchable_model_error(exc):
                    print(f"[LLM] {model} 额度/权限/限流不可用，切换下一个模型…")
                    _model_idx = max(_model_idx, mi + 1)
                    quota_exhausted = True
                    break
                if attempt == retries - 1:
                    raise
                wait = 2 ** attempt
                print(f"[LLM] {model} 第{attempt+1}次失败: {exc}，{wait}s 后重试…")
                await asyncio.sleep(wait)
        if not quota_exhausted:
            break

    raise RuntimeError(
        f"所有模型({', '.join(models)})均不可用，"
        "请检查 API Key 权限、免费额度或余额"
    )


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
