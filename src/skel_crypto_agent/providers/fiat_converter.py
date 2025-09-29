from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict

import httpx
from loguru import logger


class FiatConversionError(RuntimeError):
    """Raised when fiat conversion cannot be completed."""


@dataclass(slots=True)
class _CachedRates:
    values: Dict[str, Decimal]
    expires_at: float


class FiatConverter:
    """Utility for converting between fiat currencies using USD as the base."""

    _STABLECOIN_EQUIVALENTS = {
        "USD": Decimal("1"),
        "USDT": Decimal("1"),
        "USDC": Decimal("1"),
        "BUSD": Decimal("1"),
    }

    def __init__(self, client: httpx.AsyncClient, *, ttl_seconds: int = 300) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._cache: _CachedRates | None = None
        self._lock = asyncio.Lock()

    async def usd_to(self, currency: str) -> Decimal:
        """Return the amount of the target currency per 1 USD."""
        return await self._get_rate(currency.upper())

    async def convert(self, base_currency: str, target_currency: str) -> Decimal:
        """Return the conversion rate for 1 unit of base_currency to target_currency."""
        base_u = base_currency.upper()
        target_u = target_currency.upper()

        if base_u == target_u:
            return Decimal("1")

        target_rate = await self._get_rate(target_u)
        base_rate = await self._get_rate(base_u)

        return target_rate / base_rate

    async def has_rate(self, currency: str) -> bool:
        currency_u = currency.upper()
        if currency_u in self._STABLECOIN_EQUIVALENTS:
            return True
        rates = await self._ensure_rates()
        return currency_u in rates

    async def is_supported_currency(self, currency: str) -> bool:
        try:
            await self._get_rate(currency.upper())
            return True
        except FiatConversionError:
            return False

    async def _get_rate(self, currency_u: str) -> Decimal:
        direct = self._STABLECOIN_EQUIVALENTS.get(currency_u)
        if direct is not None:
            return direct

        rates = await self._ensure_rates()
        rate = rates.get(currency_u)
        if rate is None:
            logger.debug("Fiat conversion missing rate for USD -> {}", currency_u)
            raise FiatConversionError(f"No USD -> {currency_u} rate available")
        return rate

    async def _ensure_rates(self) -> Dict[str, Decimal]:
        cached = self._cache
        now = time.time()
        if cached and cached.expires_at > now:
            return cached.values

        async with self._lock:
            cached = self._cache
            now = time.time()
            if cached and cached.expires_at > now:
                return cached.values

            try:
                response = await self._client.get(
                    "https://open.er-api.com/v6/latest/USD",
                    timeout=httpx.Timeout(5.0, connect=3.0),
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning("Fiat conversion fetch failed for USD rates: {}", exc)
                raise FiatConversionError("Failed to fetch fiat conversion rates") from exc

            payload = response.json()
            if payload.get("result") != "success":
                logger.warning(
                    "Fiat conversion API returned error for USD rates: {}",
                    payload,
                )
                raise FiatConversionError("Conversion service error")

            rates_raw = payload.get("rates", {}) or {}
            decimal_rates = {code: Decimal(str(value)) for code, value in rates_raw.items()}
            self._cache = _CachedRates(
                values=decimal_rates,
                expires_at=time.time() + self._ttl,
            )

            return self._cache.values
