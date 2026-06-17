"""
评分引擎 — 从原HTML提取逻辑，8维度加权评分
"""
import math
from typing import Optional


# 默认权重（与前端一致）
DEFAULT_WEIGHTS = {
    "pe": 15,
    "pb": 10,
    "roe": 15,
    "npg": 10,
    "ma": 15,
    "macd": 10,
    "rsi": 10,
    "vol": 15,
}


def calc_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """计算RSI指标"""
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    # 取最近period
    recent_gains = gains[-period:]
    recent_losses = losses[-period:]

    avg_gain = sum(recent_gains) / period
    avg_loss = sum(recent_losses) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def calc_macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[str]:
    """计算MACD信号（金叉/死叉/多头/空头）"""
    if len(closes) < slow + signal:
        return None

    # EMA计算
    ema_fast = closes[0]
    ema_slow = closes[0]
    k_fast = 2 / (fast + 1)
    k_slow = 2 / (slow + 1)

    diffs = []
    for price in closes[1:]:
        ema_fast = price * k_fast + ema_fast * (1 - k_fast)
        ema_slow = price * k_slow + ema_slow * (1 - k_slow)
        diffs.append(ema_fast - ema_slow)

    # DEA (Signal)
    dea = diffs[0]
    k_sig = 2 / (signal + 1)
    macd_hist = []

    for diff in diffs[1:]:
        dea = diff * k_sig + dea * (1 - k_sig)
        macd_hist.append(2 * (diff - dea))

    if len(macd_hist) < 3:
        return None

    # 判断信号
    latest = macd_hist[-1]
    prev = macd_hist[-2]
    prev2 = macd_hist[-3]

    if latest > 0 and prev <= 0:
        return "golden"  # 金叉
    if latest < 0 and prev >= 0:
        return "dead"    # 死叉
    if latest > 0:
        return "positive"  # 多头
    return "negative"    # 空头


def score_factors(
    pe: Optional[float],
    pb: Optional[float],
    roe: Optional[float],
    npgrowth: Optional[float],
    ma_status: str,
    macd_status: str,
    rsi: Optional[float],
    vol_ratio: Optional[float],
) -> dict:
    """计算8个维度得分(0-100)"""

    # PE: 越低越好，PE>150得0分
    if pe and pe > 0:
        f_pe = max(0, min(100, 100 - (pe / 150) * 100))
    else:
        f_pe = 50  # 无数据默认

    # PB: 越低越好
    if pb and pb > 0:
        f_pb = max(0, min(100, 100 - (pb / 20) * 100))
    else:
        f_pb = 50

    # ROE: 越高越好
    if roe is not None:
        f_roe = max(0, min(100, (roe / 40) * 100))
    else:
        f_roe = 50

    # 利润增速: 基准-30%到80%，映射0-100
    if npgrowth is not None:
        f_npg = max(0, min(100, (npgrowth + 30) / 110 * 100))
    else:
        f_npg = 50

    # 均线
    ma_score_map = {"多头": 100, "above_ma60": 70, "above_ma20": 50}
    f_ma = ma_score_map.get(ma_status, 20)

    # MACD
    macd_score_map = {"golden": 100, "positive": 65, "negative": 35, "dead": 10}
    f_macd = macd_score_map.get(macd_status, 50)

    # RSI: 40-65最佳
    if rsi and 40 <= rsi <= 65:
        f_rsi = 100
    elif rsi and 65 < rsi <= 75:
        f_rsi = 70
    elif rsi and 30 <= rsi < 40:
        f_rsi = 60
    elif rsi:
        f_rsi = 30
    else:
        f_rsi = 50

    # 量比: 越高越活跃，但太高的也不好
    if vol_ratio and vol_ratio > 0:
        f_vol = min(100, (vol_ratio / 5) * 100)
    else:
        f_vol = 50

    return {
        "f_pe": round(f_pe, 1),
        "f_pb": round(f_pb, 1),
        "f_roe": round(f_roe, 1),
        "f_npg": round(f_npg, 1),
        "f_ma": f_ma,
        "f_macd": f_macd,
        "f_rsi": f_rsi,
        "f_vol": round(f_vol, 1),
    }


def calc_total_score(factors: dict, weights: dict | None = None) -> float:
    """综合评分 0-100"""
    if weights is None:
        weights = DEFAULT_WEIGHTS

    total_weight = sum(weights.values()) or 100

    score = (
        factors["f_pe"] * weights.get("pe", 0) +
        factors["f_pb"] * weights.get("pb", 0) +
        factors["f_roe"] * weights.get("roe", 0) +
        factors["f_npg"] * weights.get("npg", 0) +
        factors["f_ma"] * weights.get("ma", 0) +
        factors["f_macd"] * weights.get("macd", 0) +
        factors["f_rsi"] * weights.get("rsi", 0) +
        factors["f_vol"] * weights.get("vol", 0)
    ) / total_weight

    return round(score, 1)


def calc_limit_up_count(kline_data: list[dict], code: str, days: int = 10) -> int:
    """统计近N天涨停次数"""
    if len(kline_data) < 2:
        return 0

    # 涨停阈值
    raw_code = code.replace("sh", "").replace("sz", "").replace("bj", "")
    if raw_code.startswith("68") or raw_code.startswith("30"):
        threshold = 19.8   # 科创板/创业板 ±20%
    elif raw_code.startswith("8") or raw_code.startswith("4"):
        threshold = 29.8   # 北交所 ±30%
    else:
        threshold = 9.8    # 主板 ±10%

    count = 0
    recent = kline_data[-days - 1:]

    for i in range(1, len(recent)):
        prev_close = recent[i - 1].get("close", 0)
        curr_close = recent[i].get("close", 0)
        if prev_close <= 0:
            continue
        chg_pct = (curr_close - prev_close) / prev_close * 100
        if chg_pct >= threshold:
            count += 1

    return count


def calc_listed_days(kline_data: list[dict]) -> int:
    """从K线数据推算上市天数（自然日），兜底180天"""
    if not kline_data:
        return 180
    try:
        from datetime import datetime
        first = kline_data[0].get("date", "")
        if not first:
            return 180
        first_date = datetime.strptime(first, "%Y-%m-%d")
        today = datetime.now()
        return (today - first_date).days
    except Exception:
        return 180


def apply_filters(stocks: list[dict], filters: dict) -> list[dict]:
    """根据传入条件筛选股票"""
    f = filters

    filtered = []
    for s in stocks:
        # 1. 排除ST/*ST
        if f.get("exclude_st", True):
            name = s.get("name", "")
            if "ST" in name.upper():
                continue
        # 2. 上市天数
        if s.get("listed_days", 0) < f.get("min_listed_days", 0):
            continue
        # 3. 流通市值
        fm = s.get("float_mcap", 0) or 0
        f_min = f.get("float_mcap_min", 0)
        f_max = f.get("float_mcap_max", 999999)
        if fm < f_min or fm > f_max:
            continue
        # 4. 20日涨跌幅
        chg = s.get("chg_20d", 0) or 0
        if chg <= f.get("chg_20d_min", -100) or chg >= f.get("chg_20d_max", 100):
            continue
        # 5. 均线多头 (MA5>MA10>MA20)
        if f.get("ma_bullish", False) and s.get("ma_status") != "多头":
            continue
        # 6. 收盘价 > MA5
        if f.get("close_above_ma5", False):
            price = s.get("price", 0)
            ma5 = s.get("ma5", 0) or 0
            if price <= ma5:
                continue
        # 7. 涨停次数
        if s.get("limit_up_count_10d", 0) < f.get("min_limit_up_10d", 0):
            continue
        # 8. 换手率
        turnover = s.get("turnover", 0) or 0
        if turnover < f.get("turnover_min", 0) or turnover > f.get("turnover_max", 999):
            continue

        filtered.append(s)

    return filtered


def apply_default_filters(stocks: list[dict]) -> list[dict]:
    """向后兼容：使用默认筛选条件"""
    from config import DEFAULT_FILTERS
    return apply_filters(stocks, DEFAULT_FILTERS)
