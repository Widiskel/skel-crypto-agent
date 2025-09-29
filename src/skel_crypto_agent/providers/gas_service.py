from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence

import httpx
from loguru import logger

from .price_service import PriceService


WEI_PER_GWEI = Decimal("1000000000")
TRANSFER_GAS_LIMIT = 21_000
CONTRACT_GAS_LIMIT = 100_000
ACTION_PROFILES = [
    ("Swap", 150_000),
    ("NFT Sale", 210_000),
    ("Bridging", 250_000),
    ("Borrowing", 180_000),
]
GAS_TIER_PROFILES = [
    ("low", "Low", "😌", Decimal("0.95"), Decimal("0.5"), 45),
    ("average", "Average", "🙂", Decimal("1.0"), Decimal("1.0"), 30),
    ("high", "High", "😬", Decimal("1.05"), Decimal("2.0"), 15),
]
DEFAULT_PRIORITY_FRACTION = Decimal("0.15")
MIN_PRIORITY_GWEI = Decimal("0.1")
DEFAULT_CHAIN_ID = 1
CHAINLIST_URL_DEFAULT = "https://chainlist.org/rpcs.json"

TRACKING_PRIORITY = {
    "none": 0,
    "": 1,
    "unspecified": 1,
    "unknown": 1,
    "limited": 2,
    "yes": 3,
    "required": 4,
}


class GasServiceError(RuntimeError):
    """Raised when the gas service cannot provide a quote."""


@dataclass(slots=True)
class ExplorerInfo:
    name: str
    url: str
    standard: Optional[str] = None


@dataclass(slots=True)
class NetworkConfig:
    chain_id: int
    name: str
    native_symbol: str
    native_name: str
    decimals: int
    rpc_urls: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    chain: Optional[str] = None
    short_name: Optional[str] = None
    network_tag: Optional[str] = None
    is_testnet: bool = False
    info_url: Optional[str] = None
    faucets: List[str] = field(default_factory=list)
    explorers: List[ExplorerInfo] = field(default_factory=list)


@dataclass(slots=True)
class GasTierQuote:
    key: str
    label: str
    emoji: str
    total_wei: int
    total_gwei: Decimal
    base_component_gwei: Decimal
    priority_component_gwei: Decimal
    eta_seconds: int
    per_gas_native: Decimal
    per_gas_currency: Optional[Decimal]
    transfer_fee_native: Decimal
    transfer_fee_currency: Optional[Decimal]
    contract_fee_native: Decimal
    contract_fee_currency: Optional[Decimal]


@dataclass(slots=True)
class GasActionEstimate:
    action: str
    gas_limit: int
    native_costs: Dict[str, Decimal]
    currency_costs: Dict[str, Optional[Decimal]]


@dataclass(slots=True)
class GasQuote:
    network_key: int
    network_name: str
    chain_id: int
    native_symbol: str
    native_decimals: int
    base_fee_gwei: Decimal
    priority_fee_gwei: Decimal
    tiers: List[GasTierQuote]
    actions: List[GasActionEstimate]
    native_price_in_currency: Optional[Decimal]
    requested_currency: str
    resolved_currency: str
    rpc_url: str
    transfer_gas_limit: int
    contract_gas_limit: int


@dataclass(slots=True)
class RpcDirectoryResult:
    resolved_query: str
    networks: List[NetworkConfig]


class GasService:
    def __init__(
        self,
        price_service: PriceService,
        *,
        chainlist_url: str = CHAINLIST_URL_DEFAULT,
    ) -> None:
        self._price_service = price_service
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
        self._chainlist_url = chainlist_url
        self._networks_by_id: Dict[int, NetworkConfig] = {}
        self._networks_by_alias: Dict[str, NetworkConfig] = {}
        self._network_lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.aclose()

    async def get_gas_quote(self, network_name: Optional[str], currency: Optional[str]) -> GasQuote:
        network = await self._resolve_network(network_name)
        if not network:
            raise GasServiceError("Unsupported network")

        gas_price_wei, rpc_url = await self._fetch_gas_price(network)
        priority_fee_wei = await self._fetch_priority_fee(rpc_url)

        gas_price_dec = Decimal(gas_price_wei)
        priority_dec = Decimal(priority_fee_wei) if priority_fee_wei else Decimal(0)

        if priority_dec <= 0:
            priority_dec = (gas_price_dec * DEFAULT_PRIORITY_FRACTION).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if priority_dec < Decimal(1):
            priority_dec = Decimal(1)
        if priority_dec >= gas_price_dec:
            priority_dec = (gas_price_dec * DEFAULT_PRIORITY_FRACTION).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            if priority_dec >= gas_price_dec:
                priority_dec = gas_price_dec * Decimal("0.2")
        priority_dec = priority_dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

        base_dec = gas_price_dec - priority_dec
        if base_dec <= 0:
            base_dec = (gas_price_dec * Decimal("0.8")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        if base_dec <= 0:
            base_dec = gas_price_dec

        base_fee_gwei = base_dec / WEI_PER_GWEI
        priority_fee_gwei = priority_dec / WEI_PER_GWEI

        requested_currency = (currency or "USD").upper()
        resolved_currency = requested_currency
        native_price_in_currency: Optional[Decimal] = None

        price_quote = await self._get_price(network.native_symbol, requested_currency)
        if not price_quote and requested_currency != "USD":
            price_quote = await self._get_price(network.native_symbol, "USD")
            resolved_currency = "USD"

        if price_quote:
            native_price_in_currency = price_quote.price

        base_divisor = Decimal(10) ** network.decimals
        tiers: List[GasTierQuote] = []

        for key, label, emoji, base_multiplier, tip_multiplier, eta_seconds in GAS_TIER_PROFILES:
            base_component = (base_dec * base_multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            priority_component = (priority_dec * tip_multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)

            if base_component <= 0:
                base_component = base_dec
            if priority_component < Decimal(1) and priority_dec > 0:
                priority_component = Decimal(1)

            total_wei_dec = base_component + priority_component
            if total_wei_dec <= 0:
                total_wei_dec = gas_price_dec

            total_wei = int(total_wei_dec)
            total_gwei = total_wei_dec / WEI_PER_GWEI
            base_component_gwei = base_component / WEI_PER_GWEI
            priority_component_gwei = priority_component / WEI_PER_GWEI

            per_gas_native = total_wei_dec / base_divisor
            per_gas_currency = None
            if native_price_in_currency is not None:
                per_gas_currency = per_gas_native * native_price_in_currency

            transfer_native = per_gas_native * TRANSFER_GAS_LIMIT
            contract_native = per_gas_native * CONTRACT_GAS_LIMIT
            transfer_currency = per_gas_currency * TRANSFER_GAS_LIMIT if per_gas_currency is not None else None
            contract_currency = per_gas_currency * CONTRACT_GAS_LIMIT if per_gas_currency is not None else None

            tiers.append(
                GasTierQuote(
                    key=key,
                    label=label,
                    emoji=emoji,
                    total_wei=total_wei,
                    total_gwei=total_gwei,
                    base_component_gwei=base_component_gwei,
                    priority_component_gwei=priority_component_gwei,
                    eta_seconds=eta_seconds,
                    per_gas_native=per_gas_native,
                    per_gas_currency=per_gas_currency,
                    transfer_fee_native=transfer_native,
                    transfer_fee_currency=transfer_currency,
                    contract_fee_native=contract_native,
                    contract_fee_currency=contract_currency,
                )
            )

        if not tiers:
            raise GasServiceError("Failed to compute gas tiers")

        actions: List[GasActionEstimate] = []
        for action_name, gas_limit in ACTION_PROFILES:
            native_costs: Dict[str, Decimal] = {}
            currency_costs: Dict[str, Optional[Decimal]] = {}
            for tier in tiers:
                native_cost = tier.per_gas_native * gas_limit
                currency_cost = tier.per_gas_currency * gas_limit if tier.per_gas_currency is not None else None
                native_costs[tier.key] = native_cost
                currency_costs[tier.key] = currency_cost
            actions.append(
                GasActionEstimate(
                    action=action_name,
                    gas_limit=gas_limit,
                    native_costs=native_costs,
                    currency_costs=currency_costs,
                )
            )

        return GasQuote(
            network_key=network.chain_id,
            network_name=network.name,
            chain_id=network.chain_id,
            native_symbol=network.native_symbol,
            native_decimals=network.decimals,
            base_fee_gwei=base_fee_gwei,
            priority_fee_gwei=priority_fee_gwei,
            tiers=tiers,
            actions=actions,
            native_price_in_currency=native_price_in_currency,
            requested_currency=requested_currency,
            resolved_currency=resolved_currency,
            rpc_url=rpc_url,
            transfer_gas_limit=TRANSFER_GAS_LIMIT,
            contract_gas_limit=CONTRACT_GAS_LIMIT,
        )

    async def _resolve_network(self, network_name: Optional[str]) -> Optional[NetworkConfig]:
        await self._ensure_network_index()
        if not self._networks_by_id:
            return None

        if not network_name:
            return self._networks_by_id.get(DEFAULT_CHAIN_ID) or next(iter(self._networks_by_id.values()))

        lookup = network_name.strip().lower()
        if not lookup:
            return self._networks_by_id.get(DEFAULT_CHAIN_ID)

        if lookup.isdigit():
            try:
                chain_id = int(lookup)
            except ValueError:
                chain_id = None
            else:
                network = self._networks_by_id.get(chain_id)
                if network:
                    return network

        if lookup.startswith("0x"):
            try:
                chain_id = int(lookup, 16)
            except ValueError:
                chain_id = None
            else:
                network = self._networks_by_id.get(chain_id)
                if network:
                    return network

        network = self._networks_by_alias.get(lookup)
        if network:
            return network

        normalized = " ".join(token for token in re.split(r"[^a-z0-9]+", lookup) if token)
        if normalized:
            network = self._networks_by_alias.get(normalized)
            if network:
                return network

        tokens = [token for token in lookup.replace("-", " ").split() if token]
        for token in tokens:
            network = self._networks_by_alias.get(token)
            if network:
                return network

        return self._networks_by_id.get(DEFAULT_CHAIN_ID)

    async def get_rpc_directory(self, query: Optional[str]) -> RpcDirectoryResult:
        await self._ensure_network_index()
        if not self._networks_by_id:
            raise GasServiceError("RPC directory unavailable")

        raw_query = (query or "").strip()
        if not raw_query:
            raw_query = "eth"

        query_norm = raw_query.lower()
        matches: List[NetworkConfig] = []
        seen: set[int] = set()

        def add_network(item: NetworkConfig) -> None:
            if item.chain_id not in seen:
                matches.append(item)
                seen.add(item.chain_id)

        chain_id_candidate: Optional[int] = None
        try:
            if query_norm.startswith("0x"):
                chain_id_candidate = int(query_norm, 16)
            elif query_norm.isdigit():
                chain_id_candidate = int(query_norm)
        except ValueError:
            chain_id_candidate = None

        if chain_id_candidate is not None:
            network = self._networks_by_id.get(chain_id_candidate)
            if network:
                add_network(network)
                return RpcDirectoryResult(resolved_query=raw_query, networks=matches)

        query_upper = query_norm.upper()

        for network in self._networks_by_id.values():
            if query_norm in network.aliases:
                add_network(network)
                continue
            if network.chain and network.chain.lower() == query_norm:
                add_network(network)
                continue
            if network.short_name and network.short_name.lower() == query_norm:
                add_network(network)
                continue
            if network.native_symbol.lower() == query_norm:
                add_network(network)
                continue
            name_lower = network.name.lower()
            if query_norm and query_norm == name_lower:
                add_network(network)
                continue
            if len(query_norm) >= 3 and query_norm in name_lower:
                add_network(network)

        if not matches and query_norm:
            for network in self._networks_by_id.values():
                name_lower = network.name.lower()
                short_lower = (network.short_name or "").lower()
                if name_lower.startswith(query_norm) or short_lower.startswith(query_norm):
                    add_network(network)

        matches.sort(key=lambda item: (item.is_testnet, item.chain_id))

        max_results = 15
        if len(matches) > max_results:
            matches = matches[:max_results]

        return RpcDirectoryResult(resolved_query=raw_query, networks=matches)

    async def _ensure_network_index(self) -> None:
        if self._networks_by_id:
            return

        async with self._network_lock:
            if self._networks_by_id:
                return

            try:
                response = await self._client.get(self._chainlist_url)
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                logger.warning("Failed to load Chainlist RPC directory: {}", exc)
                if not self._networks_by_id:
                    raise GasServiceError("Chainlist RPC directory unavailable") from exc
                return

            self._build_network_index(payload)

            if not self._networks_by_id:
                raise GasServiceError("No supported networks found in Chainlist data")

    def _build_network_index(self, payload: object) -> None:
        if not isinstance(payload, Sequence):
            logger.warning("Unexpected Chainlist payload type: {}", type(payload))
            return

        networks: Dict[int, NetworkConfig] = {}
        alias_map: Dict[str, NetworkConfig] = {}

        for entry in payload:
            if not isinstance(entry, dict):
                continue

            chain_id = self._parse_chain_id(entry.get("chainId"))
            if chain_id is None:
                continue

            rpc_urls = self._filter_rpc_urls(entry.get("rpc"))
            if not rpc_urls:
                continue

            native_data = entry.get("nativeCurrency") or {}
            decimals = native_data.get("decimals")
            try:
                decimals_int = int(decimals)
            except (TypeError, ValueError):
                decimals_int = 18

            native_symbol = self._derive_symbol(native_data, entry, chain_id)
            native_name = str(native_data.get("name") or entry.get("name") or native_symbol)
            name = str(entry.get("name") or native_name or f"Chain {chain_id}")

            chain_code = str(entry.get("chain") or native_symbol).upper()
            short_name = entry.get("shortName")
            if isinstance(short_name, str):
                short_name = short_name.strip()
                if not short_name:
                    short_name = None
            else:
                short_name = None

            network_tag = entry.get("network")
            if isinstance(network_tag, str):
                network_tag = network_tag.strip()
                if not network_tag:
                    network_tag = None
            else:
                network_tag = None

            testnet_flag = entry.get("testnet")
            if isinstance(testnet_flag, bool):
                is_testnet = testnet_flag
            elif network_tag:
                is_testnet = network_tag.lower() not in {"", "mainnet", "production"}
            else:
                lowered_name = name.lower()
                is_testnet = any(tag in lowered_name for tag in ("test", "devnet", "dev", "beta"))

            info_url = entry.get("infoURL") or entry.get("infoUrl")
            if isinstance(info_url, str):
                info_url = info_url.strip() or None
            else:
                info_url = None

            faucets_raw = entry.get("faucets") or []
            faucets = [str(url).strip() for url in faucets_raw if isinstance(url, str) and url.strip()]

            explorers_data = entry.get("explorers") or []
            explorers: List[ExplorerInfo] = []
            for raw in explorers_data:
                if not isinstance(raw, dict):
                    continue
                url = raw.get("url")
                if not isinstance(url, str) or not url.strip():
                    continue
                name_value = raw.get("name") or url
                standard = raw.get("standard")
                explorers.append(
                    ExplorerInfo(
                        name=str(name_value),
                        url=url.strip(),
                        standard=str(standard) if isinstance(standard, str) and standard.strip() else None,
                    )
                )

            network = NetworkConfig(
                chain_id=chain_id,
                name=name,
                native_symbol=native_symbol,
                native_name=native_name,
                decimals=decimals_int,
                rpc_urls=rpc_urls,
                aliases=[],
                chain=chain_code,
                short_name=short_name,
                network_tag=network_tag,
                is_testnet=is_testnet,
                info_url=info_url,
                faucets=faucets,
                explorers=explorers,
            )

            alias_candidates = set(self._alias_candidates(entry, native_symbol))
            alias_candidates.add(str(chain_id))
            alias_candidates.add(str(chain_id).lower())
            alias_candidates.add(native_symbol)
            alias_candidates.add(native_symbol.lower())
            alias_candidates.add(hex(chain_id))
            if chain_code:
                alias_candidates.add(chain_code)
                alias_candidates.add(chain_code.lower())
            if short_name:
                alias_candidates.add(short_name)
                alias_candidates.add(short_name.lower())

            normalized_aliases = sorted({alias.strip().lower() for alias in alias_candidates if isinstance(alias, str) and alias.strip()})
            network.aliases = normalized_aliases

            for alias in normalized_aliases:
                existing = alias_map.get(alias)
                if existing and existing.chain_id != chain_id:
                    continue
                alias_map[alias] = network

            networks.setdefault(chain_id, network)

        self._networks_by_id = networks
        self._networks_by_alias = alias_map

    def _filter_rpc_urls(self, rpc_entries: object) -> List[str]:
        if not isinstance(rpc_entries, list):
            return []

        candidates: List[tuple[int, int, str]] = []
        seen: set[str] = set()
        for idx, entry in enumerate(rpc_entries):
            if isinstance(entry, str):
                url = entry
                tracking_value = ""
            elif isinstance(entry, dict):
                url = entry.get("url")
                tracking_value = str(entry.get("tracking") or "")
            else:
                continue

            if not isinstance(url, str):
                continue

            url = url.strip()
            if not url or not url.lower().startswith("http"):
                continue
            if url.lower().startswith("ws"):
                continue
            if "{{" in url or "}}" in url:
                continue

            normalized = url.rstrip("/")
            if normalized in seen:
                continue

            lower_url = normalized.lower()
            penalty = 0
            if "api_key" in lower_url or "apikey" in lower_url:
                penalty += 2
            priority = TRACKING_PRIORITY.get(tracking_value.lower(), 2) + penalty
            candidates.append((priority, idx, normalized))
            seen.add(normalized)

        candidates.sort()
        return [item[2] for item in candidates]

    def _parse_chain_id(self, value: object) -> Optional[int]:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                if stripped.lower().startswith("0x"):
                    return int(stripped, 16)
                return int(stripped)
            except ValueError:
                return None
        return None

    def _derive_symbol(self, native_data: object, entry: dict, chain_id: int) -> str:
        candidates: List[str] = []
        if isinstance(native_data, dict):
            for key in ("symbol", "name"):
                value = native_data.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())

        for key in ("shortName", "chain", "chainSlug", "name"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())

        for candidate in candidates:
            sanitized = re.sub(r"\s+", "", candidate.strip())
            if sanitized:
                return sanitized.upper()

        return f"CHAIN{chain_id}"

    def _alias_candidates(self, entry: dict, native_symbol: str) -> Sequence[str]:
        values: List[str] = []
        for key in ("name", "chain", "shortName", "chainSlug"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())

        native = entry.get("nativeCurrency") or {}
        symbol = native.get("symbol")
        if isinstance(symbol, str) and symbol.strip():
            values.append(symbol.strip())

        if native_symbol:
            values.append(native_symbol)

        results: List[str] = []
        for value in values:
            results.append(value)
            cleaned = re.sub(r"\s+", " ", value)
            if cleaned and cleaned != value:
                results.append(cleaned)
            slug = re.sub(r"[^a-zA-Z0-9]", " ", value).strip()
            if slug:
                results.append(slug)
                compact = slug.replace(" ", "")
                if compact:
                    results.append(compact)
                parts = [part for part in slug.lower().split() if part]
                results.extend(parts)
                if len(parts) >= 2:
                    results.append(" ".join(parts))
                    results.append(parts[0])
                    results.append(parts[-1])

        return results

    async def _fetch_gas_price(self, network: NetworkConfig) -> tuple[int, str]:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_gasPrice", "params": []}
        errors: List[str] = []
        for url in network.rpc_urls:
            try:
                response = await self._client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
            except Exception as exc:
                errors.append(f"{url}: {exc}")
                continue

            result = data.get("result") if isinstance(data, dict) else None
            if not isinstance(result, str):
                errors.append(f"{url}: unexpected response {data}")
                continue

            try:
                gas_price_wei = int(result, 16)
            except ValueError as exc:
                errors.append(f"{url}: invalid hex {result} ({exc})")
                continue

            if gas_price_wei <= 0:
                errors.append(f"{url}: non-positive gas price {result}")
                continue

            logger.debug(
                "Gas price fetched for {} via {}: {} wei",
                network.name,
                url,
                gas_price_wei,
            )
            return gas_price_wei, url

        message = ", ".join(errors) or "No RPC available"
        raise GasServiceError(f"Failed to fetch gas price for {network.name}: {message}")

    async def _fetch_priority_fee(self, url: str) -> Optional[int]:
        payload = {"jsonrpc": "2.0", "id": 2, "method": "eth_maxPriorityFeePerGas", "params": []}
        try:
            response = await self._client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return None

        result = data.get("result") if isinstance(data, dict) else None
        if not isinstance(result, str):
            return None
        try:
            priority_wei = int(result, 16)
        except ValueError:
            return None
        return priority_wei if priority_wei > 0 else None

    async def _get_price(self, symbol: str, currency: str):
        try:
            quotes = await self._price_service.get_prices(symbol, currency, limit=1)
        except Exception as exc:
            logger.debug("Price lookup failed for {}/{}: {}", symbol, currency, exc)
            return None
        if not quotes:
            return None
        return quotes[0]
