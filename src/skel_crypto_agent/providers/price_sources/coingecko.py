import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional

import httpx
from loguru import logger

from .base import PriceQuote, PriceSource


@dataclass(slots=True)
class CoinEntry:
    id: str
    name: str


class CoinGeckoPriceSource(PriceSource):
    name = "coingecko"

    def __init__(self, client: httpx.AsyncClient, api_key: Optional[str] = None) -> None:
        self._client = client
        self._api_key = api_key
        self._symbol_to_entries: Dict[str, List[CoinEntry]] = {}
        self._lock = asyncio.Lock()

    async def warmup(self) -> None:
        await self._ensure_symbol_map()

    async def get_price(self, symbol: str, currency: str) -> Optional[PriceQuote]:
        quotes = await self.get_prices(symbol, currency, limit=1)
        return quotes[0] if quotes else None

    async def get_prices(self, symbol: str, currency: str, *, limit: int = 3) -> List[PriceQuote]:
        entries = await self._get_entries(symbol)
        if not entries:
            return []

        headers = self._headers
        currency_lower = currency.lower()
        selected = entries[:limit]

        market_data = await self._fetch_market_data(selected, currency_lower, headers)
        if market_data:
            quotes = []
            for entry in selected:
                payload = market_data.get(entry.id)
                if not payload:
                    continue
                price = payload.get("current_price")
                if price is None:
                    continue

                quotes.append(
                    PriceQuote(
                        symbol=symbol.upper(),
                        currency=currency.upper(),
                        price=Decimal(str(price)),
                        source=self.name,
                        name=entry.name,
                        change_1h=self._decimal_or_none(
                            payload.get("price_change_percentage_1h_in_currency")
                        ),
                        change_24h=self._decimal_or_none(
                            payload.get("price_change_percentage_24h_in_currency")
                        ),
                        change_7d=self._decimal_or_none(
                            payload.get("price_change_percentage_7d_in_currency")
                        ),
                    )
                )

            if quotes:
                return quotes

        return await self._fetch_simple_prices(selected, symbol, currency, currency_lower, headers)

    async def _fetch_simple_prices(
        self,
        entries: List[CoinEntry],
        symbol: str,
        currency: str,
        currency_lower: str,
        headers: Dict[str, str],
    ) -> List[PriceQuote]:
        quotes: List[PriceQuote] = []
        for entry in entries:
            params = {"ids": entry.id, "vs_currencies": currency_lower}
            try:
                response = await self._client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning(
                    "CoinGecko price fetch failed for {} ({}): {}",
                    entry.id,
                    symbol.upper(),
                    exc,
                )
                continue

            data = response.json()
            value = data.get(entry.id, {}).get(currency_lower)
            if value is None:
                continue

            quotes.append(
                PriceQuote(
                    symbol=symbol.upper(),
                    currency=currency.upper(),
                    price=Decimal(str(value)),
                    source=self.name,
                    name=entry.name,
                )
            )
        return quotes

    async def _fetch_market_data(
        self,
        entries: List[CoinEntry],
        currency_lower: str,
        headers: Dict[str, str],
    ) -> Dict[str, dict]:
        ids = ",".join(entry.id for entry in entries)
        if not ids:
            return {}

        params = {
            "vs_currency": currency_lower,
            "ids": ids,
            "order": "market_cap_desc",
            "per_page": len(entries),
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "1h,24h,7d",
        }
        try:
            response = await self._client.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.debug(
                "CoinGecko market data fetch failed for %s: %s",
                ids,
                exc,
            )
            return {}

        data = response.json()
        if not isinstance(data, list):
            return {}
        return {item.get("id"): item for item in data if isinstance(item, dict) and item.get("id")}

    def _decimal_or_none(self, value: Optional[float]) -> Optional[Decimal]:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (ValueError, TypeError):
            return None

    @property
    def _headers(self) -> Dict[str, str]:
        if not self._api_key:
            return {}
        return {"x-cg-demo-api-key": self._api_key}

    async def get_coin_id(self, symbol: str) -> Optional[str]:
        entries = await self._get_entries(symbol)
        return entries[0].id if entries else None

    async def _get_entries(self, symbol: str) -> List[CoinEntry]:
        symbol_l = symbol.lower()

        entries = await self._search_symbol(symbol_l)
        if entries:
            self._symbol_to_entries[symbol_l] = entries
            return entries

        await self._ensure_symbol_map()
        return self._symbol_to_entries.get(symbol_l, [])

    async def _ensure_symbol_map(self) -> None:
        if self._symbol_to_entries:
            return
        async with self._lock:
            if self._symbol_to_entries:
                return
            try:
                response = await self._client.get(
                    "https://api.coingecko.com/api/v3/coins/list",
                    params={"include_platform": "false"},
                    headers=self._headers,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("CoinGecko coins list failed: {}", exc)
                return

            coins = response.json()
            for item in coins:
                sym = (item.get("symbol") or "").lower()
                coin_id = item.get("id")
                name = item.get("name") or coin_id
                if not sym or not coin_id:
                    continue
                self._symbol_to_entries.setdefault(sym, []).append(CoinEntry(id=coin_id, name=name))

    async def _search_symbol(self, symbol: str) -> List[CoinEntry]:
        try:
            response = await self._client.get(
                "https://api.coingecko.com/api/v3/search",
                params={"query": symbol},
                headers=self._headers,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("CoinGecko search failed for {}: {}", symbol, exc)
            return []

        payload = response.json().get("coins", [])
        matched = [
            coin for coin in payload
            if (coin.get("symbol") or "").lower() == symbol
        ]
        if not matched:
            return []

        def sort_key(coin: dict) -> tuple[int, str]:
            rank = coin.get("market_cap_rank") or 10**9
            return (rank, coin.get("name", ""))

        matched.sort(key=sort_key)
        entries: List[CoinEntry] = []
        for coin in matched:
            coin_id = coin.get("id")
            name = coin.get("name") or coin_id
            if coin_id:
                entries.append(CoinEntry(id=coin_id, name=name))
        return entries
