from decimal import Decimal
from typing import Optional

import httpx
from loguru import logger

from .base import PriceQuote, PriceSource


class BybitPriceSource(PriceSource):
    name = "bybit"

    _QUOTE_MAP = {
        "USD": "USDT",
        "USDT": "USDT",
        "USDC": "USDC",
    }

    _ENDPOINTS = (
        "https://api.bytick.com/v5/market/tickers",
        "https://api.bybit.com/v5/market/tickers",
    )

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get_price(self, symbol: str, currency: str) -> Optional[PriceQuote]:
        base = symbol.upper()
        quote = currency.upper()
        pair_quote = self._QUOTE_MAP.get(quote, quote)
        pair = f"{base}{pair_quote}"

        params = {"category": "spot", "symbol": pair}
        payload = None
        last_error: Optional[Exception] = None
        for endpoint in self._ENDPOINTS:
            try:
                response = await self._client.get(endpoint, params=params)
                response.raise_for_status()
                payload = response.json()
                break
            except httpx.HTTPError as exc:
                last_error = exc
        if not payload:
            if last_error is not None:
                logger.debug("Bybit request failed for {}: {}", pair, last_error)
            return None

        data = payload.get("result", {})
        list_data = data.get("list") or []
        if not list_data:
            logger.debug("Bybit returned empty result for {}: {}", pair, payload)
            return None
        ticker = list_data[0]
        price_str = ticker.get("lastPrice")
        if price_str is None:
            logger.debug("Bybit response missing lastPrice for {}: {}", pair, ticker)
            return None
        price = Decimal(str(price_str))

        if quote == "USD" and pair_quote != "USD":
            quote = "USD"
        else:
            quote = pair_quote

        return PriceQuote(
            symbol=base,
            currency=quote,
            price=price,
            source=self.name,
            name=base,
        )
