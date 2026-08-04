# 短视频爆款脚本 AI Agent · MVP

通用短视频脚本工具：抓取全网热点 → 选题 → 一键生成口播脚本。  
**不再需要下载本机采集助手 / DouK / Cookie 安装包。**

## 30 秒启动

```bash
cd shipinjiaoben-main
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8765
```

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)

> **不要用 Finder 双击 / `file://` 打开 `static/index.html`。**  
> 热点接口走本机服务，必须通过上面的地址访问；也可用 `./start.sh` 一键启动并打开浏览器。

1. 左侧粘贴百炼（DashScope）OpenAI 兼容 API Key  
2. 点「抓取全网热点」，或输入关键词点「查询」筛选  
3. （可选）粘贴参考文案  
4. 点「开始生成」

未填 Key 时可跑演示流水线，预览界面与输出结构。

或一键启动：

```bash
./start.sh
```

## 模型接入（OpenAI 兼容）

侧栏可选厂商，经本机 `/api/llm/chat` 代理转发（避开浏览器 CORS）：

- 通义百炼 / 千问
- OpenAI
- DeepSeek
- 月之暗面 Kimi
- 智谱 GLM
- 硅基流动
- 零一万物 Yi
- 火山方舟 / 豆包
- 自定义 Base URL + 模型名

配置保存在浏览器 localStorage，Key 不落盘。

| 平台 | 类型 |
|---|---|
| 微博热搜 | 实时热搜 |
| 百度热搜 | 实时热搜 |
| 今日头条热榜 | 热榜 |
| 腾讯热榜 | 热榜 |
| 抖音热榜 | 网页公开热搜榜 |
| B站热门 | 热门视频 |
| 第一财经 / 东方财富 / 资讯 RSS | 资讯补充 |

接口：`GET /api/hot/topics?q=AI&limit=100`  
- 不传 `q`：返回全网热点  
- 传 `q`：按关键词筛选（支持空格/逗号分隔多词）  
响应含各源成功/失败状态。

## 当前结构

```text
shipinjiaoben-main/
├── app/
│   ├── main.py           # 唯一后端：页面 + /api/hot/topics
│   ├── hot_topics.py     # 多平台公开热点聚合
│   └── topic_filter.py   # 通用热度排序 / 可选金融过滤
├── static/index.html     # 控制台前端（保留原设计语言）
├── archive/              # 旧版完整实现（助手、多 Agent CLI 等）
└── requirements.txt
```

## 相对旧版砍掉了什么

| 旧复杂度 | MVP 处理 |
|---|---|
| 本机采集助手安装包 | 删除依赖 |
| DouK / Cookie 作品级抓取 | 改用抖音公开热搜榜 |
| 多 Agent CLI、定时推送 | 暂不纳入 MVP |

旧代码仍在 `archive/`。
