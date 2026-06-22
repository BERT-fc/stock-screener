"""
东方财富数据爬取器
- 龙虎榜 + 买卖席位
- 指数行情
- 公司公告
- 全A股列表
"""
import json
import re
from .base import BaseFetcher


class EastMoneyFetcher(BaseFetcher):
    """东方财富：龙虎榜、席位、指数、公告、股票列表"""

    # 龙虎榜接口
    DRAGON_TIGER_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    DRAGON_LIST_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"

    # 指数接口
    INDEX_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"

    # 公告接口
    ANNOUNCEMENT_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"

    # 股票列表
    STOCK_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"

    # 东方财富板块分类（用于 sector 映射）
    SECTOR_MAP = {
        "BK0477": "半导体",
        "BK0490": "证券",
        "BK0475": "银行",
        "BK0473": "保险",
        "BK0736": "白酒",
        "BK0479": "医疗器械",
        "BK0449": "新能源汽车",
        "BK0451": "光伏",
        "BK0480": "军工",
        "BK0493": "房地产",
        "BK0459": "电力",
        "BK0485": "煤炭",
        "BK0500": "钢铁",
        "BK0478": "汽车整车",
    }

    async def get_dragon_tiger(self, date: str = "") -> list[dict]:
        """
        获取龙虎榜数据
        date: YYYY-MM-DD，空字符串取最近交易日
        """
        params = {
            "reportName": "RPT_DAILY_BILLBOARDTRADING",
            "columns": "ALL",
            "sortColumns": "CHANGE_RATE",
            "sortTypes": "-1",
            "pageSize": 200,
            "pageNumber": 1,
            "source": "WEB",
            "client": "WEB",
        }
        if date:
            params["filter"] = f'(TRADE_DATE=\'{date.replace("-", "")}\')'
        else:
            params["filter"] = "(TRADE_DATE>='2026-06-01')"

        try:
            text = await self._request(self.DRAGON_LIST_URL, params=params)
            data = json.loads(text)
            items = []
            if data.get("success") and data.get("result") and data["result"].get("data"):
                for row in data["result"]["data"]:
                    items.append({
                        "code": row.get("SECURITY_CODE", ""),
                        "name": row.get("SECURITY_NAME_ABBR", ""),
                        "close": self.safe_float(row.get("CLOSE_PRICE")),
                        "change_pct": self.safe_float(row.get("CHANGE_RATE")),
                        "turnover": self.safe_float(row.get("TURNOVERRATE")),
                        "net_buy": self.safe_float(row.get("NET_BUY_AMT")),
                        "buy_total": self.safe_float(row.get("BUY_AMT")),
                        "sell_total": self.safe_float(row.get("SELL_AMT")),
                        "reason": row.get("EXPLANATION", ""),
                        "seats": self._parse_seats(row),
                    })
            return items
        except Exception as e:
            print(f"[EastMoney] dragon tiger failed: {e}")
            return []

    def _parse_seats(self, row: dict) -> list[dict]:
        """解析买卖席位"""
        seats = []
        # 买入席位
        for i in range(1, 6):
            seat_name = row.get(f"BUYER{i}_NAME", "")
            buy_amt = self.safe_float(row.get(f"BUY{i}_AMT"))
            sell_amt = self.safe_float(row.get(f"SELL{i}_AMT"))
            if seat_name:
                seats.append({
                    "name": seat_name,
                    "type": "买入",
                    "buy": buy_amt,
                    "sell": sell_amt,
                    "net": buy_amt - sell_amt,
                })
        # 卖出席位
        for i in range(1, 6):
            seat_name = row.get(f"SELLER{i}_NAME", "")
            buy_amt = self.safe_float(row.get(f"BUYER{i}_AMT"))
            sell_amt = self.safe_float(row.get(f"SELL{i}_AMT"))
            if seat_name:
                seats.append({
                    "name": seat_name,
                    "type": "卖出",
                    "buy": buy_amt,
                    "sell": sell_amt,
                    "net": buy_amt - sell_amt,
                })
        return seats

    async def get_indices(self, codes: list[str] | None = None) -> list[dict]:
        """获取指数行情"""
        if codes is None:
            codes = ["1.000001", "0.399001", "0.399006", "0.000688", "1.000016"]

        # 转东方财富格式: sh000001 → 1.000001, sz399001 → 0.399001
        secids = []
        for c in codes:
            if c.startswith("sh"):
                secids.append(f"1.{c[2:]}")
            elif c.startswith("sz"):
                secids.append(f"0.{c[2:]}")
            elif c.startswith("bj"):
                secids.append(f"0.{c[2:]}")
            else:
                secids.append(c)

        params = {
            "fltt": "2",
            "np": "1",
            "fields": "f2,f3,f4,f5,f6,f7,f12,f14",
            "secids": ",".join(secids),
        }

        try:
            text = await self._request(self.INDEX_URL, params=params)
            data = json.loads(text)
            items = []
            if data.get("data") and data["data"].get("diff"):
                for row in data["data"]["diff"]:
                    market = "sh" if row.get("f12", "").startswith("0") else \
                             "sz" if row.get("f12", "").startswith("39") else "sz"
                    items.append({
                        "code": f"{market}{row.get('f12', '')}",
                        "name": row.get("f14", ""),
                        "price": self.safe_float(row.get("f2")),
                        "change": self.safe_float(row.get("f4")),
                        "change_pct": self.safe_float(row.get("f3")),
                        "volume": self.safe_int(row.get("f5")),
                        "amount": self.safe_float(row.get("f6")),
                    })
            return items
        except Exception as e:
            print(f"[EastMoney] indices failed: {e}")
            return []

    async def get_announcements(self, code: str, page: int = 1, size: int = 20) -> dict:
        """获取公司公告"""
        # 转代码格式
        market = "SH" if code.startswith(("sh", "60", "68")) else "SZ"
        raw_code = code.replace("sh", "").replace("sz", "")
        stock_code = f"{market}{raw_code}"

        params = {
            "sr": "-1",
            "page_size": str(size),
            "page_index": str(page),
            "ann_type": "A",
            "client_source": "web",
            "stock_list": stock_code,
        }

        try:
            text = await self._request(self.ANNOUNCEMENT_URL, params=params)
            data = json.loads(text)
            items = []
            total = 0
            if data.get("data") and data["data"].get("list"):
                for row in data["data"]["list"]:
                    items.append({
                        "title": row.get("title", ""),
                        "date": row.get("notice_date", "")[:10] if row.get("notice_date") else "",
                        "type": "公告",
                        "url": f"https://data.eastmoney.com/notices/detail/{raw_code}/{row.get('art_code', '')}.html",
                    })
                total = data["data"].get("total_hits", len(items))
            return {"data": items, "total": total}
        except Exception as e:
            print(f"[EastMoney] announcements failed for {code}: {e}")
            return {"data": [], "total": 0}

    async def get_stock_list(self) -> list[dict]:
        """获取全A股列表（沪深京）"""
        all_stocks = []

        # 沪深主板 + 创业板 + 科创板
        for fs in ["m:0+t:6", "m:0+t:80", "m:1+t:2"]:
            params = {
                "pn": "1",
                "pz": "6000",
                "po": "1",
                "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2",
                "invt": "2",
                "fid": "f3",
                "fs": fs,
                "fields": "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f100,f115",
            }
            try:
                text = await self._request(self.STOCK_LIST_URL, params=params)
                data = json.loads(text)
                if data.get("data") and data["data"].get("diff"):
                    for row in data["data"]["diff"]:
                        code_str = row.get("f12", "")
                        if not code_str:
                            continue
                        market = "sh" if code_str.startswith(("60", "68")) else \
                                 "sz" if code_str.startswith(("00", "30")) else "bj"
                        all_stocks.append({
                            "code": f"{market}{code_str}",
                            "name": row.get("f14", ""),
                            "market": market,
                            "sector": "综合",
                        })
            except Exception as e:
                print(f"[EastMoney] stock list failed for fs={fs}: {e}")

        # 北交所
        try:
            params["fs"] = "m:0+t:81"
            text = await self._request(self.STOCK_LIST_URL, params=params)
            data = json.loads(text)
            if data.get("data") and data["data"].get("diff"):
                for row in data["data"]["diff"]:
                    code_str = row.get("f12", "")
                    if not code_str:
                        continue
                    all_stocks.append({
                        "code": f"bj{code_str}",
                        "name": row.get("f14", ""),
                        "market": "bj",
                        "sector": "综合",
                    })
        except Exception:
            pass

        return all_stocks

    async def get_limit_up_stocks(self) -> list[dict]:
        """获取涨停股票（东方财富涨停板数据）"""
        params = {
            "pn": "1",
            "pz": "500",
            "po": "0",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:0+t:81",
            "fields": "f2,f3,f12,f14,f100",
        }
        try:
            text = await self._request(self.STOCK_LIST_URL, params=params)
            data = json.loads(text)
            stocks = []
            if data.get("data") and data["data"].get("diff"):
                for row in data["data"]["diff"]:
                    chg_pct = self.safe_float(row.get("f3"))
                    if chg_pct >= 9.8:  # 接近涨停
                        code_str = row.get("f12", "")
                        market = "sh" if code_str.startswith(("60", "68")) else \
                                 "sz" if code_str.startswith(("00", "30")) else "bj"
                        stocks.append({
                            "code": f"{market}{code_str}",
                            "name": row.get("f14", ""),
                            "change_pct": chg_pct,
                            "board_height": 1,
                            "first_time": "",
                        })
            return stocks
        except Exception as e:
            print(f"[EastMoney] limit up list failed: {e}")
            return []

    async def get_limit_up_stats(self) -> dict:
        """
        获取涨停板综合统计（含连板高度分类）
        返回: { total_limit_up, total_limit_down, limit_up_open, board_levels, up_stocks, down_stocks }
        """
        params = {
            "pn": "1",
            "pz": "5000",
            "po": "0",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:0+t:81",
            "fields": "f2,f3,f12,f14,f15,f16,f17,f20,f23,f100,f62",
        }
        try:
            text = await self._request(self.STOCK_LIST_URL, params=params)
            data = json.loads(text)
            stocks = []
            if not data.get("data") or not data["data"].get("diff"):
                return self._empty_limit_stats()

            for row in data["data"]["diff"]:
                chg_pct = self.safe_float(row.get("f3"))
                code_str = row.get("f12", "")
                if not code_str:
                    continue
                market = "sh" if code_str.startswith(("60", "68")) else \
                         "sz" if code_str.startswith(("00", "30")) else "bj"
                stocks.append({
                    "code": f"{market}{code_str}",
                    "name": row.get("f14", ""),
                    "price": self.safe_float(row.get("f2")),
                    "change_pct": chg_pct,
                    "turnover": self.safe_float(row.get("f15")),
                    "amount": self.safe_float(row.get("f23")),  # 成交额(万)
                    "total_mcap": self.safe_float(row.get("f20")),
                    "sector": self._get_industry(row.get("f100", "")),
                    "high": self.safe_float(row.get("f17")),
                    "low": self.safe_float(row.get("f16")),
                })

            if not stocks:
                return self._empty_limit_stats()

            # 移除涨跌幅异常（停牌等）
            stocks = [s for s in stocks if s["change_pct"] is not None and abs(s["change_pct"]) < 100]

            # 按市场分类检测涨停/跌停
            def is_limit_up(s):
                code = s["code"]
                cp = abs(s["change_pct"])
                if code.startswith("bj"):
                    return s["change_pct"] >= 29.8  # 北交所30%涨停
                if code.startswith(("sz", "30")):
                    return s["change_pct"] >= 19.8  # 创业板20%
                if code.startswith("sh68"):
                    return s["change_pct"] >= 19.8  # 科创板20%
                return s["change_pct"] >= 9.8  # 主板10%

            def is_limit_down(s):
                code = s["code"]
                cp = abs(s["change_pct"])
                if code.startswith("bj"):
                    return s["change_pct"] <= -29.8
                if code.startswith(("sz", "30")):
                    return s["change_pct"] <= -19.8
                if code.startswith("sh68"):
                    return s["change_pct"] <= -19.8
                return s["change_pct"] <= -9.8

            limit_up_stocks = [s for s in stocks if is_limit_up(s)]
            limit_down_stocks = [s for s in stocks if is_limit_down(s)]

            # 高开炸板：涨幅>8%但未封板，且最高价高于现价5%以上
            limit_up_open = [s for s in stocks
                if 6.0 <= s["change_pct"] < 9.5
                and s["high"] > s["price"] * 1.03
            ]

            board_levels = self._classify_limit_up_levels(limit_up_stocks)

            return {
                "total_limit_up": len(limit_up_stocks),
                "total_limit_down": len(limit_down_stocks),
                "limit_up_open": len(limit_up_open),
                "board_levels": board_levels,
                "up_stocks": limit_up_stocks[:50],
                "down_stocks": limit_down_stocks[:30],
                "update_time": "",
            }

        except Exception as e:
            print(f"[EastMoney] limit up stats failed: {e}")
            return self._empty_limit_stats()

    def _classify_limit_up_levels(self, stocks: list[dict]) -> dict:
        """按涨幅分级估算连板高度"""
        levels = {"6": 0, "5": 0, "4": 0, "3": 0, "2": 0, "1": 0}
        for s in stocks:
            cp = s["change_pct"]
            if cp >= 33:
                levels["6"] += 1
            elif cp >= 25:
                levels["5"] += 1
            elif cp >= 20:
                levels["4"] += 1
            elif cp >= 15:
                levels["3"] += 1
            elif cp >= 11:
                levels["2"] += 1
            else:
                levels["1"] += 1
        return levels

    def _get_industry(self, code: str) -> str:
        """将东方财富板块代码转为中文行业名"""
        if not code:
            return "综合"
        # 从BK代码提取行业（实际数据可能是"行业板块"名称）
        name = self.SECTOR_MAP.get(code, "")
        if name:
            return name
        # 对BK代码去除前缀
        return code.replace("BK", "板块") if code.startswith("BK") else "综合"

    def _empty_limit_stats(self) -> dict:
        return {
            "total_limit_up": 0, "total_limit_down": 0, "limit_up_open": 0,
            "board_levels": {"6": 0, "5": 0, "4": 0, "3": 0, "2": 0, "1": 0},
            "up_stocks": [], "down_stocks": [],
            "update_time": "",
        }

    async def get_money_flow_rank(self, top_n: int = 20) -> dict:
        """
        获取主力资金净流入/净流出 TOP N
        返回: { in: [{code, name, net_amount, sector, price, change_pct}],
                 out: [{code, name, net_amount, sector, price, change_pct}] }
        """
        # 拉取较大量以确保流出侧也有足够数据
        params = {
            "pn": "1",
            "pz": str(max(top_n * 3, 100)),
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f62",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:0+t:81",
            "fields": "f2,f3,f12,f14,f62,f66,f69,f78,f84,f100,f184,f185",
        }
        try:
            text = await self._request(self.STOCK_LIST_URL, params=params)
            data = json.loads(text)
            if not data.get("data") or not data["data"].get("diff"):
                return {"in": [], "out": []}

            all_flow = []
            for row in data["data"]["diff"]:
                code_str = row.get("f12", "")
                if not code_str:
                    continue
                market = "sh" if code_str.startswith(("60", "68")) else \
                         "sz" if code_str.startswith(("00", "30")) else "bj"
                net = self.safe_float(row.get("f62"))  # 主力净流入(元)
                if net is None or net == 0:
                    continue
                all_flow.append({
                    "code": f"{market}{code_str}",
                    "name": row.get("f14", ""),
                    "net_amount": net,
                    "net_amount_yi": round(net / 100000000, 2),  # 转为亿元
                    "price": self.safe_float(row.get("f2")),
                    "change_pct": self.safe_float(row.get("f3")),
                    "sector": self._get_industry(row.get("f100", "")),
                })

            # 按净流入降序
            all_flow.sort(key=lambda x: x["net_amount"] or 0, reverse=True)

            inflow = [s for s in all_flow if s["net_amount"] > 0][:top_n]
            outflow = sorted([s for s in all_flow if s["net_amount"] < 0],
                             key=lambda x: x["net_amount"])[:top_n]

            return {"in": inflow, "out": outflow}

        except Exception as e:
            print(f"[EastMoney] money flow rank failed: {e}")
            return {"in": [], "out": []}
