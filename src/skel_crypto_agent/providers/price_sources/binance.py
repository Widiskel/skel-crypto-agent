from decimal import Decimal
from typing import Optional

import httpx
from loguru import logger

from .base import PriceQuote, PriceSource


class BinancePriceSource(PriceSource):
    name = "binance"

    _QUOTE_MAP = {
        "USD": "USDT",
        "USDT": "USDT",
        "USDC": "USDC",
        "BUSD": "BUSD",
        "IDR": "BIDR",
        "EUR": "EUR",
        "GBP": "GBP",
    }

    _ENDPOINTS = (
        "https://api.binance.com/api/v3/ticker/price",
        "https://data-api.binance.vision/api/v3/ticker/price",
    )

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get_price(self, symbol: str, currency: str) -> Optional[PriceQuote]:
        base = symbol.upper()
        quote = currency.upper()
        pair_quote = self._QUOTE_MAP.get(quote, quote)
        pair_primary = f"{base}{pair_quote}"
        pair_secondary = f"{base}{currency.upper()}" if pair_quote != currency.upper() else None

        for candidate in filter(None, [pair_primary, pair_secondary]):
            params = {"symbol": candidate}
            last_error: Optional[Exception] = None
            for endpoint in self._ENDPOINTS:
                try:
                    response = await self._client.get(endpoint, params=params)
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    last_error = exc
                    continue

                data = response.json()
                price_str = data.get("price")
                if price_str is None:
                    logger.debug(
                        "Binance returned unexpected payload for {} via {}: {}",
                        candidate,
                        endpoint,
                        data,
                    )
                    continue

                price = Decimal(str(price_str))
                return PriceQuote(
                    symbol=base,
                    currency=candidate[len(base):],
                    price=price,
                    source=self.name,
                    name=base,
                )

            if last_error is not None:
                logger.debug("Binance request failed for {}: {}", candidate, last_error)

        return None
