from decimal import Decimal
from typing import Awaitable, Callable, Optional

import httpx
from loguru import logger

from .base import PriceQuote, PriceSource


Resolver = Callable[[str], Awaitable[Optional[str]]]


class DefiLlamaPriceSource(PriceSource):
    name = "defillama"

    def __init__(self, client: httpx.AsyncClient, resolver: Resolver) -> None:
        self._client = client
        self._resolver = resolver

    async def get_price(self, symbol: str, currency: str) -> Optional[PriceQuote]:
        if currency.upper() not in {"USD", "USDT"}:
            return None

        coin_id = await self._resolver(symbol)
        if not coin_id:
            return None

        identifier = f"coingecko:{coin_id}"
        try:
            response = await self._client.get(
                f"https://coins.llama.fi/prices/current/{identifier}",
                params={"searchWidth": "4"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.debug("DefiLlama request failed: {}", exc)
            return None

        data = response.json().get("coins", {})
        info = data.get(identifier)
        if not info:
            return None
        price = info.get("price")
        if price is None:
            return None

        return PriceQuote(
            symbol=symbol.upper(),
            currency="USD",
            price=Decimal(str(price)),
            source=self.name,
        )
