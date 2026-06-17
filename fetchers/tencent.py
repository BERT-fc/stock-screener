"""
腾讯财经数据爬取器
- 实时行情（批量）：http://qt.gtimg.cn/q=
- 分时数据：http://ifzq.gtimg.cn/appstock/app/minute/query
- 资金流向：http://qt.gtimg.cn/q=ff_xxx
"""
import re
from .base import BaseFetcher


class TencentFetcher(BaseFetcher):
    """腾讯财经：实时行情、分时数据、资金流向"""

    BASE_URL = "http://qt.gtimg.cn/q="
    INTRADAY_URL = "http://ifzq.gtimg.cn/appstock/app/minute/query"

    # 实时行情字段映射（腾讯接口 ~50+字段）
    # 0:名称 1:代码 3:现价 4:昨收 5:今开 6:成交量 7:外盘 8:内盘
    # 9:买一 10:买一量 ... 19:卖一 20:卖一量
    # 30:日期 31:时间 32:涨跌额 33:涨跌幅% 34:最高 35:最低
    # 36:量比 37:换手率% 38:市盈率 41:成交额 42-45:最高/最低/振幅/流通市值
    # 46:总市值 47:市净率 48:涨停价 49:跌停价

    @staticmethod
    def _code_to_qt(code: str) -> str:
        """转腾讯格式: sh600519 → sh600519"""
        return code

    @staticmethod
    def _parse_quote(raw: str) -> dict:
        """解析单只股票行情 - 新版字段映射(2026)"""
        # 格式: v_sh600519="1~贵州茅台~600519~..."
        parts = raw.split('"')
        if len(parts) < 2:
            return {}
        fields = parts[1].split("~")
        if len(fields) < 46:
            return {}

        # 已验证字段映射 (2026-06-17)
        return {
            "name": fields[1],
            "code": fields[2],
            "price": BaseFetcher.safe_float(fields[3]),
            "pre_close": BaseFetcher.safe_float(fields[4]),
            "open": BaseFetcher.safe_float(fields[5]),
            "volume": BaseFetcher.safe_int(fields[6]),          # 成交量(手)
            "change": BaseFetcher.safe_float(fields[31]),        # 涨跌额
            "change_pct": BaseFetcher.safe_float(fields[32]),    # 涨跌幅%
            "high": BaseFetcher.safe_float(fields[33]),
            "low": BaseFetcher.safe_float(fields[34]),
            # fields[35] is composite: "price/volume/amount"
            "amount": BaseFetcher.safe_float(fields[37]),        # 成交额(万元)
            "turnover": BaseFetcher.safe_float(fields[38]),      # 换手率%
            "pe": BaseFetcher.safe_float(fields[39]) if BaseFetcher.safe_float(fields[39]) > 0 else None,
            "vol_ratio": None,
            "high_52w": BaseFetcher.safe_float(fields[41]),
            "low_52w": BaseFetcher.safe_float(fields[42]),
            "amplitude": BaseFetcher.safe_float(fields[43]),     # 振幅%
            "float_mcap": BaseFetcher.safe_float(fields[44]),    # 流通市值(亿)
            "mcap": BaseFetcher.safe_float(fields[45]),          # 总市值(亿)
            "pb": BaseFetcher.safe_float(fields[46]) if BaseFetcher.safe_float(fields[46]) > 0 else None,
            "limit_up": BaseFetcher.safe_float(fields[47]),
            "limit_down": BaseFetcher.safe_float(fields[48]),
        }

    async def get_batch_quote(self, codes: list[str]) -> list[dict]:
        """批量获取实时行情 支持最多~50只/次"""
        results = []
        # 分批，每批50只
        for i in range(0, len(codes), 45):
            batch = codes[i:i + 45]
            qt_codes = ",".join(batch)
            url = f"{self.BASE_URL}{qt_codes}"
            try:
                text = await self._request(url, encoding="gbk")
                # 按换行分割，每行一只
                for line in text.strip().split("\n"):
                    if "=" in line and "~" in line:
                        data = self._parse_quote(line.strip())
                        if data and data.get("name"):
                            # 确定market并补全code前缀
                            code = data["code"]
                            market = "sh" if code.startswith("60") or code.startswith("68") else \
                                     "sz" if code.startswith("00") or code.startswith("30") else "bj"
                            data["market"] = market
                            data["code"] = f"{market}{code}"  # 补全前缀

                            # 腾讯返回的float_mcap/mcap单位可能是亿，但有时返回不准确
                            # 做一下容错：如果值为0则置None
                            if data.get("float_mcap", 0) == 0:
                                data["float_mcap"] = None
                            if data.get("mcap", 0) == 0:
                                data["mcap"] = None

                            results.append(data)
            except Exception as e:
                # 单批失败不影响其他批
                print(f"[Tencent] batch quote failed for {len(batch)} stocks: {e}")
                continue
        return results

    async def get_intraday(self, code: str) -> list[dict]:
        """获取分时数据"""
        # 腾讯分时接口
        market_code = code
        url = f"{self.INTRADAY_URL}?_var=min_data&code={market_code}"
        try:
            text = await self._request(url, encoding="gbk")
            # 返回: min_data={...}
            json_str = text.replace("min_data=", "").strip(";")
            data = __import__("json").loads(json_str)
            points = []
            if "data" in data and isinstance(data["data"], dict):
                qt_data = list(data["data"].values())[0] if data["data"] else {}
                if qt_data and "data" in qt_data and "data" in qt_data["data"]:
                    mins = qt_data["data"]["data"]
                else:
                    mins = []
                # 昨日收盘
                pre_close = qt_data.get("pre", 0)
                total_vol = 0
                for item in mins:
                    # item格式: "0930 1420.50 12500" (时间 价格 成交量)
                    parts = item.split(" ")
                    if len(parts) >= 2:
                        points.append({
                            "time": parts[0],
                            "price": self.safe_float(parts[1]),
                            "volume": self.safe_int(parts[2]) if len(parts) >= 3 else 0,
                            "avg_price": pre_close,
                        })
            return points
        except Exception as e:
            print(f"[Tencent] intraday failed for {code}: {e}")
            return []

    async def get_moneyflow(self, code: str) -> dict:
        """获取资金流向"""
        market = "sh" if code.startswith(("60", "68")) else "sz"
        raw_code = code.replace("sh", "").replace("sz", "")
        ff_code = f"ff_{market}{raw_code}"
        url = f"{self.BASE_URL}{ff_code}"
        try:
            text = await self._request(url, encoding="gbk")
            # 腾讯资金流向字段较少
            parts = text.split('"')
            if len(parts) < 2:
                return {}
            fields = parts[1].split("~")
            return {
                "main_net_inflow": self.safe_float(fields[6]) if len(fields) > 6 else None,
                "super_large_net": self.safe_float(fields[9]) if len(fields) > 9 else None,
                "large_net": self.safe_float(fields[12]) if len(fields) > 12 else None,
                "mid_net": self.safe_float(fields[15]) if len(fields) > 15 else None,
                "small_net": self.safe_float(fields[18]) if len(fields) > 18 else None,
            }
        except Exception as e:
            print(f"[Tencent] moneyflow failed for {code}: {e}")
            return {}
