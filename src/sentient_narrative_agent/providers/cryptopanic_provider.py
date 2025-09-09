import asyncio
from typing import Optional, List, Dict, Any

import httpx
from loguru import logger

from .base_news_provider import BaseNewsProvider
from .base_news_schemas import NewsItem


class CryptoPanicNewsProvider(BaseNewsProvider):
    def __init__(self, api_key: str):
        self._base_url = "https://cryptopanic.com/api/developer/v2/posts/"
        self._api_key = api_key
        self._cache: Dict[str, tuple[float, List[NewsItem], Dict[str, Any]]] = {}
        self._cooldown_until: float = 0.0
        self._last_status: str = "init"

    def _cache_key(self, symbol: str, limit: int) -> str:
        return f"{symbol.upper()}|{limit}"

    async def _get(self, params: Dict[str, Any], *, timeout: float = 15.0, max_retries: int = 2) -> Optional[Dict[str, Any]]:
        if self._cooldown_until:
            import time
            if time.time() < self._cooldown_until:
                self._last_status = "cooldown"
                return None
        q = dict(params)
        q.setdefault("auth_token", self._api_key)
        q.setdefault("public", "true")
        q.setdefault("regions", "en")

        backoff = 1.0
        from urllib.parse import urlparse
        ep_path = urlparse(self._base_url).path or "/api/developer/v2/posts/"
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(self._base_url, params=q)
                logger.info(f"GET {ep_path} -> {resp.status_code}")
                if resp.status_code in (401,):
                    logger.warning("CryptoPanic unauthorized")
                    self._last_status = "unauthorized"
                    return None
                if resp.status_code in (403, 429):
                    retry_after = float(resp.headers.get("Retry-After", backoff))
                    self._last_status = "rate_limited"
                    await asyncio.sleep(retry_after)
                    import time
                    if attempt >= max_retries:
                        self._cooldown_until = time.time() + 60
                        self._last_status = "cooldown"
                        return None
                    backoff *= 2
                    continue
                resp.raise_for_status()
                self._last_status = "ok"
                return resp.json()
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt >= max_retries:
                    self._last_status = "error"
                    return None
                await asyncio.sleep(backoff)
                backoff *= 2
        return None

    async def get_news(self, symbol: str, name: str, limit: int = 10) -> List[NewsItem]:
        import time
        key = self._cache_key(symbol, limit)
        if key in self._cache and time.time() - self._cache[key][0] < 600:
            return self._cache[key][1]

        params_primary = {
            "currencies": symbol.upper(),
            "kind": "news",
        }
        raw = await self._get(params_primary)
        if (not raw or not (raw.get("results") or [])):
            params_fallback = {
                "currencies": symbol.upper(),
                "kind": "news",
                "filter": "rising",
            }
            raw = await self._get(params_fallback)
        items: List[NewsItem] = []
        if raw and isinstance(raw, dict):
            results = raw.get("results") or []
            for r in results[:limit]:
                currencies: List[str] = []
                for inst in r.get("instruments") or []:
                    code = inst.get("code")
                    if code:
                        currencies.append(str(code))
                if not currencies:
                    for c in r.get("currencies") or []:
                        code = c.get("code")
                        if code:
                            currencies.append(str(code))
                rid = r.get("id")
                slug = r.get("slug")
                url_val = None
                if rid is not None and slug:
                    url_val = f"https://cryptopanic.com/news/{rid}/{slug}"
                elif rid is not None:
                    url_val = f"https://cryptopanic.com/news/{rid}"
                elif slug:
                    url_val = f"https://cryptopanic.com/news/{slug}"
                else:
                    url_val = "https://cryptopanic.com"

                items.append(NewsItem(
                    id=str(r.get("id")) if r.get("id") is not None else None,
                    title=str(r.get("title")),
                    url=str(url_val),
                    source=(r.get("source") or {}).get("domain") if isinstance(r.get("source"), dict) else None,
                    published_at=str(r.get("published_at")) if r.get("published_at") else None,
                    currencies=currencies,
                    raw=r,
                ))

        import time
        if raw is None and not items:
            if key in self._cache and (time.time() - self._cache[key][0] < 600):
                return self._cache[key][1]
        self._cache[key] = (time.time(), items, raw if isinstance(raw, dict) else (self._cache.get(key, (0, [], {}))[2]))
        return items

    def get_last_raw(self, symbol: str, limit: int = 10) -> Optional[Dict[str, Any]]:
        key = self._cache_key(symbol, limit)
        if key in self._cache:
            return self._cache[key][2]
        return None

    def get_last_status(self) -> str:
        return self._last_status

    async def get_bull_bear_counts(self, symbol: str) -> Dict[str, int]:
        """Fetch counts of bullish vs bearish posts for a symbol using Developer API.

        Returns a dict like {"bullish": N, "bearish": M}. Uses kind=news and public=true.
        """
        counts = {"bullish": 0, "bearish": 0}
        for flt in ("bullish", "bearish"):
            params = {
                "currencies": symbol.upper(),
                "kind": "news",
                "filter": flt,
            }
            raw = await self._get(params)
            if raw and isinstance(raw, dict):
                results = raw.get("results") or []
                counts[flt] = len(results)
        return counts
