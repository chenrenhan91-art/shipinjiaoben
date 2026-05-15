"""
Agent 1：热点感知 Agent
- 从 36氪 RSS、百度热搜、今日头条热榜、腾讯热榜、微博热搜聚合热点
- 所有热点最终服务财经类口播脚本：直接财经 > 政经/时事 > 财经桥接 > 泛娱乐 > 其他
- 财经桥接：互联网大厂/消费/就业/监管等可从财经视角切入的话题
- 按加权热度降序，输出 Top60
"""
from typing import List
from agents.base_agent import BaseAgent
from data_models import HotTopic
from utils.crawler import fetch_all_hot_topics

# ① 直接财经/科技关键词：热度 ×3（财经IP首选）
FINANCE_KEYWORDS = [
    "经济", "股市", "股票", "A股", "港股", "基金", "债券", "楼市", "房价",
    "利率", "央行", "美联储", "通胀", "GDP", "财政", "汇率", "黄金", "石油",
    "科技股", "新能源", "消费", "就业", "银行", "保险", "理财", "投资",
    "上市", "IPO", "退市", "暴跌", "暴涨", "熔断", "降息", "加息",
    "芯片", "AI", "人工智能", "大模型", "科技", "贸易", "关税", "制裁",
    "汽车", "电动车", "互联网", "数字经济", "碳中和", "双碳",
]

# ② 政经/时事关键词：热度 ×2.5（有明显宏观经济含义）
HOT_EVENT_KEYWORDS = [
    "特朗普", "美国", "中美", "普京", "俄罗斯", "乌克兰", "日本", "欧盟",
    "习近平", "国务院", "政府", "政策", "会议", "峰会", "谈判", "制裁",
    "战争", "冲突", "灾难", "地震", "疫情", "事故",
]

# ③ 财经桥接关键词：泛话题但可从财经视角切入，热度 ×2（新增）
#    互联网大厂 → 股价/战略解读；消费/就业 → 经济晴雨表；监管 → 行业影响
FINANCIAL_BRIDGE_KEYWORDS = [
    # 互联网/科技巨头（股价/业绩/战略）
    "腾讯", "阿里", "字节", "百度", "美团", "京东", "拼多多", "滴滴",
    "华为", "小米", "比亚迪", "宁德时代", "蔚来", "理想", "小鹏",
    "苹果", "谷歌", "微软", "英伟达", "特斯拉", "亚马逊",
    # 消费/电商/就业（经济晴雨表）
    "电商", "直播带货", "外卖", "快递", "网购",
    "工资", "薪资", "裁员", "招聘", "副业", "创业", "失业",
    # 政策/监管（行业财经影响）
    "补贴", "监管", "反垄断", "合规", "数据安全", "平台经济",
    # 文娱经济（票仓/IP价值）
    "票房", "版权", "IP", "游戏", "演出", "影视",
    # 房产/教育经济
    "买房", "租房", "装修", "考研", "留学", "培训班",
]

# ④ 通用高传播关键词（纯娱乐/社会）：热度 ×1.5（兜底，无明显财经切入点）
GENERAL_VIRAL_KEYWORDS = [
    "明星", "网红", "出轨", "离婚", "结婚", "恋爱", "塌房", "翻车",
    "综艺", "电影", "爆火", "爆款", "出圈",
    "高考", "医院", "医疗", "健康", "减肥",
    "法院", "判决", "案件", "警方", "犯罪", "诈骗",
    "旅游", "景区", "奥运", "世界杯", "体育", "冠军",
]


def _boost_score(topic: HotTopic) -> float:
    """财经收束加权：直接财经 > 政经时事 > 财经桥接 > 泛娱乐 > 其他"""
    text = topic.title + topic.summary
    base = topic.heat_score + 1  # +1 避免 heat_score=0 时排序失效
    if any(kw in text for kw in FINANCE_KEYWORDS):
        return base * 3
    if any(kw in text for kw in HOT_EVENT_KEYWORDS):
        return base * 2.5
    if any(kw in text for kw in FINANCIAL_BRIDGE_KEYWORDS):
        return base * 2           # 新增桥接层，高于纯娱乐
    if any(kw in text for kw in GENERAL_VIRAL_KEYWORDS):
        return base * 1.5
    return base


class HotTopicAgent(BaseAgent):
    def __init__(self):
        super().__init__("HotTopicAgent")

    async def run(self) -> List[HotTopic]:
        self.log("开始抓取热点（36氪/百度/头条/腾讯/微博）…")
        topics = await fetch_all_hot_topics()
        self.log(f"原始热点 {len(topics)} 条")

        # 财经收束：加权排序让直接财经 > 政经 > 可桥接财经话题自然浮到前排
        topics.sort(key=_boost_score, reverse=True)

        from collections import Counter
        src_dist = Counter(t.source.split("/")[0] for t in topics[:60])
        self.log(f"Top60 来源分布: {dict(src_dist)}")
        return topics[:60]  # 最多送 60 条给决策层
