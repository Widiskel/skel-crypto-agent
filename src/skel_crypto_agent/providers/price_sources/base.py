from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, List


@dataclass(slots=True)
class PriceQuote:
    symbol: str
    currency: str
    price: Decimal
    source: str
    name: Optional[str] = None
    change_1h: Optional[Decimal] = None
    change_4h: Optional[Decimal] = None
    change_24h: Optional[Decimal] = None
    change_7d: Optional[Decimal] = None


class PriceSource(ABC):
    name: str

    @abstractmethod
    async def get_price(self, symbol: str, currency: str) -> Optional[PriceQuote]:
        """Return a price quote or None if unavailable."""

    async def get_prices(self, symbol: str, currency: str, *, limit: int = 3) -> List[PriceQuote]:
        quote = await self.get_price(symbol, currency)
        return [quote] if quote else []

    async def warmup(self) -> None:
        """Allow sources to pre-load data if desired."""
        return None
