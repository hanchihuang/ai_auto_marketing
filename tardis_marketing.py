"""
Tardis 营销专用模块

提供 Tardis 服务的营销功能，包括：
- 高意图关键词搜索
- Sober 用户名过滤
- 专业数据服务话术生成
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TardisCommentStrategy(Enum):
    """Tardis 专用评论策略"""
    DIAGNOSIS = "diagnosis"      # 诊断型 - 指出问题是数据层而非模型层
    VALUE_ADD = "value_add"       # 价值型 - 强调 tick 数据的独特价值
    SAMPLE = "sample"             # 样例型 - 提供免费样例数据
    DEMO = "demo"                 # 演示型 - 引导 demo 预约


# Tardis 营销关键词库 - 按优先级分类
TARDIS_KEYWORDS = {
    # 最高优先级 - 直接数据痛点
    "critical": [
        "crypto tick data",
        "historical tick data",
        "crypto order book data",
        "L2 order book crypto",
        "tick-level data",
    ],
    # 高优先级 - 交易所历史数据
    "high": [
        "binance futures historical data",
        "bybit historical data",
        "okx historical data",
        "deribit options data",
        "crypto options data",
    ],
    # 中优先级 - 衍生品数据
    "medium": [
        "perp funding rate data",
        "liquidation data crypto",
        "open interest history crypto",
        "market microstructure crypto",
        "execution research crypto",
    ],
    # 常规优先级 - 研究相关
    "regular": [
        "slippage model crypto",
        "trade replay crypto",
        "backtesting crypto data",
        "quant research crypto",
        "vol surface crypto",
        "implied volatility crypto",
    ],
}

# 完整关键词库 - 包含用户提供的所有关键词
FULL_TARDIS_KEYWORDS = [
    # 最高优先级关键词
    "crypto tick data",
    "historical tick data",
    "crypto order book data",
    "L2 order book crypto",
    "tick-level data",
    # 高优先级关键词
    "binance futures historical data",
    "bybit historical data",
    "okx historical data",
    "deribit options data",
    "crypto options data",
    # 中优先级关键词
    "perp funding rate data",
    "liquidation data crypto",
    "open interest history crypto",
    "market microstructure crypto",
    "execution research crypto",
    # 常规优先级关键词
    "slippage model crypto",
    "trade replay crypto",
    "backtesting crypto data",
    "quant research crypto",
    "vol surface crypto",
    "implied volatility crypto",
    # 更多高意图关键词
    "historical market data",
    "order book data",
    "market microstructure",
    "trade replay",
    "historical trades",
    "funding rate data",
    "liquidation data",
    "open interest data",
    "options data",
    "options chain",
    "implied volatility",
    "backtesting data",
    "quant research",
    "execution data",
    "slippage model",
    "latency arbitrage",
    "perp data",
    "Deribit data",
    "Binance futures data",
    "Bybit historical data",
    # 组合搜索关键词
    "(tick data OR order book data) (crypto OR bitcoin OR perp OR options)",
    "(historical market data OR backtesting data) (binance OR bybit OR deribit OR okx)",
    "(funding rate OR liquidation OR open interest) (historical OR api OR data)",
    "(options data OR vol surface OR implied volatility) (crypto OR deribit)",
    "(market microstructure OR execution model OR slippage) crypto",
]

# 所有关键词 flat 列表
ALL_TARDIS_KEYWORDS = FULL_TARDIS_KEYWORDS


# 过滤词 - 排除噪音帖子
EXCLUDE_FILTERS = [
    "-airdrop",
    "-giveaway",
    "-meme",
    "-priceprediction",
    "- Prediction",
    "- pump",
]


@dataclass
class TardisProduct:
    """Tardis 产品信息"""
    name: str = "Tardis"
    tagline: str = "Raw Tick-Level Market Data API"
    description: str = "提供 spot / perpetual / futures / options 的原始 tick 数据，支持 exchange-native 和 normalized 两种数据形态"
    website: str = "https://tardis.dev"
    demo_link: str = "https://tardis.dev/demo"
    sample_keywords: list[str] = field(default_factory=lambda: [
        "Binance futures tick sample",
        "Deribit options sample",
        "Funding + liquidation sample dataset",
    ])


# 诊断型话术 - 指出问题是数据粒度而非模型
DIAGNOSIS_TEMPLATES = [
    "你这个问题其实是数据粒度问题，不是模型问题。要做准确的回测，至少需要 trades + L2 order book + instrument metadata。",
    "大部分回测不准，不是因为策略差，而是因为数据层就已经错了。OHLCV 解决不了 order book / liquidation / funding 这些研究。",
    "如果你要做这个方向的回测，candle 数据是不够的，尤其是 funding / options / order book 这类微观结构研究。",
    "你描述的这个场景，用 tick-level 数据和完整 order book 会更准确。OHLCV 的精度不足以支撑这类研究。",
]

# 价值型话术 - 强调数据完整性和开发时间节省
VALUE_ADD_TEMPLATES = [
    "Tardis 提供完整的 tick-level 历史数据，覆盖主流交易所的 spot / perp / futures / options，省掉你自己抓数据、补断线、做标准化的麻烦。",
    "自己抓交易所 WebSocket 的隐性成本远高于 API 价格。Tardis 已经帮你处理好了跨交易所标准化和期权元数据。",
    "研究团队最贵的不是 API 费，而是开发时间。Tardis 让你专注策略研究，而不是数据维护。",
    "做跨交易所历史数据研究最难的不是抓单一交易所，而是标准化。Tardis 已经处理好了这些坑。",
]

# 样例型话术 - 提供免费样例
SAMPLE_TEMPLATES = [
    "如果你愿意，我可以给你一个对应交易所/品种的样例数据结构，包含 trades + L2 + funding。",
    "可以先给你一份指定交易所的历史 tick 样例，验证数据质量后再决定。",
    "需要的话我发你一个 Binance futures / Deribit options 的样例数据集你自己跑跑看。",
    "免费样例数据我可以提供：交易所 + 品种 + 时间段你指定。",
]

# 演示型话术 - 引导 demo
DEMO_TEMPLATES = [
    "5 分钟 demo 可以帮你快速验证这个方向的数据可行性，要不要安排一下？",
    "如果你在评估数据可行性，一个针对你研究方向的 quick demo 最直接。",
    "可以预约一个 5 分钟的 demo，帮你确认这个数据源是否满足你的研究需求。",
    "如果你想了解哪个交易所的数据质量更好，我可以安排一个针对性 demo。",
]


# 硬约束：所有评论必须带上 Tardis 链接
TARDIS_LINK = "https://tardis.dev"
# 如果需要用微信文章链接，可以改成: "https://mp.weixin.qq.com/s/EqruJSaA7YHWz9Sms4eF9w"

# CTA 话术 - 最终引导（每条评论都会自动追加，必须带链接）
CTA_TEMPLATES = [
    f"感兴趣的话可以看看 {TARDIS_LINK} ，有免费样例可以先试。",
    f"需要更详细的信息可以访问 {TARDIS_LINK} 或 DM 我安排 demo。",
    f"更多细节可以看 {TARDIS_LINK} ，或者告诉我你需要的交易所/品种，我给你发样例。",
    f"点击查看 {TARDIS_LINK} ，免费样例数据先到先得。",
    f"想了解更多？{TARDIS_LINK} 有完整的数据文档和样例。",
]


class TardisCommentGenerator:
    """Tardis 专用评论生成器"""

    def __init__(self, product: Optional[TardisProduct] = None):
        self.product = product or TardisProduct()

    def _should_filter_author(self, author_name: str) -> bool:
        """检查作者名是否应该被过滤（包含 Sober/sober）"""
        if not author_name:
            return False
        author_lower = author_name.lower()
        return "sober" in author_lower

    def _extract_exchange_mention(self, post_content: str) -> list[str]:
        """从帖子内容中提取提到的交易所"""
        exchanges = []
        content_lower = post_content.lower()
        
        exchange_names = {
            "binance": ["binance", "bnb"],
            "bybit": ["bybit"],
            "okx": ["okx", "okex"],
            "deribit": ["deribit"],
            "huobi": ["huobi", "htx"],
            "gate": ["gate", "gt"],
        }
        
        for exchange, keywords in exchange_names.items():
            if any(kw in content_lower for kw in keywords):
                exchanges.append(exchange)
        
        return exchanges

    def _extract_data_type_mention(self, post_content: str) -> list[str]:
        """从帖子内容中提取提到的数据类型"""
        data_types = []
        content_lower = post_content.lower()
        
        type_keywords = {
            "tick": ["tick", "tick-level", "tick data"],
            "orderbook": ["order book", "l2", "lob", "depth"],
            "ohlcv": ["candle", "ohlcv", "kline"],
            "funding": ["funding", "funding rate"],
            "liquidation": ["liquidation", "liquidations"],
            "open_interest": ["open interest", "oi"],
            "options": ["option", "options", "vol", "volatility", "iv"],
            "perp": ["perpetual", "perp", "futures"],
            "spot": ["spot"],
            "backtest": ["backtest", "backtesting", "回测"],
            "microstructure": ["microstructure", "微观结构"],
        }
        
        for dtype, keywords in type_keywords.items():
            if any(kw in content_lower for kw in keywords):
                data_types.append(dtype)
        
        return data_types

    def _personalize_comment(self, base_comment: str, post_content: str) -> str:
        """根据帖子内容个性化评论"""
        exchanges = self._extract_exchange_mention(post_content)
        data_types = self._extract_data_type_mention(post_content)
        
        personalized = base_comment
        
        # 如果帖子提到了具体交易所，尝试个性化
        if exchanges and data_types:
            # 优先匹配交易所 + 数据类型的组合
            if "tick" in data_types or "orderbook" in data_types:
                if "binance" in exchanges or "bybit" in exchanges or "deribit" in exchanges:
                    personalized = personalized.replace(
                        "trades + L2",
                        f"trades + L2 order book ({', '.join(exchanges)})"
                    )
        
        return personalized

    def generate_comment(
        self,
        strategy: TardisCommentStrategy = TardisCommentStrategy.DIAGNOSIS,
        post_content: str = "",
    ) -> str:
        """生成评论内容"""
        templates = {
            TardisCommentStrategy.DIAGNOSIS: DIAGNOSIS_TEMPLATES,
            TardisCommentStrategy.VALUE_ADD: VALUE_ADD_TEMPLATES,
            TardisCommentStrategy.SAMPLE: SAMPLE_TEMPLATES,
            TardisCommentStrategy.DEMO: DEMO_TEMPLATES,
        }
        
        base_comment = random.choice(templates[strategy])
        
        # 如果提供了帖子内容，尝试个性化
        if post_content:
            base_comment = self._personalize_comment(base_comment, post_content)
        
        # 硬约束：每条评论都必须带 Tardis 链接
        cta = random.choice(CTA_TEMPLATES)
        return f"{base_comment}\n\n{cta}"
        
        return base_comment

    def generate_diagnostic_comment(self, post_content: str = "") -> str:
        """生成诊断型评论"""
        return self.generate_comment(TardisCommentStrategy.DIAGNOSIS, post_content)

    def generate_value_add_comment(self, post_content: str = "") -> str:
        """生成价值型评论"""
        return self.generate_comment(TardisCommentStrategy.VALUE_ADD, post_content)

    def generate_sample_comment(self, post_content: str = "") -> str:
        """生成样例型评论"""
        return self.generate_comment(TardisCommentStrategy.SAMPLE, post_content)

    def generate_demo_comment(self, post_content: str = "") -> str:
        """生成演示型评论"""
        return self.generate_comment(TardisCommentStrategy.DEMO, post_content)


def get_keywords_by_priority(priority: str = "all") -> list[str]:
    """获取指定优先级的关键词"""
    if priority == "all":
        return ALL_TARDIS_KEYWORDS
    return TARDIS_KEYWORDS.get(priority, [])


def build_search_query(base_keyword: str, add_filters: bool = True) -> str:
    """构建搜索查询"""
    query = base_keyword
    if add_filters:
        query += " " + " ".join(EXCLUDE_FILTERS)
    return query


def is_relevant_post(post_content: str, post_title: str = "") -> bool:
    """判断帖子是否与 Tardis 服务相关"""
    content = (post_content + " " + post_title).lower()
    
    # 正面关键词 - 相关主题
    positive_keywords = [
        "tick", "order book", "l2", "depth", "market data",
        "historical data", "backtest", "回测", "quant", "quantitative",
        "trading", "trader", "strategy", "futures", "perpetual", "options",
        "funding", "liquidation", "open interest", "volatility", "iv",
        "microstructure", "execution", "slippage", "binance", "bybit",
        "deribit", "okx", "exchange", "api", "data source",
    ]
    
    # 负面关键词 - 噪音
    negative_keywords = [
        "airdrop", "giveaway", "meme", "pump", "dump", "price prediction",
        " сигнал", "signal", "shill", "抽水", "喊单",
    ]
    
    # 检查负面关键词
    if any(neg in content for neg in negative_keywords):
        return False
    
    # 检查正面关键词
    return any(pos in content for pos in positive_keywords)


# 自动营销任务配置
@dataclass
class TardisCampaign:
    """Tardis 营销活动配置"""
    name: str = "Tardis Crypto Data Campaign"
    keywords: list[str] = field(default_factory=lambda: ALL_TARDIS_KEYWORDS[:20])
    priority_keywords: list[str] = field(default_factory=lambda: TARDIS_KEYWORDS["critical"])
    strategy: TardisCommentStrategy = TardisCommentStrategy.DIAGNOSIS
    max_posts_per_keyword: int = 20
    max_comments: int = 50
    min_likes: int = 0
    filter_sober: bool = True
    add_exclude_filters: bool = True


# 快速活动预设
CAMPAIGN_PRESETS = {
    "quick": TardisCampaign(
        name="Quick Test",
        keywords=["crypto tick data", "order book data crypto"],
        max_posts_per_keyword=10,
        max_comments=20,
    ),
    "full": TardisCampaign(
        name="Full Campaign",
        keywords=ALL_TARDIS_KEYWORDS,
        max_posts_per_keyword=20,
        max_comments=50,
    ),
    "critical_only": TardisCampaign(
        name="Critical Keywords Only",
        keywords=TARDIS_KEYWORDS["critical"],
        max_posts_per_keyword=30,
        max_comments=30,
    ),
}
