"""
Pydantic 数据模型
"""
from pydantic import BaseModel
from typing import Optional


# ── 腾讯财经 ──
class QuoteItem(BaseModel):
    code: str
    name: str
    market: str              # sh / sz / bj
    price: float
    open: float
    high: float
    low: float
    pre_close: float
    change: float            # 涨跌额
    change_pct: float        # 涨跌幅%
    volume: int              # 成交量(手)
    amount: float            # 成交额(万元)
    turnover: float          # 换手率%
    pe: Optional[float] = None
    pb: Optional[float] = None
    mcap: Optional[float] = None      # 总市值(亿)
    float_mcap: Optional[float] = None # 流通市值(亿)
    listed_days: int = 365
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None

class QuoteBatchResponse(BaseModel):
    data: list[QuoteItem]
    update_time: str

class IntraDayPoint(BaseModel):
    time: str
    price: float
    volume: int
    avg_price: float

class IntraDayResponse(BaseModel):
    data: list[IntraDayPoint]

class MoneyFlowData(BaseModel):
    main_net_inflow: Optional[float] = None
    super_large_net: Optional[float] = None
    large_net: Optional[float] = None
    mid_net: Optional[float] = None
    small_net: Optional[float] = None

class MoneyFlowResponse(BaseModel):
    data: MoneyFlowData


# ── 新浪 K线 ──
class KLineItem(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int

class KLineResponse(BaseModel):
    data: list[KLineItem]
    ma: dict[str, list[Optional[float]]]  # ma5, ma10, ma20, ma60


# ── 东方财富 ──
class SeatItem(BaseModel):
    name: str
    type: str               # 买/卖
    buy: float
    sell: float
    net: float

class DragonTigerItem(BaseModel):
    code: str
    name: str
    close: float
    change_pct: float
    turnover: float
    net_buy: float           # 净买额(万)
    buy_total: float
    sell_total: float
    reason: str              # 上榜原因
    seats: list[SeatItem]

class DragonTigerResponse(BaseModel):
    data: list[DragonTigerItem]

class IndexItem(BaseModel):
    code: str
    name: str
    price: float
    change: float
    change_pct: float
    volume: Optional[int] = None
    amount: Optional[float] = None

class IndexResponse(BaseModel):
    data: list[IndexItem]

class AnnouncementItem(BaseModel):
    title: str
    date: str
    type: str               # 公告/研报/新闻
    url: str

class AnnouncementResponse(BaseModel):
    data: list[AnnouncementItem]
    total: int

class StockListItem(BaseModel):
    code: str
    name: str
    market: str
    sector: str

class StockListResponse(BaseModel):
    data: list[StockListItem]
    total: int


# ── 开盘啦 ──
class MoodData(BaseModel):
    up_count: int
    down_count: int
    flat_count: int
    limit_up: int
    limit_down: int
    limit_up_open: int       # 炸板数
    mood_index: float        # 情绪指数

class MoodResponse(BaseModel):
    data: MoodData

class LimitStock(BaseModel):
    code: str
    name: str
    board_height: int        # 连板数
    change_pct: float
    first_time: str          # 首次涨停时间

class LimitAnalysisData(BaseModel):
    boards: dict[int, list[LimitStock]]  # key=连板高度
    open_rate: float         # 炸板率%
    total_limit_up: int
    total_open: int

class LimitAnalysisResponse(BaseModel):
    data: LimitAnalysisData

class DrawdownItem(BaseModel):
    code: str
    name: str
    from_high_pct: float     # 距前高%
    current_chg: float       # 当日涨幅
    drawdown_pct: float      # 最大回撤%

class DrawdownResponse(BaseModel):
    data: list[DrawdownItem]


# ── 综合选股 ──
class ScreenerItem(BaseModel):
    code: str
    name: str
    market: str
    sector: str
    price: float
    change_pct: float
    pe: Optional[float] = None
    pb: Optional[float] = None
    roe: Optional[float] = None
    float_mcap: float
    mcap: float
    turnover: float
    listed_days: int
    # 均线
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    ma_status: str = "震荡"    # 多头/空头/震荡
    # 技术指标
    rsi_14: Optional[float] = None
    macd_status: str = "无信号"  # 金叉/死叉/无信号
    vol_ratio: Optional[float] = None
    chg_20d: Optional[float] = None
    limit_up_count_10d: int = 0
    # 评分
    score: float = 0.0

class ScreenerResponse(BaseModel):
    data: list[ScreenerItem]
    total: int
    update_time: str


# ── 通用 ──
class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
