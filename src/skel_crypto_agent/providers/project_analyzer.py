from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from .web_search import SearchKnowledge, TavilySearchClient


@dataclass(slots=True)
class ProjectProfile:
    name: Optional[str] = None
    symbol: Optional[str] = None
    category: Optional[str] = None
    stage: Optional[str] = None
    description: Optional[str] = None
    funding_total: Optional[str] = None
    investors: List[str] = field(default_factory=list)
    reward_opportunities: Optional[str] = None
    socials: Dict[str, str] = field(default_factory=dict)
    website: Optional[str] = None
    sentiment: Optional[str] = None
    plan_notes: List[str] = field(default_factory=list)


@dataclass(slots=True)
class ProjectAnalysis:
    name: str
    symbol: Optional[str]
    category: Optional[str]
    stage: Optional[str]
    description: Optional[str]
    sentiment: Optional[str]
    funding_total: Optional[str]
    reward_opportunities: Optional[str]
    investors: List[str]
    socials: Dict[str, str]
    website: Optional[str]
    plan_notes: List[str]
    tavily_answer: Optional[str]
    tavily_sources: List[Dict[str, str]]


class ProjectAnalyzer:
    """Collects crypto project intelligence from CryptoRank and web search."""

    def __init__(
        self,
        *,
        api_key: Optional[str],
        tavily_client: Optional[TavilySearchClient],
    ) -> None:
        self._api_key = api_key
        self._tavily = tavily_client
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
        self._lock = asyncio.Lock()
        self._base_url = "https://api.cryptorank.io/v2"
        self._map_cache: Optional[List[Dict[str, Any]]] = None
        self._map_cache_expiry: float = 0.0
        self._category_cache: Dict[int, str] = {}
        self._category_cache_expiry: float = 0.0
        self._cache_ttl = 1800.0
        self._forbidden_markers: set[str] = set()

    async def close(self) -> None:
        await self._client.aclose()

    async def analyze(self, project_name: str, lang: str) -> ProjectAnalysis:
        profile = ProjectProfile()

        if self._api_key:
            try:
                await self._populate_from_cryptorank(profile, project_name)
            except Exception as exc:
                logger.exception("CryptoRank fetch failed: %s", exc)

        knowledge = await self._fetch_tavily_knowledge(project_name)
        tavily_answer = knowledge.answer if knowledge else None
        tavily_sources = []
        if knowledge:
            for item in knowledge.sources:
                tavily_sources.append({"title": item.title, "url": item.url, "snippet": item.snippet})

        return ProjectAnalysis(
            name=profile.name or project_name,
            symbol=profile.symbol,
            category=profile.category,
            stage=profile.stage,
            description=profile.description,
            sentiment=profile.sentiment,
            funding_total=profile.funding_total,
            reward_opportunities=profile.reward_opportunities,
            investors=list(profile.investors),
            socials=dict(profile.socials),
            website=profile.website,
            plan_notes=list(profile.plan_notes),
            tavily_answer=tavily_answer,
            tavily_sources=tavily_sources,
        )

    async def _populate_from_cryptorank(self, profile: ProjectProfile, project_name: str) -> None:
        query = project_name.strip()
        if not query or not self._api_key:
            return

        entry = await self._resolve_currency(query)
        if not entry:
            logger.debug("CryptoRank could not resolve project for query %s", query)
            return

        profile.name = entry.get("name") or profile.name
        if entry.get("symbol"):
            profile.symbol = entry["symbol"]

        stage = self._normalize_stage(entry.get("lifeCycle"))
        if stage:
            profile.stage = stage

        currency_id = entry.get("id")
        if not currency_id:
            return

        currency_task = asyncio.create_task(self._get_currency_details(currency_id))
        full_meta_task = (
            asyncio.create_task(self._get_full_metadata(currency_id))
            if not self._is_forbidden_marker("full-metadata")
            else None
        )
        funding_task = (
            asyncio.create_task(self._get_funding_rounds(currency_id))
            if not self._is_forbidden_marker("funding-rounds")
            else None
        )

        currency = await currency_task
        full_meta = await full_meta_task if full_meta_task else None
        funding = await funding_task if funding_task else None

        investors: List[str] = profile.investors

        if currency:
            profile.symbol = currency.get("symbol") or profile.symbol
            stage = self._normalize_stage(currency.get("lifeCycle"))
            if stage:
                profile.stage = stage
            category_name = await self._category_name(currency.get("categoryId"))
            if category_name:
                profile.category = category_name
            reward_hint = self._reward_hint_from_flags(currency)
            profile.reward_opportunities = self._merge_reward_notes(
                profile.reward_opportunities,
                reward_hint,
            )
            sentiment_bits: List[str] = []
            asset_type = currency.get("type")
            if asset_type:
                sentiment_bits.append(f"Asset type: {str(asset_type).replace('-', ' ').title()}")
            rank = currency.get("rank")
            if rank:
                sentiment_bits.append(f"Rank #{rank}")
            price = self._format_money(currency.get("price"))
            if price:
                sentiment_bits.append(f"Last price {price}")
            if sentiment_bits:
                profile.sentiment = "; ".join(sentiment_bits)

        if full_meta:
            description = full_meta.get("shortDescription") or full_meta.get("description")
            if description:
                profile.description = (
                    str(description)
                    .replace("\r\n", "\n")
                    .replace("\r", "\n")
                )
            self._merge_links(profile, full_meta.get("links"))
            investors = self._merge_investors(investors, self._collect_investors(full_meta.get("funds")))
        elif self._is_forbidden_marker("full-metadata"):
            note = (
                "Detailed project metadata requires a higher CryptoRank plan—"
                "support the creator so we can upgrade access."
            )
            if note not in profile.plan_notes:
                profile.plan_notes.append(note)

        if funding:
            total_raise = funding.get("totalFundingRaise") or funding.get("totalRaise")
            formatted_total = self._format_money(total_raise)
            if formatted_total:
                profile.funding_total = formatted_total
            investors = self._merge_investors(
                investors,
                self._collect_investors_from_rounds(funding.get("fundingRounds")),
            )
            profile.reward_opportunities = self._merge_reward_notes(
                profile.reward_opportunities,
                funding.get("fundrasingDescription"),
            )
        elif self._is_forbidden_marker("funding-rounds"):
            note = (
                "Funding round details are locked behind a higher CryptoRank plan—"
                "support the creator to help us unlock them."
            )
            if note not in profile.plan_notes:
                profile.plan_notes.append(note)

        if investors:
            profile.investors = investors

    async def _fetch_tavily_knowledge(self, project_name: str) -> Optional[SearchKnowledge]:
        if not self._tavily:
            return None

        query = f"{project_name} crypto project overview".strip()
        try:
            knowledge = await self._tavily.search(query)
        except Exception as exc:
            logger.debug("Tavily lookup skipped: %s", exc)
            return None

        return knowledge

    async def _resolve_currency(self, query: str) -> Optional[Dict[str, Any]]:
        items = await self._get_currency_map()
        if not items:
            return None

        query_norm = query.strip().lower()
        slug = "-".join(query_norm.split())

        best: Optional[Dict[str, Any]] = None
        best_score = -1
        for item in items:
            score = self._score_currency(item, query_norm, slug)
            if score > best_score:
                best = item
                best_score = score
            elif score == best_score and best is not None:
                if self._stage_priority(item.get("lifeCycle")) > self._stage_priority(best.get("lifeCycle")):
                    best = item

        if best_score < 40:
            return None
        return best

    def _score_currency(self, item: Dict[str, Any], query_norm: str, slug: str) -> int:
        if not query_norm:
            return -1

        name = (item.get("name") or "").lower()
        symbol = (item.get("symbol") or "").lower()
        key = (item.get("key") or "").lower()

        if symbol and query_norm == symbol:
            return 100
        if key and query_norm == key:
            return 95
        if name and query_norm == name:
            return 90
        if slug and key == slug:
            return 88

        score = 0
        if symbol and query_norm == symbol.replace(" ", ""):
            score = max(score, 85)
        if symbol and query_norm.upper() == symbol.upper():
            score = max(score, 82)
        if query_norm in name and len(query_norm) >= 3:
            proximity = 70 - max(0, len(name) - len(query_norm))
            score = max(score, proximity)
        if query_norm in key and len(query_norm) >= 3:
            proximity = 65 - max(0, len(key) - len(query_norm))
            score = max(score, proximity)
        if symbol and any(part == symbol for part in query_norm.split()):
            score = max(score, 60)
        return score

    def _stage_priority(self, stage: Optional[str]) -> int:
        mapping = {
            "traded": 5,
            "crowdsale": 4,
            "funding": 3,
            "scheduled": 2,
            "inactive": 1,
        }
        return mapping.get((stage or "").lower(), 0)

    def _normalize_stage(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        clean = value.replace("_", " ").replace("-", " ").strip()
        if not clean:
            return None
        return clean.title()

    async def _get_currency_map(self) -> Optional[List[Dict[str, Any]]]:
        now = time.time()
        if self._map_cache and now < self._map_cache_expiry:
            return self._map_cache

        data = await self._get("/currencies/map", params={"include": ["lifeCycle", "type"]})
        if isinstance(data, list):
            self._map_cache = data
            self._map_cache_expiry = now + self._cache_ttl
            return data
        return None

    async def _category_name(self, category_id: Optional[int]) -> Optional[str]:
        if not category_id:
            return None

        now = time.time()
        if self._category_cache and now < self._category_cache_expiry:
            return self._category_cache.get(int(category_id))

        data = await self._get("/currencies/categories")
        if isinstance(data, list):
            self._category_cache = {}
            for item in data:
                if isinstance(item, dict) and item.get("id") is not None:
                    try:
                        cid = int(item["id"])
                    except (TypeError, ValueError):
                        continue
                    name = item.get("name")
                    if name:
                        self._category_cache[cid] = str(name)
            self._category_cache_expiry = now + self._cache_ttl
        return self._category_cache.get(int(category_id))

    async def _get_currency_details(self, currency_id: Optional[int]) -> Optional[Dict[str, Any]]:
        if currency_id is None:
            return None
        data = await self._get(f"/currencies/{currency_id}")
        return data if isinstance(data, dict) else None

    async def _get_full_metadata(self, currency_id: Optional[int]) -> Optional[Dict[str, Any]]:
        if currency_id is None:
            return None
        data = await self._get(f"/currencies/{currency_id}/full-metadata")
        return data if isinstance(data, dict) else None

    async def _get_funding_rounds(self, currency_id: Optional[int]) -> Optional[Dict[str, Any]]:
        if currency_id is None:
            return None
        data = await self._get(f"/currencies/{currency_id}/funding-rounds")
        return data if isinstance(data, dict) else None

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        headers = {"X-Api-Key": self._api_key} if self._api_key else None
        try:
            response = await self._client.get(
                f"{self._base_url}{path}",
                params=params,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            logger.debug("CryptoRank request failed via %s%s: %s", self._base_url, path, exc)
            return None

        if response.status_code == 403:
            self._record_forbidden(path)
            logger.debug(
                "CryptoRank request forbidden via %s%s (plan restriction)",
                self._base_url,
                path,
            )
            return None
        if response.status_code == 404:
            logger.debug("CryptoRank resource not found via %s%s", self._base_url, path)
            return None

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.debug("CryptoRank request failed via %s%s: %s", self._base_url, path, exc)
            return None

        try:
            payload = response.json()
        except ValueError:
            logger.debug("CryptoRank response for %s%s is not JSON", self._base_url, path)
            return None

        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    def _record_forbidden(self, path: str) -> None:
        clean = path.split("?", 1)[0]
        self._forbidden_markers.add(clean)
        suffix = clean.rsplit("/", 1)[-1]
        if suffix:
            self._forbidden_markers.add(suffix)

    def _is_forbidden_marker(self, marker: str) -> bool:
        return marker in self._forbidden_markers

    def _merge_links(self, profile: ProjectProfile, links: Any) -> None:
        if not isinstance(links, list):
            return

        label_map = {
            "twitter": "X / Twitter",
            "telegram": "Telegram",
            "discord": "Discord",
            "medium": "Medium",
            "github": "GitHub",
            "gitbook": "GitBook",
            "youtube": "YouTube",
            "linkedin": "LinkedIn",
            "facebook": "Facebook",
            "reddit": "Reddit",
            "wechat": "WeChat",
            "slack": "Slack",
            "blog": "Blog",
            "announcement": "Announcements",
            "explorer": "Explorer",
            "farcaster": "Farcaster",
        }

        for link in links:
            if not isinstance(link, dict):
                continue
            link_type = str(link.get("type") or "").lower()
            raw_url = link.get("url") or link.get("value")
            if not isinstance(raw_url, str):
                continue
            url = raw_url.strip()
            if not url:
                continue

            if link_type in {"web", "referral"}:
                if not profile.website:
                    profile.website = url
                continue

            label = label_map.get(link_type) or link_type.replace("-", " ").title()
            profile.socials.setdefault(label, url)

    def _collect_investors(self, funds: Any) -> List[str]:
        if not isinstance(funds, list):
            return []
        names: List[str] = []
        for item in funds:
            name = self._safe_name(item)
            if name:
                names.append(name)
        return names

    def _collect_investors_from_rounds(self, rounds: Any) -> List[str]:
        if not isinstance(rounds, list):
            return []
        seen: set[str] = set()
        collected: List[str] = []
        for round_item in rounds:
            if not isinstance(round_item, dict):
                continue
            for fund in round_item.get("funds") or []:
                name = self._safe_name(fund)
                if not name:
                    continue
                key = name.strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                collected.append(name)
        return collected

    def _merge_investors(self, current: List[str], additions: List[str]) -> List[str]:
        if not additions:
            return current
        result = list(current)
        seen = {name.strip().lower() for name in current if isinstance(name, str)}
        for name in additions:
            if not name:
                continue
            normalized = name.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(normalized)
        return result

    def _merge_reward_notes(self, base: Optional[str], addition: Optional[str]) -> Optional[str]:
        fragments: List[str] = []
        for value in (base, addition):
            if not value:
                continue
            parts = [segment.strip() for segment in str(value).split(";") if segment.strip()]
            fragments.extend(parts)

        if not fragments:
            return None

        merged: List[str] = []
        seen: set[str] = set()
        for fragment in fragments:
            key = fragment.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(fragment)
        return "; ".join(merged)

    def _reward_hint_from_flags(self, payload: Dict[str, Any]) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        hints: List[str] = []
        if payload.get("hasCrowdsales"):
            hints.append("Public token sale records available")
        if payload.get("hasLaunchpools"):
            hints.append("Launchpool campaigns tracked")
        if payload.get("hasVesting"):
            hints.append("Vesting schedules published")
        if payload.get("hasFundingRounds"):
            hints.append("Venture funding history tracked")
        if payload.get("hasActivity"):
            hints.append("On-chain activity metrics available")
        if payload.get("hasNextUnlock"):
            hints.append("Upcoming unlock schedule monitored")
        return "; ".join(hints) if hints else None

    def _format_money(self, payload: Any) -> Optional[str]:
        if payload is None:
            return None
        if isinstance(payload, (int, float, Decimal)):
            return f"${float(payload):,.2f}"
        if isinstance(payload, str):
            raw = payload.replace(",", "").strip()
            if not raw:
                return None
            try:
                value = Decimal(raw)
            except (InvalidOperation, ValueError):
                return payload
            return f"${value:,.2f}"
        if isinstance(payload, dict):
            value = (
                payload.get("value")
                or payload.get("amount")
                or payload.get("total")
                or payload.get("raised")
            )
            currency = payload.get("currency") or "$"
            formatted = self._format_money(value)
            if formatted:
                if formatted.startswith("$") and currency and currency != "$":
                    return f"{currency} {formatted[1:]}"
                return formatted
            if value is not None:
                return f"{currency} {value}"
            return None
        return str(payload)

    def _safe_name(self, item: Any) -> str:
        if isinstance(item, dict):
            for key in ("name", "title", "entity"):
                value = item.get(key)
                if value:
                    return str(value)
            return "?"
        if isinstance(item, str):
            return item
        return str(item)
