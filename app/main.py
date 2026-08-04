"""MVP 入口：根目录页面 + 热点 API + 主流模型 LLM 代理。

启动：
  pip install -r requirements.txt
  uvicorn app.main:app --host 127.0.0.1 --port 8765

浏览器打开 http://127.0.0.1:8765
GitHub Pages 默认呈现根目录 index.html（完整能力需本机 API）。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.hot_topics import fetch_all_hot_topics
from app.llm_proxy import LLMChatRequest, chat_completions, provider_catalog
from app.prompts import get_prompts
from app.topic_filter import filter_by_keyword, rank_by_heat

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"

app = FastAPI(title="短视频爆款脚本 MVP", version="0.6.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def allow_private_network_access(request, call_next):
    """允许 GitHub Pages / file:// 对本机 127.0.0.1 的请求（Chrome Private Network Access）。"""
    if request.method == "OPTIONS" and request.headers.get("access-control-request-private-network") == "true":
        from fastapi.responses import Response

        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Allow-Private-Network": "true",
            },
        )
    response = await call_next(request)
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    if "access-control-allow-origin" not in {k.lower() for k in response.headers.keys()}:
        response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "mvp": True,
        "helper_required": False,
        "platforms": [
            "微博热搜", "百度热搜", "今日头条热榜", "腾讯热榜",
            "抖音热榜", "B站热门", "第一财经", "东方财富", "资讯RSS",
        ],
        "llm_providers": [p["id"] for p in provider_catalog()],
    }


@app.get("/api/llm/providers")
async def llm_providers() -> dict:
    return {"ok": True, "providers": provider_catalog()}


@app.get("/api/prompts")
async def prompts() -> dict:
    return {"ok": True, "prompts": get_prompts()}


@app.post("/api/llm/chat")
async def llm_chat(req: LLMChatRequest) -> dict:
    """代理调用任意 OpenAI 兼容厂商。API Key 仅用于本次请求，不落盘。"""
    try:
        result = await chat_completions(req)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"上游调用失败: {exc}") from exc
    if not result.get("ok"):
        raise HTTPException(
            status_code=int(result.get("status") or 502),
            detail=result.get("error") or "调用失败",
        )
    return result


@app.get("/api/hot/topics")
async def hot_topics(
    limit: int = Query(default=80, ge=1, le=200),
    q: str = Query(default="", description="关键词，支持空格/逗号分隔多个词"),
) -> dict:
    raw_topics, source_results = await fetch_all_hot_topics()
    query = (q or "").strip()
    if query:
        limited = filter_by_keyword(raw_topics, query, limit=limit)
        filter_name = "keyword"
    else:
        limited = rank_by_heat(raw_topics, limit=limit)
        filter_name = "all_platforms"

    source_summary: dict[str, int] = {}
    for topic in limited:
        name = topic.source.split("/")[0]
        source_summary[name] = source_summary.get(name, 0) + 1

    return {
        "ok": True,
        "q": query,
        "total": len(limited),
        "raw_total": len(raw_topics),
        "limit": limit,
        "filter": filter_name,
        "source_summary": source_summary,
        "sources": [s.to_dict() for s in source_results],
        "topics": [t.to_dict() for t in limited],
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(INDEX)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8765, reload=True)
