"""
股票选股分析工具 — FastAPI 后端服务
启动: python server.py
"""
import asyncio
import time
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from config import HOST, PORT, CACHE_TTL, DEFAULT_FILTERS
from cache_manager import cache
from models import (
    QuoteItem, QuoteBatchResponse, IntraDayResponse, MoneyFlowResponse,
    KLineResponse, DragonTigerResponse, IndexResponse,
    AnnouncementResponse, StockListResponse,
    MoodResponse, DrawdownResponse,
    ScreenerItem, ScreenerResponse, ErrorResponse,
)
from fetchers import TencentFetcher, SinaFetcher, EastMoneyFetcher, KaipanlaFetcher
from scorer import (
    calc_rsi, calc_macd, score_factors, calc_total_score,
    apply_filters, apply_default_filters, calc_limit_up_count, calc_listed_days,
    DEFAULT_WEIGHTS,
)
from stock_pool import FALLBACK_STOCKS

# ── App ──
app = FastAPI(
    title="Stock Screener API",
    description="多源股票数据聚合与选股评分",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── HTTP客户端（复用一个连接池）──
_http_client: httpx.AsyncClient | None = None
_tencent: TencentFetcher | None = None
_sina: SinaFetcher | None = None
_eastmoney: EastMoneyFetcher | None = None
_kaipanla: KaipanlaFetcher | None = None


def get_tencent() -> TencentFetcher:
    return _tencent  # type: ignore
def get_sina() -> SinaFetcher:
    return _sina   # type: ignore
def get_eastmoney() -> EastMoneyFetcher:
    return _eastmoney  # type: ignore
def get_kaipanla() -> KaipanlaFetcher:
    return _kaipanla  # type: ignore


@app.on_event("startup")
async def startup():
    global _http_client, _tencent, _sina, _eastmoney, _kaipanla
    _http_client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
    _tencent = TencentFetcher(_http_client)
    _sina = SinaFetcher(_http_client)
    _eastmoney = EastMoneyFetcher(_http_client)
    _kaipanla = KaipanlaFetcher(_http_client)
    print(f"[server] 启动完成 http://{HOST}:{PORT}")


@app.on_event("shutdown")
async def shutdown():
    if _http_client:
        await _http_client.aclose()


# ── 静态文件 ──
BASE_DIR = Path(__file__).parent

@app.get("/")
async def index():
    """前端入口"""
    html_path = BASE_DIR / "stock-screener.html"
    if html_path.exists():
        return FileResponse(html_path, media_type="text/html; charset=utf-8")
    return {"message": "Stock Screener API v2.0 — 前端文件请放在同目录"}


# ── 辅助 ──
async def _get_stock_list() -> list[dict]:
    """获取全A股股票列表（优先新浪，失败用东方财富，再失败用本地池）"""
    # 优先：新浪财经 — 全量~5600只，自带行情数据
    sina = get_sina()
    data = await sina.get_stock_list()
    if data:
        print(f"[server] 使用新浪股票列表: {len(data)} 只")
        return data

    # 备选：东方财富
    em = get_eastmoney()
    data = await em.get_stock_list()
    if data:
        print(f"[server] 使用东方财富股票列表: {len(data)} 只")
        return data

    # 兜底：本地精选池
    print("[server] 数据源全部不可用，使用本地精选股票池")
    seen = set()
    pool = []
    for c, n, s in FALLBACK_STOCKS:
        if c not in seen:
            seen.add(c)
            pool.append({"code": c, "name": n, "market": c[:2], "sector": s, "price": 0, "change_pct": 0,
                         "pe": None, "pb": None, "mcap": None, "float_mcap": None, "turnover": 0})
    return pool


# ═══════════════════════════════════════════
# 个股K线（放在腾讯行情之前，避免路由冲突）
# ═══════════════════════════════════════════

@app.get("/api/kline-detail/{code}")
async def stock_kline_detail(code: str, period: str = Query("day", description="day|week|month"), count: int = Query(120, ge=10, le=240)):
    """获取单只股票的K线数据（含均线）"""
    sina = get_sina()
    data = await sina.get_kline_with_ma(code, period=period, count=count)
    if not data or not data.get("data"):
        return {"code": code, "period": period, "data": [], "ma": {}}
    return {
        "code": code,
        "period": period,
        "data": data["data"],
        "ma": data["ma"],
    }


# ═══════════════════════════════════════════
# 涨停板统计 + 主力资金流向
# ═══════════════════════════════════════════

@app.get("/api/market/limit-up")
async def market_limit_up():
    """涨停板综合统计（连板高度、涨停/跌停列表）"""
    em = get_eastmoney()
    result = await em.get_limit_up_stats()
    result["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return result


@app.get("/api/market/money-flow")
async def market_money_flow(top_n: int = Query(20, ge=5, le=50)):
    """主力资金净流入/流出 TOP N"""
    em = get_eastmoney()
    result = await em.get_money_flow_rank(top_n=top_n)
    return {
        "top_n": top_n,
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        **result,
    }


# ═══════════════════════════════════════════
# 行情接口（腾讯财经）
# ═══════════════════════════════════════════

@app.get("/api/quote/batch", response_model=QuoteBatchResponse)
async def quote_batch(codes: str = Query(..., description="逗号分隔股票代码，如 sh600519,sz000001")):
    """批量获取实时行情"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list or len(code_list) > 200:
        raise HTTPException(400, "codes: 1-200只")

    cache_key = f"quote_batch_{','.join(sorted(code_list))}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    tencent = get_tencent()
    raw_data = await tencent.get_batch_quote(code_list)

    result = []
    for d in raw_data:
        try:
            result.append(QuoteItem(
                code=d.get("code", ""),
                name=d.get("name", ""),
                market=d.get("market", "sh"),
                price=d.get("price", 0),
                open=d.get("open", 0),
                high=d.get("high", 0),
                low=d.get("low", 0),
                pre_close=d.get("pre_close", 0),
                change=d.get("change", 0),
                change_pct=d.get("change_pct", 0),
                volume=d.get("volume", 0),
                amount=d.get("amount", 0),
                turnover=d.get("turnover", 0),
                pe=d.get("pe"),
                pb=d.get("pb"),
                mcap=d.get("mcap"),
                float_mcap=d.get("float_mcap"),
                high_52w=d.get("high_52w"),
                low_52w=d.get("low_52w"),
            ))
        except Exception:
            pass

    resp = QuoteBatchResponse(
        data=result,
        update_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    await cache.set(cache_key, resp, CACHE_TTL["quote"])
    return resp


@app.get("/api/quote/{code}/intraday", response_model=IntraDayResponse)
async def quote_intraday(code: str):
    """分时数据"""
    cache_key = f"intraday_{code}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    tencent = get_tencent()
    points = await tencent.get_intraday(code)

    resp = IntraDayResponse(data=[
        {"time": p["time"], "price": p["price"], "volume": p["volume"], "avg_price": p["avg_price"]}
        for p in points
    ])
    await cache.set(cache_key, resp, CACHE_TTL["default"])
    return resp


@app.get("/api/quote/{code}/moneyflow", response_model=MoneyFlowResponse)
async def quote_moneyflow(code: str):
    """资金流向"""
    cache_key = f"moneyflow_{code}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    tencent = get_tencent()
    data = await tencent.get_moneyflow(code)
    resp = MoneyFlowResponse(data=data)
    await cache.set(cache_key, resp, CACHE_TTL["default"])
    return resp


# ═══════════════════════════════════════════
# K线接口（新浪财经）
# ═══════════════════════════════════════════

@app.get("/api/kline/{code}", response_model=KLineResponse)
async def kline(
    code: str,
    period: str = Query("day", description="day|week|month|5min|15min|30min|60min"),
    count: int = Query(250, ge=1, le=240),
    adjust: str = Query("qfq", description="qfq|hfq|none"),
):
    """获取K线（含均线）"""
    ttl = CACHE_TTL["kline_day"] if period == "day" else CACHE_TTL["kline_min"]
    cache_key = f"kline_{code}_{period}_{count}_{adjust}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    sina = get_sina()
    result = await sina.get_kline_with_ma(code, period, count, adjust)

    if not result["data"]:
        raise HTTPException(404, f"K线数据获取失败: {code}")

    resp = KLineResponse(**result)
    await cache.set(cache_key, resp, ttl)
    return resp


# ═══════════════════════════════════════════
# 龙虎榜 + 指数 + 公告 + 股票列表（东方财富）
# ═══════════════════════════════════════════

@app.get("/api/dragon-tiger", response_model=DragonTigerResponse)
async def dragon_tiger(date: str = Query("", description="YYYY-MM-DD, 空=最近")):
    """龙虎榜"""
    cache_key = f"dragon_tiger_{date}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    em = get_eastmoney()
    data = await em.get_dragon_tiger(date)
    resp = DragonTigerResponse(data=data)
    await cache.set(cache_key, resp, CACHE_TTL["dragon_tiger"])
    return resp


@app.get("/api/index")
async def get_indices(
    codes: str = Query("sh000001,sz399001,sz399006", description="逗号分隔指数代码"),
):
    """指数行情"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    cache_key = f"index_{','.join(sorted(code_list))}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    em = get_eastmoney()
    data = await em.get_indices(code_list)
    resp = IndexResponse(data=data)
    await cache.set(cache_key, resp, CACHE_TTL["index"])
    return resp


@app.get("/api/announcements/{code}", response_model=AnnouncementResponse)
async def announcements(
    code: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """公司公告"""
    cache_key = f"announce_{code}_{page}_{size}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    em = get_eastmoney()
    result = await em.get_announcements(code, page, size)
    resp = AnnouncementResponse(**result)
    await cache.set(cache_key, resp, CACHE_TTL["announcement"])
    return resp


@app.get("/api/stock-list", response_model=StockListResponse)
async def stock_list():
    """全A股列表"""
    cached = await cache.get("stock_list_full")
    if cached:
        return cached

    data = await _get_stock_list()
    resp = StockListResponse(data=data, total=len(data))
    await cache.set("stock_list_full", resp, CACHE_TTL["stock_list"])
    return resp


# ═══════════════════════════════════════════
# 监控面板（开盘啦）
# ═══════════════════════════════════════════

@app.get("/api/monitoring/mood", response_model=MoodResponse)
async def monitoring_mood():
    """市场情绪"""
    cached = await cache.get("mood")
    if cached:
        return cached

    kp = get_kaipanla()
    data = await kp.get_mood()
    resp = MoodResponse(data=data)
    await cache.set("mood", resp, CACHE_TTL["mood"])
    return resp


@app.get("/api/monitoring/drawdown", response_model=DrawdownResponse)
async def monitoring_drawdown():
    """大幅回撤"""
    cached = await cache.get("drawdown")
    if cached:
        return cached

    kp = get_kaipanla()
    data = await kp.get_drawdown_stocks()
    resp = DrawdownResponse(data=data)
    await cache.set("drawdown", resp, CACHE_TTL["default"])
    return resp


# ═══════════════════════════════════════════
# 综合选股（核心接口）
# ═══════════════════════════════════════════

@app.get("/api/screener", response_model=ScreenerResponse)
async def screener(
    limit: int = Query(200, ge=10, le=500, description="返回TOP N只"),
    # ── 自定义筛选参数 ──
    exclude_st: bool = Query(True, description="排除ST/*ST"),
    min_listed_days: int = Query(60, ge=0, le=9999, description="上市天数 ≥"),
    float_mcap_min: float = Query(30, ge=0, description="流通市值下限(亿)"),
    float_mcap_max: float = Query(120, ge=0, description="流通市值上限(亿)"),
    chg_20d_min: float = Query(0, description="20日涨跌幅下限(%)"),
    chg_20d_max: float = Query(50, description="20日涨跌幅上限(%)"),
    ma_bullish: bool = Query(True, description="MA5>MA10>MA20 多头排列"),
    close_above_ma5: bool = Query(True, description="收盘价 > MA5"),
    min_limit_up_10d: int = Query(1, ge=0, le=10, description="近10日涨停次数 ≥"),
    turnover_min: float = Query(3, ge=0, description="换手率下限(%)"),
    turnover_max: float = Query(15, ge=0, description="换手率上限(%)"),
    sort: str = Query("score", description="排序字段: score|pe|change_pct|turnover"),
    full_market: bool = Query(False, description="全市场模式：分析所有候选股票（较慢但完整）"),
):
    """
    综合选股接口 — 支持自定义筛选条件
    1. 获取全市场列表 → 批量行情 → K线+技术指标 → 涨停检测 → 评分 → 筛选 → 排序
    """
    # 构建筛选条件字典
    custom_filters = {
        "exclude_st": exclude_st,
        "min_listed_days": min_listed_days,
        "float_mcap_min": float_mcap_min,
        "float_mcap_max": float_mcap_max,
        "chg_20d_min": chg_20d_min,
        "chg_20d_max": chg_20d_max,
        "ma_bullish": ma_bullish,
        "close_above_ma5": close_above_ma5,
        "min_limit_up_10d": min_limit_up_10d,
        "turnover_min": turnover_min,
        "turnover_max": turnover_max,
    }

    cache_key = f"screener_f{full_market}_l{limit}_s{sort}_{hash(frozenset(custom_filters.items()))}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    start_time = time.time()

    # Step 1: 获取全市场股票列表（新浪自带行情数据: price/pe/pb/mcap/turnover）
    all_stocks = await _get_stock_list()
    if not all_stocks:
        raise HTTPException(503, "获取股票列表失败")

    # Step 2: 第一阶段 — 只用列表自带数据筛选（不取K线，极快）
    if exclude_st:
        candidates = [s for s in all_stocks
            if "ST" not in s.get("name", "").upper() and "退" not in s.get("name", "")
               and s.get("price", 0) > 0]
    else:
        candidates = [s for s in all_stocks if s.get("price", 0) > 0]

    cheap_passed = []
    cheap_stats = {"total": len(all_stocks), "mcap_out": 0, "turnover_out": 0, "no_price": 0}

    for s in candidates:
        fm = s.get("float_mcap") or 0
        to = s.get("turnover") or 0
        if fm < float_mcap_min or fm > float_mcap_max:
            cheap_stats["mcap_out"] += 1
            continue
        if to < turnover_min or to > turnover_max:
            cheap_stats["turnover_out"] += 1
            continue
        cheap_passed.append(s)

    cheap_stats["passed"] = len(cheap_passed)
    # 调试：打印候选池的市场分布
    _mkt = {}
    for _s in cheap_passed:
        _m = _s.get("market", "?")
        _mkt[_m] = _mkt.get(_m, 0) + 1
    print(f"[screener] 第一阶段完成 | 候选总计 {len(cheap_passed)} | 市场分布 {_mkt}")
    print(f"[screener] 第一阶段 {len(candidates)} → 市值淘汰{cheap_stats['mcap_out']} 换手淘汰{cheap_stats['turnover_out']} → 候选 {len(cheap_passed)}")

    # Step 3: 第二阶段 — 对候选人取K线做技术分析 + 涨停检测
    sina = get_sina()
    results = []

    # 全市场模式：分析所有候选；快速模式：上限300
    max_kline = len(cheap_passed) if full_market else min(len(cheap_passed), 300)
    if full_market:
        print(f"[screener] 全市场模式：将分析全部 {max_kline} 只候选股票")
    
    # 并发控制：全市场模式限制同时请求数避免被封
    sem = asyncio.Semaphore(15) if full_market else asyncio.Semaphore(999)
    
    async def analyze_one(stock: dict) -> dict | None:
        async with sem:
            code = stock["code"]
            price = stock.get("price", 0)
            name = stock.get("name", "")
            pe = stock.get("pe")
            pb = stock.get("pb")
            turnover = stock.get("turnover", 0)
            float_mcap = stock.get("float_mcap") or 0
            mcap = stock.get("mcap") or 0

            rsi_val = 50.0
            macd_stat = "无信号"
            ma_status = "震荡"
            ma5 = ma10 = ma20 = ma60 = None
            chg_20d = 0.0
            limit_up_count = 0
            listed_days = 180

            try:
                kline_data = await sina.get_kline(code, period="day", count=120)
                if kline_data and len(kline_data) >= 20:
                    closes = [k["close"] for k in kline_data]

                    # RSI
                    rsi_val = calc_rsi(closes) or 50.0
                    # MACD
                    macd_stat = calc_macd(closes) or "无信号"

                    # 均线
                    if len(closes) >= 60:
                        ma5 = round(sum(closes[-5:]) / 5, 2)
                        ma10 = round(sum(closes[-10:]) / 10, 2)
                        ma20 = round(sum(closes[-20:]) / 20, 2)
                        ma60 = round(sum(closes[-60:]) / 60, 2)
                        if ma5 > ma10 > ma20:
                            ma_status = "多头"
                        elif ma5 < ma10 < ma20:
                            ma_status = "空头"
                        elif price > ma60:
                            ma_status = "above_ma60"
                        elif price > ma20:
                            ma_status = "above_ma20"

                    # 20日涨跌幅
                    if len(closes) >= 21:
                        chg_20d = round((closes[-1] - closes[-21]) / closes[-21] * 100, 2)

                    # 涨停检测
                    limit_up_count = calc_limit_up_count(kline_data, code, days=10)
                    # 上市天数
                    listed_days = calc_listed_days(kline_data)

            except Exception as e:
                print(f"[screener] K线失败 {code}: {e}")
                return None

            # 评分
            factors = score_factors(pe, pb, None, None, ma_status, macd_stat, rsi_val, 0)
            score = calc_total_score(factors)

            return {
                "code": code, "name": name, "market": stock.get("market", "sh"),
                "sector": stock.get("sector", "综合"), "price": price,
                "change_pct": stock.get("change_pct", 0), "pe": pe, "pb": pb,
                "roe": None, "float_mcap": float_mcap, "mcap": mcap,
                "turnover": turnover, "listed_days": listed_days,
                "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
                "ma_status": ma_status, "rsi_14": rsi_val, "macd_status": macd_stat,
                "vol_ratio": 0, "chg_20d": chg_20d,
                "limit_up_count_10d": limit_up_count, "score": score,
            }
    
    tasks = [analyze_one(stock) for stock in cheap_passed[:max_kline]]
    gathered = await asyncio.gather(*tasks)
    results = [r for r in gathered if r is not None]

    # Step 4: 筛选（应用需要K线的条件：均线/涨跌幅/涨停/上市天数）
    results = apply_filters(results, custom_filters)
    # 调试：打印筛选结果的市值分布
    _mkt2 = {}
    for _s in results:
        _m = _s.get("market", "?")
        _mkt2[_m] = _mkt2.get(_m, 0) + 1
    print(f"[screener] 筛选后 {len(results)} 只 | 市场分布 {_mkt2}")

    # Step 5: 排序
    if sort == "pe":
        results.sort(key=lambda x: x.get("pe") or 9999, reverse=False)
    elif sort == "change_pct":
        results.sort(key=lambda x: x.get("change_pct", 0), reverse=True)
    elif sort == "turnover":
        results.sort(key=lambda x: x.get("turnover", 0), reverse=True)
    else:
        results.sort(key=lambda x: x["score"], reverse=True)

    # 取Top N
    results = results[:limit]

    elapsed = time.time() - start_time
    print(f"[screener] 筛选完成: {len(results)} 只, 耗时 {elapsed:.1f}s")

    resp = ScreenerResponse(
        data=[ScreenerItem(**r) for r in results],
        total=len(results),
        update_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    await cache.set(cache_key, resp, CACHE_TTL["default"])
    return resp


# ═══════════════════════════════════════════
# 健康检查 + 缓存管理
# ═══════════════════════════════════════════

@app.get("/api/health")
async def health():
    """健康检查"""
    stats = await cache.stats()
    return {
        "status": "ok",
        "time": datetime.now().isoformat(),
        "cache": stats,
    }

@app.post("/api/cache/clear")
async def cache_clear(prefix: str = ""):
    """清除缓存"""
    await cache.clear(prefix)
    return {"message": f"缓存已清除 (prefix={prefix or '全部'})"}


# ── 启动 ──
if __name__ == "__main__":
    import uvicorn
    print(f"=== Stock Screener v2.0 ===")
    print(f"启动: http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
