from __future__ import annotations

import asyncio
from collections import Counter
from decimal import Decimal
from typing import List, Optional

import httpx
from loguru import logger

from .fiat_converter import FiatConversionError, FiatConverter
from .price_sources.base import PriceQuote, PriceSource
from .price_sources.binance import BinancePriceSource
from .price_sources.bybit import BybitPriceSource
from .price_sources.coingecko import CoinGeckoPriceSource
from .price_sources.coinmarketcap import CoinMarketCapPriceSource
from .price_sources.defillama import DefiLlamaPriceSource


class PriceService:
    def __init__(self, *, coingecko_api_key: Optional[str], coinmarketcap_api_key: Optional[str]) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
        self._coingecko = CoinGeckoPriceSource(self._client, api_key=coingecko_api_key)
        self._sources: List[PriceSource] = [
            self._coingecko,
            BinancePriceSource(self._client),
            BybitPriceSource(self._client),
            CoinMarketCapPriceSource(self._client, api_key=coinmarketcap_api_key),
            DefiLlamaPriceSource(self._client, resolver=self._coingecko.get_coin_id),
        ]
        self._warmup_task: Optional[asyncio.Task[None]] = None
        self._fiat_converter = FiatConverter(self._client)

    async def start(self) -> None:
        async def _warm():
            for source in self._sources:
                try:
                    await source.warmup()
                except Exception as exc:
                    logger.debug("Price source warmup {} failed: {}", source.name, exc)

        if self._warmup_task is None:
            self._warmup_task = asyncio.create_task(_warm())

    async def close(self) -> None:
        await self._client.aclose()

    async def get_price(self, symbol: str, currency: str) -> Optional[PriceQuote]:
        quotes = await self.get_prices(symbol, currency, limit=1)
        return quotes[0] if quotes else None

    async def get_prices(self, symbol: str, currency: str, *, limit: int = 3) -> List[PriceQuote]:
        symbol_u = symbol.upper()
        currency_u = currency.upper()

        if self._warmup_task and not self._warmup_task.done():
            pass

        logger.debug(
            "Price lookup requested for {}/{} (limit={})",
            symbol_u,
            currency_u,
            limit,
        )

        fiat_quote = await self._direct_fiat_quote(symbol_u, currency_u)
        if fiat_quote:
            logger.info(
                "Fiat conversion {} -> {} rate accepted: {}",
                symbol_u,
                currency_u,
                self._format_decimal(fiat_quote.price),
            )
            return [fiat_quote]

        fetch_currency = "USD"

        results: List[PriceQuote] = []
        seen: set[tuple[str, str, str]] = set()

        fetch_tasks = [
            asyncio.create_task(
                self._fetch_from_source(source, symbol_u, fetch_currency, limit)
            )
            for source in self._sources
        ]

        fetch_results = await asyncio.gather(*fetch_tasks)

        for source, quotes in fetch_results:
            for quote in quotes:
                if not quote:
                    continue
                normalized = self._normalize_quote(quote, expected_currency=fetch_currency)
                if not normalized:
                    logger.debug(
                        "Discarded quote from {} due to currency mismatch: {}",
                        source.name,
                        quote,
                    )
                    continue
                key = (normalized.source, normalized.symbol, normalized.name or normalized.symbol)
                if key in seen:
                    logger.debug(
                        "Skipping duplicate quote from {} for {}",
                        normalized.source,
                        normalized.symbol,
                    )
                    continue
                seen.add(key)
                results.append(normalized)
                logger.info(
                    "Source {} quote accepted: 1 {} ({}) = {} {}",
                    normalized.source,
                    normalized.symbol,
                    (normalized.name or normalized.symbol),
                    self._format_decimal(normalized.price),
                    normalized.currency,
                )

        filtered = self._apply_consensus(results, limit)
        if not filtered:
            return []

        if currency_u != fetch_currency:
            converted = await self._convert_quotes(filtered, target_currency=currency_u)
            return converted[:limit]

        return filtered[:limit]

    def _normalize_quote(self, quote: PriceQuote, *, expected_currency: str) -> Optional[PriceQuote]:
        if quote.currency == expected_currency:
            return quote

        stablecoins = {"USDT", "USDC", "BUSD"}
        if expected_currency == "USD" and quote.currency in stablecoins:
            return PriceQuote(
                symbol=quote.symbol,
                currency="USD",
                price=quote.price,
                source=quote.source,
                name=quote.name,
            )

        if expected_currency in stablecoins and quote.currency == "USD":
            return PriceQuote(
                symbol=quote.symbol,
                currency=expected_currency,
                price=quote.price,
                source=quote.source,
                name=quote.name,
            )

        return None

    def _apply_consensus(self, quotes: List[PriceQuote], limit: int) -> List[PriceQuote]:
        if len(quotes) <= 1:
            return quotes

        def consensus_key(quote: PriceQuote) -> str:
            name = (quote.name or quote.symbol).strip().lower()
            return f"{quote.symbol}:{name}" if name else quote.symbol

        counts = Counter(consensus_key(q) for q in quotes)
        key, count = counts.most_common(1)[0]

        if count <= 1:
            baseline = quotes
        else:
            majority_quotes = [q for q in quotes if consensus_key(q) == key]
            median = self._median_price(majority_quotes)

            lower_ratio = Decimal("0.4")
            upper_ratio = Decimal("2.5")
            baseline: List[PriceQuote] = []
            removed = 0
            for quote in quotes:
                if consensus_key(quote) == key:
                    baseline.append(quote)
                    continue

                if median == 0:
                    baseline.append(quote)
                    continue

                ratio = quote.price / median
                if lower_ratio <= ratio <= upper_ratio:
                    baseline.append(quote)
                else:
                    removed += 1

            if removed:
                logger.debug(
                    "Consensus filtering removed {} quotes for {}; keeping {}",
                    removed,
                    quotes[0].symbol,
                    majority_quotes[0].name or majority_quotes[0].symbol,
                )

        filtered = self._filter_price_outliers(baseline)
        return filtered[:limit]

    def _filter_price_outliers(self, quotes: List[PriceQuote]) -> List[PriceQuote]:
        if len(quotes) <= 1:
            return quotes

        prices = sorted(q.price for q in quotes)
        mid = len(prices) // 2
        if len(prices) % 2:
            median = prices[mid]
        else:
            median = (prices[mid - 1] + prices[mid]) / Decimal(2)

        if median == 0:
            return quotes

        lower_ratio = Decimal("0.4")
        upper_ratio = Decimal("2.5")
        kept: List[PriceQuote] = []
        for quote in quotes:
            ratio = quote.price / median
            if lower_ratio <= ratio <= upper_ratio:
                kept.append(quote)

        if kept and len(kept) < len(quotes):
            logger.debug(
                "Price outlier filter removed {} quotes for {}",
                len(quotes) - len(kept),
                quotes[0].symbol,
            )
            return kept

        return quotes

    def _median_price(self, quotes: List[PriceQuote]) -> Decimal:
        prices = sorted(q.price for q in quotes)
        mid = len(prices) // 2
        if len(prices) % 2:
            return prices[mid]
        return (prices[mid - 1] + prices[mid]) / Decimal(2)

    @staticmethod
    def _format_decimal(value: Decimal) -> str:
        return format(value, ",f")

    async def _convert_quotes(self, quotes: List[PriceQuote], *, target_currency: str) -> List[PriceQuote]:
        try:
            rate = await self._fiat_converter.usd_to(target_currency)
        except FiatConversionError as exc:
            logger.warning(
                "Fiat conversion failed for USD -> {}: {}. Returning USD prices.",
                target_currency,
                exc,
            )
            return quotes

        target_u = target_currency.upper()
        if rate == Decimal("1") and target_u != "USD":
            logger.debug("Applying unit conversion rate for USD -> {}", target_u)
        else:
            logger.debug("Applying conversion rate USD -> {}: {}", target_u, rate)

        converted: List[PriceQuote] = []
        for quote in quotes:
            converted.append(
                PriceQuote(
                    symbol=quote.symbol,
                    currency=target_u,
                    price=quote.price * rate,
                    source=quote.source,
                    name=quote.name,
                    change_1h=quote.change_1h,
                    change_4h=quote.change_4h,
                    change_24h=quote.change_24h,
                    change_7d=quote.change_7d,
                )
            )
        return converted

    async def _direct_fiat_quote(self, base: str, target: str) -> Optional[PriceQuote]:
        if not (base.isalpha() and target.isalpha()):
            return None
        if len(base) > 4 or len(target) > 4:
            return None

        if not await self._fiat_converter.has_rate(base):
            return None
        if not await self._fiat_converter.has_rate(target):
            return None

        try:
            rate = await self._fiat_converter.convert(base, target)
        except FiatConversionError:
            return None

        logger.debug("Fiat converter produced rate for {}/{}: {}", base, target, rate)
        return PriceQuote(
            symbol=base,
            currency=target,
            price=rate,
            source="fiat_converter",
            name=base,
        )

    async def _fetch_from_source(
        self,
        source: PriceSource,
        symbol: str,
        currency: str,
        limit: int,
    ) -> tuple[PriceSource, List[PriceQuote]]:
        logger.debug(
            "Requesting price via {} for {}/{}",
            source.name,
            symbol,
            currency,
        )
        try:
            quotes = await source.get_prices(symbol, currency, limit=limit)
        except Exception as exc:
            logger.debug("Price source {} errored: {}", source.name, exc)
            return source, []

        if not quotes:
            logger.debug(
                "Price source {} returned no quotes for {}/{}",
                source.name,
                symbol,
                currency,
            )
            return source, []

        logger.debug(
            "Price source {} returned {} raw quote(s) for {}/{}",
            source.name,
            len(quotes),
            symbol,
            currency,
        )
        return source, quotes
