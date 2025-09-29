from decimal import Decimal
from typing import Optional

import httpx
from loguru import logger

from .base import PriceQuote, PriceSource


class CoinMarketCapPriceSource(PriceSource):
    name = "coinmarketcap"

    def __init__(self, client: httpx.AsyncClient, api_key: Optional[str] = None) -> None:
        self._client = client
        self._api_key = api_key

    async def get_price(self, symbol: str, currency: str) -> Optional[PriceQuote]:
        if not self._api_key:
            return None

        params = {
            "symbol": symbol.upper(),
            "convert": currency.upper(),
        }
        headers = {"X-CMC_PRO_API_KEY": self._api_key}
        try:
            response = await self._client.get(
                "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("CoinMarketCap price fetch failed: {}", exc)
            return None

        data = response.json().get("data", {})
        symbol_data = data.get(symbol.upper())
        if not symbol_data:
            return None
        info = symbol_data[0] if isinstance(symbol_data, list) else symbol_data
        quote = info.get("quote", {}).get(currency.upper())
        if not quote:
            return None
        price = quote.get("price")
        if price is None:
            return None
        name = info.get("name") or symbol.upper()
        return PriceQuote(
            symbol=symbol.upper(),
            currency=currency.upper(),
            price=Decimal(str(price)),
            source=self.name,
            name=name,
        )
