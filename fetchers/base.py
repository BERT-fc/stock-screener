"""
数据爬取基类 — 统一请求、重试、编码处理
"""
import random
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import httpx
from config import HTTP_TIMEOUT, MAX_RETRIES, RETRY_DELAY, USER_AGENTS


class BaseFetcher:
    """HTTP请求基类"""

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    def _random_ua(self) -> str:
        return random.choice(USER_AGENTS)

    def _headers(self, referer: str = "") -> dict:
        h = {
            "User-Agent": self._random_ua(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }
        if referer:
            h["Referer"] = referer
        return h

    async def _request(
        self,
        url: str,
        timeout: int = HTTP_TIMEOUT,
        encoding: str | None = None,
        referer: str = "",
        params: dict | None = None,
    ) -> str:
        """
        带重试的HTTP GET请求
        encoding: 强制编码（如 'gbk'），None则自动
        """
        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = await self.client.get(
                    url,
                    headers=self._headers(referer),
                    params=params,
                    timeout=timeout,
                    follow_redirects=True,
                )
                # 编码处理
                if encoding:
                    resp.encoding = encoding
                elif resp.encoding and resp.encoding.lower() in ("iso-8859-1", "latin-1"):
                    # 腾讯接口常见，尝试GBK
                    resp.encoding = "gbk"

                resp.raise_for_status()
                return resp.text

            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code in (403, 429):
                    # IP可能被限，换UA等一等
                    await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
                    continue
                raise
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY * (2 ** attempt))
                    continue
                raise

        raise last_error  # type: ignore

    async def _request_json(
        self,
        url: str,
        timeout: int = HTTP_TIMEOUT,
        encoding: str | None = None,
        referer: str = "",
        params: dict | None = None,
    ) -> dict | list:
        """请求并解析JSON"""
        text = await self._request(url, timeout, encoding, referer, params)
        return __import__("json").loads(text)

    def _parse_gbk_text(self, text: str) -> str:
        """解析腾讯gbk编码的响应（备用）"""
        return text

    @staticmethod
    def safe_float(val, default=0.0) -> float:
        try:
            return float(val) if val and val != "-" else default
        except (ValueError, TypeError):
            return default

    @staticmethod
    def safe_int(val, default=0) -> int:
        try:
            return int(val) if val and val != "-" else default
        except (ValueError, TypeError):
            return default
