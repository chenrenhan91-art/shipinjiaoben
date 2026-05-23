"""本机采集助手 API。

启动：
  python3 local_api.py

前端 index.html 会调用 http://127.0.0.1:8765 自动检测、登录和采集真实来源素材。
"""
from __future__ import annotations

import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import config
from utils.helper_supervisor import (
    ensure_douyin_tool_started,
    helper_status,
    import_douyin_cookie_from_browser,
    open_douyin_login_page,
    open_douyin_search_page,
    set_douyin_cookie_direct,
)
from utils.crawler import fetch_all_hot_topics
from utils.topic_filter import rank_relevant_topics
from utils.viral_bridge import check_douyin_status, extract_source_content, search_viral_content, get_video_transcript


class ViralSearchRequest(BaseModel):
    keyword: str = Field(default="", description="关键词")
    source_url: str = Field(default="", description="抖音/小红书/文章来源链接")
    limit: int = Field(default=6, ge=1, le=20, description="最多返回条数")
    video_only: bool = Field(default=False, description="是否直接搜索关键词相关视频")


class SourceExtractRequest(BaseModel):
    source_url: str = Field(default="", description="抖音/小红书/文章来源链接")


app = FastAPI(title="AI Agent Viral Source Bridge", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def allow_private_network_access(request, call_next):
    response = await call_next(request)
    if request.headers.get("access-control-request-private-network") == "true":
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.get("/api/health")
async def health() -> dict:
    # 读取安装时写入的版本号（由 install_macos_helper.sh 生成）
    version_file = os.path.join(os.path.dirname(__file__), "VERSION")
    helper_version = ""
    try:
        helper_version = open(version_file).read().strip()
    except OSError:
        pass
    return {
        "ok": True,
        "helper": "running",
        "version": helper_version,
        "douk_api_base": config.douk_api_base,
        "xhs_api_base": config.xhs_api_base,
    }


@app.get("/api/helper/status")
async def get_helper_status() -> dict:
    return await helper_status()


@app.post("/api/helper/start")
async def start_helper_services() -> dict:
    return await ensure_douyin_tool_started()


@app.post("/api/helper/restart-douyin")
async def restart_douyin_tool() -> dict:
    return await ensure_douyin_tool_started()


@app.post("/api/helper/import-douyin-cookie")
async def import_douyin_cookie(browser: str = "chrome") -> dict:
    return await import_douyin_cookie_from_browser(browser)


class SetCookieRequest(BaseModel):
    cookie: str = Field(default="", description="抖音 Cookie 字符串")


@app.post("/api/helper/set-douyin-cookie")
async def set_douyin_cookie(payload: SetCookieRequest) -> dict:
    return await set_douyin_cookie_direct(payload.cookie)


class TranscriptRequest(BaseModel):
    url: str = Field(default="", description="抖音视频链接")
    api_key: str = Field(default="", description="OpenAI API Key（可选，优先级高于服务端配置）")


@app.post("/api/helper/transcript")
async def get_transcript(payload: TranscriptRequest) -> dict:
    return await get_video_transcript(payload.url, api_key=payload.api_key or None)


@app.post("/api/helper/open-douyin-login")
async def open_douyin_login(keyword: str = "") -> dict:
    return open_douyin_login_page(keyword)


@app.post("/api/helper/open-douyin-search")
async def open_douyin_search(keyword: str = "财经热点") -> dict:
    return open_douyin_search_page(keyword)


@app.get("/api/douyin/status")
async def douyin_status(keyword: str = "测试") -> dict:
    await ensure_douyin_tool_started()
    return await check_douyin_status(keyword)


@app.post("/api/viral/search")
async def viral_search(req: ViralSearchRequest) -> dict:
    await ensure_douyin_tool_started()
    return await search_viral_content(req.keyword, req.source_url, req.limit, req.video_only)


@app.get("/api/hot/topics")
async def hot_topics(limit: int = 80) -> dict:
    limit = max(1, min(limit, 120))
    raw_topics = await fetch_all_hot_topics()
    limited_topics = rank_relevant_topics(raw_topics, limit=limit)
    source_summary: dict[str, int] = {}
    for topic in limited_topics:
        source_name = topic.source.split("/")[0]
        source_summary[source_name] = source_summary.get(source_name, 0) + 1
    return {
        "ok": True,
        "total": len(limited_topics),
        "raw_total": len(raw_topics),
        "limit": limit,
        "filter": "finance_tech_relevant",
        "source_summary": source_summary,
        "topics": [topic.model_dump(mode="json") for topic in limited_topics],
    }


@app.post("/api/source/extract")
async def source_extract(req: SourceExtractRequest) -> dict:
    return await extract_source_content(req.source_url)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=config.local_api_port)