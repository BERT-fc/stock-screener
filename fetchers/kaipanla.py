"""
开盘啦数据爬取器
- 市场情绪、涨跌停统计、连板分析、大幅回撤、炸板监控
"""
import json
from .base import BaseFetcher


class KaipanlaFetcher(BaseFetcher):
    """开盘啦：市场情绪、涨跌停、回撤监控"""

    # 开盘啦API（实际使用东方财富数据模拟，因为开盘啦接口限制较多）
    # 保留框架，实际能用时直接替换

    async def get_mood(self) -> dict:
        """获取市场情绪数据"""
        # 基于东方财富数据汇总
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": "6000",
            "po": "0",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:0+t:81",
            "fields": "f3,f12,f14",
        }

        try:
            text = await self._request(url, params=params)
            data = json.loads(text)

            up_count = down_count = flat_count = limit_up = limit_down = 0

            if data.get("data") and data["data"].get("diff"):
                for row in data["data"]["diff"]:
                    chg = self.safe_float(row.get("f3"))
                    if chg > 9.8:
                        limit_up += 1
                        up_count += 1
                    elif chg < -9.8:
                        limit_down += 1
                        down_count += 1
                    elif chg > 0:
                        up_count += 1
                    elif chg < 0:
                        down_count += 1
                    else:
                        flat_count += 1

            total = up_count + down_count + flat_count
            # 情绪指数: 0-100，基于涨跌比计算
            mood_index = round((up_count / max(total, 1)) * 100, 1) if total > 0 else 50.0

            return {
                "up_count": up_count,
                "down_count": down_count,
                "flat_count": flat_count,
                "limit_up": limit_up,
                "limit_down": limit_down,
                "limit_up_open": 0,  # 炸板数暂无法精确统计
                "mood_index": mood_index,
            }
        except Exception as e:
            print(f"[Kaipanla] mood failed: {e}")
            return {
                "up_count": 0, "down_count": 0, "flat_count": 0,
                "limit_up": 0, "limit_down": 0, "limit_up_open": 0,
                "mood_index": 50.0,
            }

    async def get_drawdown_stocks(self) -> list[dict]:
        """获取大幅回撤股票"""
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1",
            "pz": "200",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2",
            "fields": "f2,f3,f4,f12,f14,f15,f16,f17",
        }

        try:
            text = await self._request(url, params=params)
            data = json.loads(text)
            drawdowns = []
            if data.get("data") and data["data"].get("diff"):
                for row in data["data"]["diff"]:
                    code_str = row.get("f12", "")
                    chg = self.safe_float(row.get("f3"))
                    high = self.safe_float(row.get("f15"))
                    low = self.safe_float(row.get("f16"))
                    price = self.safe_float(row.get("f2"))

                    if chg >= -5:
                        continue  # 只要跌幅超过5%的

                    market = "sh" if code_str.startswith(("60", "68")) else \
                             "sz" if code_str.startswith(("00", "30")) else "bj"

                    # 盘中回撤: (最高-当前)/最高 * 100
                    drawdown = ((high - price) / high * 100) if high > 0 else 0

                    if drawdown >= 5:
                        drawdowns.append({
                            "code": f"{market}{code_str}",
                            "name": row.get("f14", ""),
                            "from_high_pct": 0,
                            "current_chg": chg,
                            "drawdown_pct": round(drawdown, 2),
                        })
            return drawdowns
        except Exception as e:
            print(f"[Kaipanla] drawdown failed: {e}")
            return []
