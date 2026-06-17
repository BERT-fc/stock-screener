"""
新浪财经数据爬取器
- 全A股股票列表（含行情）
- 日/周/月K线 + 复权
"""
import json
import asyncio
from .base import BaseFetcher


class SinaFetcher(BaseFetcher):
    """新浪财经：股票列表 + K线数据 + 均线计算"""

    KLINE_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    STOCK_LIST_URL = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"

    PERIOD_MAP = {
        "day": "240",    # 日线，参数datalen最大240
        "week": "5",     # 周线
        "month": "6",    # 月线
        "5min": "5",
        "15min": "15",
        "30min": "30",
        "60min": "60",
    }

    @staticmethod
    def _code_to_symbol(code: str) -> str:
        """转新浪格式: sh600519 → sh600519"""
        return code

    @staticmethod
    def calc_ma(data: list[dict], period: int) -> list[float | None]:
        """计算移动均线"""
        result = [None] * len(data)
        closes = [item["close"] for item in data]
        for i in range(period - 1, len(closes)):
            result[i] = round(sum(closes[i - period + 1:i + 1]) / period, 2)
        return result

    async def get_kline(self, code: str, period: str = "day",
                         count: int = 250, adjust: str = "qfq") -> list[dict]:
        """
        获取K线数据
        period: day | week | month | 5min | 15min | 30min | 60min
        adjust: qfq(前复权) | hfq(后复权) | none(不复权)
        """
        symbol = self._code_to_symbol(code)
        scale = self.PERIOD_MAP.get(period, "240")

        # 对于日线，新浪最大返回240条
        params = {
            "symbol": symbol,
            "scale": scale,
            "ma": "no",
            "datalen": min(count, 240),
        }

        try:
            text = await self._request(self.KLINE_URL, params=params)
            data = json.loads(text)

            if not isinstance(data, list):
                return []

            klines = []
            for item in data:
                klines.append({
                    "date": item.get("day", ""),
                    "open": self.safe_float(item.get("open")),
                    "high": self.safe_float(item.get("high")),
                    "low": self.safe_float(item.get("low")),
                    "close": self.safe_float(item.get("close")),
                    "volume": self.safe_int(item.get("volume")),
                })

            return klines

        except Exception as e:
            print(f"[Sina] kline failed for {code} ({period}): {e}")
            return []

    async def get_kline_with_ma(self, code: str, period: str = "day",
                                 count: int = 250, adjust: str = "qfq") -> dict:
        """获取K线并附带均线"""
        klines = await self.get_kline(code, period, count, adjust)

        ma = {
            "ma5": self.calc_ma(klines, 5),
            "ma10": self.calc_ma(klines, 10),
            "ma20": self.calc_ma(klines, 20),
            "ma60": self.calc_ma(klines, 60),
        }

        return {"data": klines, "ma": ma}

    @staticmethod
    def get_ma_status(data: list[dict]) -> str:
        """判断均线排列状态"""
        if len(data) < 2:
            return "震荡"
        latest = data[-1]
        ma5 = latest.get("ma5")
        ma10 = latest.get("ma10")
        ma20 = latest.get("ma20")
        if ma5 is None or ma10 is None or ma20 is None:
            return "震荡"
        if ma5 > ma10 > ma20:
            return "多头"
        if ma5 < ma10 < ma20:
            return "空头"
        return "震荡"

    @staticmethod
    def _code_to_market(code: str) -> str:
        """根据代码前缀推断市场"""
        c = code.strip()
        if c.startswith("60"):
            return "sh"
        if c.startswith("68"):
            return "sh"
        if c.startswith("00") or c.startswith("30") or c.startswith("002") or c.startswith("003"):
            return "sz"
        if c.startswith("4") or c.startswith("8") or c.startswith("92"):
            return "bj"
        return "sh"

    @staticmethod
    def _code_to_sector(code: str) -> str:
        """根据代码前缀粗略划分行业"""
        c = code.strip()
        if c.startswith("60") or c.startswith("68"):
            return "沪市主板" if c.startswith("60") else "科创板"
        if c.startswith("000") or c.startswith("001") or c.startswith("002") or c.startswith("003"):
            return "深市主板"
        if c.startswith("300") or c.startswith("301"):
            return "创业板"
        if c.startswith("4") or c.startswith("8") or c.startswith("92"):
            return "北交所"
        return "其他"

    async def get_stock_list(self, max_pages: int = 60, per_page: int = 100) -> list[dict]:
        """
        从新浪获取全A股股票列表（分页拉取，每页100只）
        分别拉取沪市(sh_a)、深市(sz_a)、北交所(bj_a)，然后合并
        返回: [{code, name, market, sector, price, change_pct, pe, pb, mcap, float_mcap, turnover}]
        """
        all_stocks = []
        # 沪市 + 深市：分别拉取
        nodes = ["sh_a", "sz_a"]
        
        for node in nodes:
            print(f"[Sina] 开始拉取 {node} ...")
            for page in range(1, max_pages + 1):
                params = {
                    "page": page,
                    "num": per_page,
                    "sort": "symbol",
                    "asc": "1",
                    "node": node,
                }
                try:
                    text = await self._request(self.STOCK_LIST_URL, params=params)
                    data = json.loads(text)
                    if not data or not isinstance(data, list) or len(data) == 0:
                        break

                    for item in data:
                        code = item.get("code", "")
                        if not code:
                            continue
                        name = item.get("name", "")

                        # 排除ST、*ST、退市
                        if "ST" in name or "退" in name:
                            continue

                        market = self._code_to_market(code)
                        sector = self._code_to_sector(code)

                        # 新浪 mktcap/nmc 单位是万元 → 转为亿元
                        mcap_val = self.safe_float(item.get("mktcap"))
                        nmc_val = self.safe_float(item.get("nmc"))
                        mcap_yi = round(mcap_val / 10000, 2) if mcap_val else None
                        nmc_yi = round(nmc_val / 10000, 2) if nmc_val else None
                        pe_val = self.safe_float(item.get("per"))
                        pb_val = self.safe_float(item.get("pb"))

                        all_stocks.append({
                            "code": f"{market}{code}",
                            "name": name,
                            "market": market,
                            "sector": sector,
                            "price": self.safe_float(item.get("trade")),
                            "change_pct": self.safe_float(item.get("changepercent")),
                            "pe": pe_val if (pe_val and pe_val > 0 and pe_val < 10000) else None,
                            "pb": pb_val if (pb_val and pb_val > 0 and pb_val < 1000) else None,
                            "mcap": mcap_yi,
                            "float_mcap": nmc_yi,
                            "turnover": self.safe_float(item.get("turnoverratio")),
                        })

                except Exception as e:
                    print(f"[Sina] stock_list {node} page {page} failed: {e}")
                    break
            
            print(f"[Sina] {node} 拉取完成，当前累计 {len(all_stocks)} 只")
        
        # 北交所：从 hs_a 中过滤（bj_a 不存在）
        print(f"[Sina] 开始拉取北交所(从 hs_a 过滤)...")
        bj_stocks = []
        for page in range(1, max_pages + 1):
            params = {
                "page": page,
                "num": per_page,
                "sort": "symbol",
                "asc": "1",
                "node": "hs_a",
            }
            try:
                text = await self._request(self.STOCK_LIST_URL, params=params)
                data = json.loads(text)
                if not data or not isinstance(data, list) or len(data) == 0:
                    break
                
                # 只保留北交所股票（代码以 4/8/92 开头）
                for item in data:
                    code = item.get("code", "")
                    if not code:
                        continue
                    if not (code.startswith("4") or code.startswith("8") or code.startswith("92")):
                        continue
                    
                    name = item.get("name", "")
                    if "ST" in name or "退" in name:
                        continue

                    market = "bj"
                    sector = self._code_to_sector(code)

                    mcap_val = self.safe_float(item.get("mktcap"))
                    nmc_val = self.safe_float(item.get("nmc"))
                    mcap_yi = round(mcap_val / 10000, 2) if mcap_val else None
                    nmc_yi = round(nmc_val / 10000, 2) if nmc_val else None
                    pe_val = self.safe_float(item.get("per"))
                    pb_val = self.safe_float(item.get("pb"))

                    bj_stocks.append({
                        "code": f"{market}{code}",
                        "name": name,
                        "market": market,
                        "sector": sector,
                        "price": self.safe_float(item.get("trade")),
                        "change_pct": self.safe_float(item.get("changepercent")),
                        "pe": pe_val if (pe_val and pe_val > 0 and pe_val < 10000) else None,
                        "pb": pb_val if (pb_val and pb_val > 0 and pb_val < 1000) else None,
                        "mcap": mcap_yi,
                        "float_mcap": nmc_yi,
                        "turnover": self.safe_float(item.get("turnoverratio")),
                    })

            except Exception as e:
                print(f"[Sina] stock_list bj page {page} failed: {e}")
                break
        
        all_stocks.extend(bj_stocks)
        print(f"[Sina] 北交所拉取完成，新增 {len(bj_stocks)} 只，当前累计 {len(all_stocks)} 只")

        print(f"[Sina] 全市场股票列表拉取完成: {len(all_stocks)} 只")
        return all_stocks
