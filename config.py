"""
股票选股工具 — 全局配置
"""
import os

# 服务配置
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8888))  # Render 会注入 PORT 环境变量

# 缓存TTL（秒）
CACHE_TTL = {
    "quote":        300,    # 实时行情 5分钟（手动刷新，被动失效）
    "kline_day":    3600,   # 日K线 1小时
    "kline_min":    60,     # 分钟K线 60秒
    "dragon_tiger": 3600,   # 龙虎榜 1小时
    "announcement": 7200,   # 公告 2小时
    "mood":         30,     # 市场情绪 30秒
    "stock_list":   86400,  # 股票列表 24小时
    "index":        10,     # 指数 10秒
    "default":      300,    # 默认 5分钟
}

# 请求配置
HTTP_TIMEOUT = 5           # 默认超时(秒)
HTTP_TIMEOUT_KLINE = 15    # K线请求超时
MAX_RETRIES = 2            # 最大重试次数
RETRY_DELAY = 1            # 重试基础延迟(秒)

# User-Agent 池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

# 选股默认条件（老大指定）
DEFAULT_FILTERS = {
    "exclude_st": True,              # 排除ST/*ST
    "min_listed_days": 60,           # 上市 > 60天
    "float_mcap_min": 30,            # 流通市值 >= 30亿
    "float_mcap_max": 120,           # 流通市值 <= 120亿
    "chg_20d_min": 0,                # 20日涨跌幅 > 0%
    "chg_20d_max": 50,               # 20日涨跌幅 < 50%
    "ma_bullish": True,              # MA5 > MA10 > MA20
    "close_above_ma5": True,         # 收盘价 > MA5
    "min_limit_up_10d": 1,           # 近10日涨停 >= 1
    "turnover_min": 3,               # 换手率 >= 3%
    "turnover_max": 15,              # 换手率 <= 15%
}
