# 短视频爆款脚本

全网热点 → 选题 → 一键生成口播脚本。浏览器打开即可用；热点与模型代理由本机轻量 API 提供。

## 本地运行（完整能力）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8765
```

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)，或执行 `./start.sh`。

1. 侧栏填写 OpenAI 兼容 API Key（通义 / DeepSeek / Kimi 等）
2. 「抓取全网热点」，或关键词筛选
3. （可选）粘贴参考文案 →「开始生成」

未填 Key 时可跑演示流水线。

## GitHub Pages

仓库根目录 `index.html` 即为站点首页（与本地 8765 同一套界面）。

仓库 → Settings → Pages → Source 选 **Deploy from a branch** → Branch **main** / **/**（根目录）。

Pages 上浏览时，热点与 LLM 请求会自动指向本机 `http://127.0.0.1:8765`，请先在本机启动上述服务。

## 目录

```text
.
├── index.html          # 默认网页（Pages + uvicorn /）
├── app/                # 本机 API：热点聚合、LLM 代理、提示词
├── requirements.txt
├── start.sh
└── .nojekyll           # Pages 跳过 Jekyll
```

## 接口摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |
| GET | `/api/hot/topics?q=&limit=` | 全网热点 / 关键词筛选 |
| GET | `/api/prompts` | 固化提示词包 |
| GET | `/api/llm/providers` | 厂商列表 |
| POST | `/api/llm/chat` | OpenAI 兼容代理（Key 不落盘） |
