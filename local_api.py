"""本地采集桥接 API。

启动：
  python3 local_api.py

前端 index.html 会调用 http://127.0.0.1:8765/api/viral/search 获取真实来源素材。
"""
from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import config
from utils.viral_bridge import check_douyin_status, search_viral_content


class ViralSearchRequest(BaseModel):
    keyword: str = Field(default="", description="关键词")
    source_url: str = Field(default="", description="抖音/小红书/文章来源链接")
    limit: int = Field(default=6, ge=1, le=20, description="最多返回条数")


app = FastAPI(title="AI Agent Viral Source Bridge", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "douk_api_base": config.douk_api_base,
        "xhs_api_base": config.xhs_api_base,
    }


@app.get("/api/douyin/status")
async def douyin_status(keyword: str = "测试") -> dict:
    return await check_douyin_status(keyword)


@app.post("/api/viral/search")
async def viral_search(req: ViralSearchRequest) -> dict:
    return await search_viral_content(req.keyword, req.source_url, req.limit)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=config.local_api_port)