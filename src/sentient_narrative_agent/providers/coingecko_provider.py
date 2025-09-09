import asyncio
import time
from typing import List, Optional

import httpx
from loguru import logger

from .base_crypto_provider import BaseCryptoProvider
from .base_crypto_schemas import Coin, TrendingCoin, CoinDetails


class CoinGeckoProvider(BaseCryptoProvider):
    def __init__(self, api_key: str):
        self._base_url = "https://api.coingecko.com/api/v3"
        self._api_key = api_key
        self._coin_list_cache: Optional[List[Coin]] = None
        self._trending_cache: tuple[float, List[TrendingCoin]] | None = None
        self._last_coin_list_raw: Optional[list[dict]] = None
        self._last_trending_raw: Optional[dict] = None
        self._last_coin_details_raw: dict[str, dict] = {}

    async def _initialize_coin_list_cache(self) -> None:
        if self._coin_list_cache is None:
            logger.info("Initializing CoinGecko coin list cache…")
            self._coin_list_cache = await self.get_coin_list()
            logger.info(f"Coin list cache initialized with {len(self._coin_list_cache)} coins.")

    async def _get(self, path: str, params: Optional[dict] = None, *, timeout: float = 15.0, max_retries: int = 2) -> httpx.Response:
        url = f"{self._base_url}{path}"
        q = dict(params or {})
        q.setdefault("x_cg_demo_api_key", self._api_key)

        backoff = 1.0
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(url, params=q)
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", backoff))
                    logger.warning(f"Rate limited by CoinGecko (429). Retrying in {retry_after:.1f}s…")
                    await asyncio.sleep(retry_after)
                    backoff *= 2
                    continue
                resp.raise_for_status()
                return resp
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt >= max_retries:
                    logger.error(f"HTTP error contacting CoinGecko: {e}")
                    raise
                logger.warning(f"HTTP error contacting CoinGecko (attempt {attempt+1}/{max_retries}). Retrying in {backoff:.1f}s…")
                await asyncio.sleep(backoff)
                backoff *= 2

        raise RuntimeError("Failed to fetch from CoinGecko after retries")

    async def find_coins_by_symbol(self, symbol: str) -> List[Coin]:
        await self._initialize_coin_list_cache()
        symbol_lower = symbol.lower()
        return [coin for coin in self._coin_list_cache if coin.symbol.lower() == symbol_lower]

    async def get_coin_list(self) -> List[Coin]:
        resp = await self._get("/coins/list")
        raw = resp.json()
        self._last_coin_list_raw = raw
        return [Coin(**item) for item in raw]

    async def get_trending(self) -> List[TrendingCoin]:
        now = time.time()
        if self._trending_cache and (now - self._trending_cache[0] < 60):
            return self._trending_cache[1]

        resp = await self._get("/search/trending")
        raw = resp.json()
        data = [TrendingCoin(**item) for item in raw.get("coins", [])]
        self._last_trending_raw = raw
        self._trending_cache = (now, data)
        return data

    async def get_coin_details(self, coin_id: str) -> CoinDetails:
        logger.info(f"Fetching full details for coin ID: {coin_id}")
        params = {
            "localization": "false",
            "tickers": "false",
            "community_data": "false",
            "developer_data": "false",
            "sparkline": "false",
        }
        resp = await self._get(f"/coins/{coin_id}", params=params)
        raw = resp.json()
        self._last_coin_details_raw[coin_id] = raw
        return CoinDetails(**raw)

    def get_last_coin_list_raw(self) -> Optional[list[dict]]:
        return self._last_coin_list_raw

    def get_last_trending_raw(self) -> Optional[dict]:
        return self._last_trending_raw

    def get_last_coin_details_raw(self, coin_id: str) -> Optional[dict]:
        return self._last_coin_details_raw.get(coin_id)
