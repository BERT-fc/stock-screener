"""
内存TTL缓存管理器
"""
import time
import asyncio
from typing import Any, Optional


class CacheManager:
    """简单的内存TTL缓存"""

    def __init__(self):
        self._store: dict[str, tuple[Any, float]] = {}  # (value, expire_at)
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存，过期返回None"""
        async with self._lock:
            if key not in self._store:
                return None
            value, expire_at = self._store[key]
            if time.time() > expire_at:
                del self._store[key]
                return None
            return value

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """设置缓存"""
        async with self._lock:
            self._store[key] = (value, time.time() + ttl)

    async def delete(self, key: str) -> None:
        """删除缓存"""
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self, prefix: str = "") -> None:
        """清除指定前缀的缓存"""
        async with self._lock:
            if prefix:
                keys = [k for k in self._store if k.startswith(prefix)]
                for k in keys:
                    del self._store[k]
            else:
                self._store.clear()

    async def stats(self) -> dict:
        """缓存统计"""
        async with self._lock:
            total = len(self._store)
            active = sum(1 for _, (_, exp) in self._store.items() if time.time() <= exp)
            return {"total": total, "active": active}


# 全局单例
cache = CacheManager()
