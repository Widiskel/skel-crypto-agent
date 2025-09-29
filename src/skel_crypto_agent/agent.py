from __future__ import annotations

import re
import json
import html
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, List, Optional

from loguru import logger
from sentient_agent_framework import AbstractAgent, Query, ResponseHandler, Session

from .providers.agent_provider import AgentProvider
from .providers.price_service import PriceQuote, PriceService
from .providers.project_analyzer import ProjectAnalysis, ProjectAnalyzer
from .providers.web_search import TavilySearchClient
from .providers.gas_service import GasQuote, GasService, GasServiceError, RpcDirectoryResult
from .utils.event import EventBuilder


_CONVERSION_PATTERN = re.compile(
    r"^\s*(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<base>[A-Za-z0-9]{2,10})(?:\s*(?:to)?\s*(?P<quote>[A-Za-z]{2,10}))?\s*$",
    re.IGNORECASE,
)
_LANG_TOKEN = re.compile(r"^\s*\[LANG=(EN|ID)\]\s*", re.IGNORECASE)
_SUPPORTED_LANGS = {"EN", "ID"}
_DEFAULT_LANG = "EN"

PROJECT_SUMMARY_PROMPTS = {
    "EN": (
        "You are the Skel Crypto Agent. Craft Telegram HTML responses summarising a crypto project. "
        "Use <b>, <i>, <code>, <blockquote>, and <a> tags where helpful. "
        "Leverage PROJECT_DATA to build a concise overview without copying raw snippets. "
        "Structure: start with <b>Project Name (Symbol)</b> on its own line, followed by a blank line and a short overview paragraph. "
        "Insert another blank line, then group thematic bullets under bold headings (e.g., <b>Highlights</b>) using <blockquote>• ...</blockquote>, one bullet per line, covering category, stage, funding/backers, technology/roadmap, and social links when present. "
        "If plan_notes exist, add a single <b>Notes</b> section with <blockquote>• ...</blockquote> summarising limitations politely; never output 'data unavailable'. "
        "Weave Tavily information into the narrative; do not mention Tavily or paste raw excerpts. "
        "Only include a <b>References</b> section when at least one source clearly relates to the project, listing up to two <a href> links. "
        "Keep sections separated by blank lines so the message stays readable, maintain a professional tone, and match the target language."
    ),
    "ID": (
        "Kamu adalah Skel Crypto Agent. Buat ringkasan proyek kripto dalam format HTML Telegram yang rapi. "
        "Gunakan tag <b>, <i>, <code>, <blockquote>, dan <a> seperlunya. "
        "Manfaatkan PROJECT_DATA untuk menyusun gambaran tanpa menyalin potongan mentah. "
        "Awali dengan <b>Nama Proyek (Simbol)</b> pada satu baris, beri baris kosong, lalu paragraf ringkas. "
        "Tambahkan baris kosong, kemudian kelompokkan sorotan di bawah judul tebal seperti <b>Sorotan</b> menggunakan <blockquote>• ...</blockquote> per baris untuk kategori, tahap, pendanaan/investor, teknologi/roadmap, serta tautan sosial jika tersedia. "
        "Jika ada plan_notes, buat satu bagian <b>Catatan</b> dengan <blockquote>• ...</blockquote> yang merangkum keterbatasan secara sopan tanpa frasa 'data unavailable'. "
        "Integrasikan wawasan Tavily dalam narasi; jangan sebut Tavily atau menempelkan kutipan mentah. "
        "Hanya tampilkan <b>Referensi</b> bila ada sumber yang relevan dengan proyek, maksimal dua tautan <a href>. "
        "Pastikan antarbagian dipisahkan baris kosong agar mudah dibaca, dan gunakan nada profesional berbahasa Indonesia."
    ),
}

_LANG_MESSAGES: Dict[str, Dict[str, str]] = {
    "EN": {
        "welcome": "Hello! I'm the Skel Crypto Agent. Ask me about crypto, prices, or general market insights.",
        "llm_start": "Generating reply...",
        "llm_error": "Sorry, I can't respond right now. Please try again later.",
        "conversion_fetch": "Fetching {base}/{quote} price...",
        "conversion_error": "Failed to fetch the latest price. Please try again soon.",
        "conversion_missing": "Sorry, I couldn't find a live price for {base}/{quote}.",
        "conversion_single_intro": "Here's the latest snapshot for {amount} {base} → {quote}:",
        "conversion_result": "{amount} {base} ({name}) = {value} {quote} (source: {source})",
        "conversion_multi_header": "Here are the top live prices for {amount} {base} → {quote}:",
        "conversion_multi_row": "{amount} {base} ({name}) = {value} {quote} (source: {source})",
        "project_start": "Analyzing {project}…",
        "project_not_configured": "Project analysis isn't available right now.",
        "project_error": "I couldn't complete the project analysis. Please try again soon.",
        "gas_fetch": "Fetching current gas fees…",
        "gas_error": "I couldn't fetch gas data right now. Please try again later.",
        "gas_not_configured": "Gas fee lookups are not available at the moment.",
        "rpc_fetch": "Looking up RPC endpoints…",
        "rpc_error": "I couldn't retrieve RPC data right now. Please try again later.",
        "rpc_not_configured": "RPC lookup is not available at the moment.",
        "rpc_not_found": "I couldn't find RPC endpoints for {network}.",
    },
    "ID": {
        "welcome": "Halo! Aku Skel Crypto Agent. Tanya apa saja tentang crypto, harga, atau analisis pasar.",
        "llm_start": "Menyusun jawaban...",
        "llm_error": "Maaf, aku belum bisa menjawab sekarang. Coba lagi sebentar lagi.",
        "conversion_fetch": "Mengambil harga {base}/{quote}...",
        "conversion_error": "Gagal mengambil harga terbaru. Coba lagi nanti.",
        "conversion_missing": "Maaf, aku belum menemukan harga {base}/{quote} saat ini.",
        "conversion_single_intro": "Berikut hasil terkini {amount} {base} → {quote}:",
        "conversion_result": "{amount} {base} ({name}) = {value} {quote} (sumber: {source})",
        "conversion_multi_header": "Inilah harga terbaru untuk {amount} {base} → {quote}:",
        "conversion_multi_row": "{amount} {base} ({name}) = {value} {quote} (sumber: {source})",
        "project_start": "Menganalisis {project}…",
        "project_not_configured": "Analisis proyek belum tersedia saat ini.",
        "project_error": "Analisis proyek gagal dilakukan. Coba lagi nanti.",
        "gas_fetch": "Mengambil data gas terkini…",
        "gas_error": "Aku belum bisa mendapatkan data gas sekarang. Coba lagi sebentar lagi.",
        "gas_not_configured": "Layanan informasi gas belum tersedia saat ini.",
        "rpc_fetch": "Mengambil daftar RPC…",
        "rpc_error": "Aku belum bisa mengambil data RPC sekarang. Coba lagi nanti.",
        "rpc_not_configured": "Layanan pencarian RPC belum tersedia saat ini.",
        "rpc_not_found": "Aku tidak menemukan RPC untuk {network}.",
    },
}

_LANG_INSTRUCTION = {
    "EN": (
        "You are a helpful, professional assistant. Always respond in English. "
        "Use courteous, neutral wording and avoid profanity or offensive language. "
        "If the user writes in another language, respond in English unless explicitly asked not to."
    ),
    "ID": (
        "Kamu adalah asisten yang ramah dan profesional. Selalu balas dalam Bahasa Indonesia. "
        "Gunakan bahasa santun dan netral serta hindari kata kasar atau ofensif. "
        "Jika pengguna memakai bahasa lain, tetap balas dalam Bahasa Indonesia kecuali diminta sebaliknya."
    ),
}

SOURCE_LINKS = {
    "coingecko": "https://www.coingecko.com/",
    "binance": "https://www.binance.com/en",
    "bybit": "https://www.bybit.com/en/",
    "coinmarketcap": "https://coinmarketcap.com/",
    "defillama": "https://defillama.com/",
    "fiat_converter": "https://open.er-api.com/",
}


@dataclass(slots=True)
class ConversionRequest:
    amount: Decimal
    base_symbol: str
    quote_symbol: str


@dataclass(slots=True)
class GasRequest:
    network: Optional[str]
    currency: Optional[str]


@dataclass(slots=True)
class RpcRequest:
    network: Optional[str]


class CryptoChatAgent(AbstractAgent):
    """Chat-oriented agent that keeps lightweight session memory."""

    def __init__(
        self,
        name: str,
        model_provider: AgentProvider,
        price_service: PriceService,
        search_client: Optional[TavilySearchClient] = None,
        project_analyzer: Optional[ProjectAnalyzer] = None,
        gas_service: Optional[GasService] = None,
    ) -> None:
        super().__init__(name)
        self.model_provider = model_provider
        self.price_service = price_service
        self.search_client = search_client
        self.project_analyzer = project_analyzer
        self.gas_service = gas_service
        self._chat_histories: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        self._language_pref: Dict[str, str] = {}
        self._max_turns = 20
        self._warmup_started = False

    async def assist(self, session: Session, query: Query, response_handler: ResponseHandler) -> None:
        events = EventBuilder(handler=response_handler)
        activity_id = str(session.activity_id)
        incoming_prompt = (query.prompt or "").strip()

        lang, prompt = self._extract_language(activity_id, incoming_prompt)
        logger.info("Activity {} (lang={}) received prompt: {}", activity_id, lang, prompt)

        if not prompt:
            welcome = self._msg(lang, "welcome")
            self._log_response(activity_id, lang, welcome)
            await events.final_block(welcome)
            return

        project_query = self._parse_project(prompt)
        if project_query:
            await self._handle_project(project_query, events, lang, activity_id)
            return

        gas_request = self._parse_gas(prompt)
        if gas_request:
            await self._handle_gas(gas_request, events, lang, activity_id)
            return

        rpc_request = self._parse_rpc(prompt)
        if rpc_request:
            await self._handle_rpc(rpc_request, events, lang, activity_id)
            return

        conversion = self._parse_conversion(prompt)
        if conversion:
            await self._handle_conversion(conversion, events, lang, activity_id)
            return

        history = self._chat_histories[activity_id]
        history.append({"role": "user", "content": prompt})
        self._trim_history(history)

        search_context = await self._build_search_context(prompt, lang)

        try:
            await events.start(self._msg(lang, "llm_start"))
            messages_for_llm = history.copy()
            messages_for_llm.insert(0, {"role": "system", "content": _LANG_INSTRUCTION[lang]})
            if search_context:
                messages_for_llm.insert(1, {"role": "system", "content": search_context})
            reply = await self.model_provider.query(messages_for_llm)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to generate reply: {}", exc)
            msg = self._msg(lang, "llm_error")
            self._log_response(activity_id, lang, msg)
            await events.fail(msg)
            return

        history.append({"role": "assistant", "content": reply})
        self._trim_history(history)
        self._log_response(activity_id, lang, reply)
        await events.final_block(reply)

    def reset(self, session_id: str) -> None:
        self._chat_histories.pop(session_id, None)
        self._language_pref.pop(session_id, None)

    async def _handle_project(self, project_query: str, events: EventBuilder, lang: str, activity_id: str) -> None:
        if not self.project_analyzer:
            msg = self._msg(lang, "project_not_configured")
            self._log_response(activity_id, lang, msg)
            await events.final_block(msg)
            return

        history = self._chat_histories[activity_id]
        history.append({"role": "user", "content": f"[PROJECT] {project_query}"})
        self._trim_history(history)

        await events.start(self._msg(lang, "project_start", project=project_query))
        try:
            analysis = await self.project_analyzer.analyze(project_query, lang)
        except Exception as exc:
            logger.exception("Project analysis failed: %s", exc)
            msg = self._msg(lang, "project_error")
            self._log_response(activity_id, lang, msg)
            await events.fail(msg)
            return

        context_blob = self._build_project_context(analysis, project_query)
        guidance = PROJECT_SUMMARY_PROMPTS.get(lang, PROJECT_SUMMARY_PROMPTS[_DEFAULT_LANG])
        base_messages = [
            {"role": "system", "content": _LANG_INSTRUCTION[lang]},
            {"role": "system", "content": guidance},
            {"role": "system", "content": f"PROJECT_DATA:\n{context_blob}"},
        ]
        messages_for_llm = base_messages + history.copy()

        try:
            reply = await self.model_provider.query(messages_for_llm)
        except Exception as exc:
            logger.exception("Project response generation failed: %s", exc)
            msg = self._msg(lang, "project_error")
            self._log_response(activity_id, lang, msg)
            await events.fail(msg)
            return

        history.append({"role": "assistant", "content": reply})
        self._trim_history(history)
        self._log_response(activity_id, lang, reply)
        await events.final_block(reply)

    async def _handle_gas(self, gas_request: GasRequest, events: EventBuilder, lang: str, activity_id: str) -> None:
        if not self.gas_service:
            msg = self._msg(lang, "gas_not_configured")
            self._log_response(activity_id, lang, msg)
            await events.final_block(msg)
            return

        await events.start(self._msg(lang, "gas_fetch"))

        try:
            quote = await self.gas_service.get_gas_quote(
                network_name=gas_request.network,
                currency=gas_request.currency,
            )
        except GasServiceError as exc:
            logger.warning("Gas lookup failed: %s", exc)
            msg = self._msg(lang, "gas_error")
            self._log_response(activity_id, lang, msg)
            await events.fail(msg)
            return
        except Exception as exc:
            logger.exception("Unexpected gas lookup failure: %s", exc)
            msg = self._msg(lang, "gas_error")
            self._log_response(activity_id, lang, msg)
            await events.fail(msg)
            return

        response = self._render_gas_response(quote, lang)
        self._log_response(activity_id, lang, response)
        await events.final_block(response)

    async def _handle_rpc(self, rpc_request: RpcRequest, events: EventBuilder, lang: str, activity_id: str) -> None:
        if not self.gas_service:
            msg = self._msg(lang, "rpc_not_configured")
            self._log_response(activity_id, lang, msg)
            await events.final_block(msg)
            return

        await events.start(self._msg(lang, "rpc_fetch"))

        try:
            directory = await self.gas_service.get_rpc_directory(rpc_request.network)
        except GasServiceError as exc:
            logger.warning("RPC lookup failed: %s", exc)
            msg = self._msg(lang, "rpc_error")
            self._log_response(activity_id, lang, msg)
            await events.fail(msg)
            return
        except Exception as exc:
            logger.exception("Unexpected RPC lookup failure: %s", exc)
            msg = self._msg(lang, "rpc_error")
            self._log_response(activity_id, lang, msg)
            await events.fail(msg)
            return

        if not directory.networks:
            query_label = rpc_request.network or directory.resolved_query
            msg = self._msg(lang, "rpc_not_found", network=self._html_escape(query_label))
            self._log_response(activity_id, lang, msg)
            await events.final_block(msg)
            return

        response = self._render_rpc_response(directory)
        self._log_response(activity_id, lang, response)
        await events.final_block(response)

    async def _handle_conversion(self, conversion: ConversionRequest, events: EventBuilder, lang: str, activity_id: str) -> None:
        if not self._warmup_started:
            await self.price_service.start()
            self._warmup_started = True

        base = conversion.base_symbol.upper()
        quote = conversion.quote_symbol.upper()
        amount = conversion.amount

        await events.start(self._msg(lang, "conversion_fetch", base=base, quote=quote))
        try:
            quotes = await self.price_service.get_prices(base, quote, limit=3)
        except Exception as exc:
            logger.exception("Price service failed: {}", exc)
            msg = self._msg(lang, "conversion_error")
            self._log_response(activity_id, lang, msg)
            await events.fail(msg)
            return

        if not quotes:
            missing = self._msg(lang, "conversion_missing", base=base, quote=quote)
            self._log_response(activity_id, lang, missing)
            await events.final_block(missing)
            return

        formatted_amount = self._format_amount(amount)
        if len(quotes) == 1:
            price_quote = quotes[0]
            total_value = amount * price_quote.price
            intro = self._format_conversion_intro(
                lang=lang,
                is_multi=False,
                amount=formatted_amount,
                base=base,
                quote=quote,
            )
            data_line = self._format_conversion_line(
                amount=formatted_amount,
                base=base,
                quote=quote,
                price_quote=price_quote,
                value=self._format_amount(total_value),
            )
            change_block = self._format_price_change_block(price_quote)
            if change_block:
                response = f"{intro}\n{data_line}\n<blockquote>• {change_block}</blockquote>"
            else:
                response = f"{intro}\n{data_line}"
            self._log_response(activity_id, lang, response)
            await events.final_block(response)
        else:
            intro = self._format_conversion_intro(
                lang=lang,
                is_multi=True,
                amount=formatted_amount,
                base=base,
                quote=quote,
            )
            lines = [intro]
            for price_quote in quotes:
                total_value = amount * price_quote.price
                lines.append(
                    self._format_conversion_bullet(
                        amount=formatted_amount,
                        base=base,
                        quote=quote,
                        price_quote=price_quote,
                        value=self._format_amount(total_value),
                    )
                )
            multi_response = "\n".join(lines)
            self._log_response(activity_id, lang, multi_response)
            await events.final_block(multi_response)

    def _log_response(self, activity_id: str, lang: str, message: str) -> None:
        snippet = message.replace("\n", " ").strip()
        if len(snippet) > 500:
            snippet = snippet[:497] + "..."
        logger.info("Activity {} (lang={}) response: {}", activity_id, lang, snippet)


    def _format_conversion_intro(self, lang: str, *, is_multi: bool, amount: str, base: str, quote: str) -> str:
        amount_html = self._html_bold(amount)
        base_html = self._html_code(base)
        quote_html = self._html_code(quote)
        arrow = "→"
        if lang == "ID":
            if is_multi:
                text = f"Inilah harga terbaru untuk {amount_html} {base_html} {arrow} {quote_html}:"
            else:
                text = f"Berikut hasil terkini {amount_html} {base_html} {arrow} {quote_html}:"
        else:
            if is_multi:
                text = f"Here are the top live prices for {amount_html} {base_html} {arrow} {quote_html}:"
            else:
                text = f"Here's the latest snapshot for {amount_html} {base_html} {arrow} {quote_html}:"
        return f"<i>{text}</i>"

    def _format_conversion_line(self, *, amount: str, base: str, quote: str, price_quote: PriceQuote, value: str) -> str:
        amount_html = self._html_bold(amount)
        base_html = self._html_code(base)
        quote_html = self._html_code(quote)
        value_html = self._html_bold(value)
        name_html = self._html_underline(price_quote.name or base)
        source_html = self._format_source_label(price_quote.source)
        return (
            f"{amount_html} {base_html} ({name_html}) = {value_html} {quote_html} "
            f"(source: {source_html})"
        )

    def _format_conversion_bullet(self, *, amount: str, base: str, quote: str, price_quote: PriceQuote, value: str) -> str:
        line = self._format_conversion_line(
            amount=amount,
            base=base,
            quote=quote,
            price_quote=price_quote,
            value=value,
        )
        change_block = self._format_price_change_block(price_quote)
        if change_block:
            return f"<blockquote>• {line}\n{change_block}</blockquote>"
        return f"<blockquote>• {line}</blockquote>"

    def _format_price_change_block(self, price_quote: PriceQuote) -> Optional[str]:
        parts: List[str] = []
        mapping = [
            ("1h", price_quote.change_1h),
            ("4h", price_quote.change_4h),
            ("24h", price_quote.change_24h),
            ("7d", price_quote.change_7d),
        ]
        for label, value in mapping:
            if value is None:
                continue
            parts.append(f"{label}: {self._format_percent(value)}")
        if not parts:
            return None
        return f"<i>{' | '.join(parts)}</i>"

    def _format_percent(self, value: Decimal) -> str:
        try:
            pct = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except Exception:
            pct = value
        sign = "+" if pct >= 0 else ""
        return f"{sign}{format(pct, '.2f')}%"

    def _render_rpc_response(self, directory: RpcDirectoryResult) -> str:
        query_label = self._html_escape(directory.resolved_query.upper())
        lines = [f"<b>RPC Directory · {query_label}</b>", ""]

        for network in directory.networks:
            title = f"{network.name} (chain ID {network.chain_id})"
            if network.is_testnet:
                title += " — Testnet"
            lines.append(f"<b>{self._html_escape(title)}</b>")

            detail_parts: List[str] = []
            detail_parts.append(f"Symbol: {network.native_symbol}")
            if network.chain:
                detail_parts.append(f"Chain code: {network.chain}")
            if network.short_name:
                detail_parts.append(f"Short: {network.short_name}")
            if network.network_tag:
                detail_parts.append(f"Network: {network.network_tag}")
            detail_line = " | ".join(self._html_escape(part) for part in detail_parts)
            lines.append(f"<blockquote>• {detail_line}</blockquote>")

            max_rpc = 10
            rpc_urls = network.rpc_urls[:max_rpc]
            if rpc_urls:
                rpc_block = ["• RPC endpoints:"]
                for url in rpc_urls:
                    rpc_block.append(self._html_code(url))
                if len(network.rpc_urls) > max_rpc:
                    remaining = len(network.rpc_urls) - max_rpc
                    rpc_block.append(self._html_escape(f"(+{remaining} more on Chainlist)"))
                rpc_text = "\n".join(rpc_block)
                lines.append(f"<blockquote>{rpc_text}</blockquote>")

            if network.info_url:
                href = html.escape(network.info_url, quote=True)
                info_line = f"• Info: <a href=\"{href}\">{self._html_escape(network.info_url)}</a>"
                lines.append(f"<blockquote>{info_line}</blockquote>")

            if network.faucets:
                faucet_limit = 5
                faucet_entries = network.faucets[:faucet_limit]
                faucet_block = ["• Faucets:"]
                faucet_block.extend(self._html_escape(url) for url in faucet_entries)
                if len(network.faucets) > faucet_limit:
                    remaining = len(network.faucets) - faucet_limit
                    faucet_block.append(self._html_escape(f"(+{remaining} more)"))
                faucet_text = "\n".join(faucet_block)
                lines.append(f"<blockquote>{faucet_text}</blockquote>")

            if network.explorers:
                explorer_limit = 5
                explorers = []
                for explorer in network.explorers[:explorer_limit]:
                    href = html.escape(explorer.url, quote=True)
                    name = self._html_escape(explorer.name or explorer.url)
                    explorers.append(f'<a href="{href}">{name}</a>')
                if len(network.explorers) > explorer_limit:
                    explorers.append(self._html_escape(f"(+{len(network.explorers) - explorer_limit} more)"))
                explorer_line = "• Explorers: " + ", ".join(explorers)
                lines.append(f"<blockquote>{explorer_line}</blockquote>")

            lines.append("")

        lines.append("<i>RPC listings sourced from Chainlist.</i>")
        return "\n".join(lines)

    def _render_gas_response(self, quote: GasQuote, lang: str) -> str:
        currency = quote.resolved_currency
        native_symbol = quote.native_symbol

        header = f"<b>{self._html_escape(quote.network_name)} Gas Fees</b>"
        lines = [header, ""]

        for tier in quote.tiers:
            lines.append(f"<b>{tier.emoji} {self._html_escape(tier.label)}</b>")
            total_gwei = self._format_decimal(tier.total_gwei, precision=3)
            base_gwei = self._format_decimal(tier.base_component_gwei, precision=3)
            priority_gwei = self._format_decimal(tier.priority_component_gwei, precision=3)
            lines.append(f"<blockquote>• Total: <code>{total_gwei}</code> gwei per gas</blockquote>")
            lines.append(
                f"<blockquote>• Base: <code>{base_gwei}</code> gwei | Priority: <code>{priority_gwei}</code> gwei</blockquote>"
            )
            if tier.eta_seconds:
                lines.append(f"<blockquote>• ETA: ~{tier.eta_seconds} sec</blockquote>")

            transfer_native = self._format_decimal(tier.transfer_fee_native, precision=8)
            transfer_line = (
                f"<blockquote>• Transfer (~{quote.transfer_gas_limit:,} gas): "
                f"<code>{transfer_native}</code> {native_symbol}{self._format_fiat_suffix(tier.transfer_fee_currency, currency)}"
                "</blockquote>"
            )
            lines.append(transfer_line)

            contract_native = self._format_decimal(tier.contract_fee_native, precision=8)
            contract_line = (
                f"<blockquote>• Contract (~{quote.contract_gas_limit:,} gas): "
                f"<code>{contract_native}</code> {native_symbol}{self._format_fiat_suffix(tier.contract_fee_currency, currency)}"
                "</blockquote>"
            )
            lines.append(contract_line)
            lines.append("")

        if quote.actions:
            lines.append("<b>Featured Actions</b>")
            for action in quote.actions:
                segments: List[str] = []
                for tier in quote.tiers:
                    currency_fee = action.currency_costs.get(tier.key)
                    if currency_fee is not None:
                        value = self._format_decimal(currency_fee, precision=5)
                        segments.append(f"{tier.label}: <b>{value}</b> {currency}")
                    else:
                        native_fee = action.native_costs[tier.key]
                        value = self._format_decimal(native_fee, precision=8)
                        segments.append(f"{tier.label}: <code>{value}</code> {native_symbol}")
                joined = " | ".join(segments)
                lines.append(
                    f"<blockquote>• {self._html_escape(action.action)} — {joined}</blockquote>"
                )
            lines.append("")

        lines.append("<b>Details</b>")
        lines.append(
            f"<blockquote>• Network: {self._html_escape(quote.network_name)} (chain ID {quote.chain_id})</blockquote>"
        )
        lines.append(f"<blockquote>• Native token: {native_symbol}</blockquote>")

        if quote.native_price_in_currency is not None:
            native_price = self._format_decimal(quote.native_price_in_currency, precision=2)
            lines.append(
                f"<blockquote>• {native_symbol} price: {native_price} {currency}</blockquote>"
            )

        base_fee = self._format_decimal(quote.base_fee_gwei, precision=3)
        priority_fee = self._format_decimal(quote.priority_fee_gwei, precision=3)
        lines.append(
            f"<blockquote>• Base fee (est.): <code>{base_fee}</code> gwei | Priority (avg): <code>{priority_fee}</code> gwei</blockquote>"
        )
        lines.append(
            f"<blockquote>• RPC source: {self._html_escape(quote.rpc_url)}</blockquote>"
        )

        if quote.requested_currency != quote.resolved_currency:
            lines.append("")
            lines.append(
                "<i>Note: Displayed amounts use {actual} because rates for {requested} were unavailable.</i>".format(
                    actual=quote.resolved_currency,
                    requested=quote.requested_currency,
                )
            )

        lines.append("")
        lines.append("<i>Gas data from on-chain RPC; token prices via market feeds.</i>")
        return "\n".join(lines)

    def _format_fiat_suffix(self, amount: Optional[Decimal], currency: str) -> str:
        if amount is None:
            return ""
        fiat_amount = self._format_decimal(amount, precision=5)
        return f" (~<b>{fiat_amount}</b> {currency})"

    def _format_decimal(self, value: Decimal, *, precision: int = 4) -> str:
        if value == 0:
            return "0"
        quant = Decimal(1).scaleb(-precision)
        try:
            return format(value.quantize(quant), "f")
        except Exception:
            return format(value, "f")

    def _html_escape(self, text: str) -> str:
        return html.escape(text, quote=False)

    def _html_bold(self, text: str) -> str:
        return f"<b>{self._html_escape(text)}</b>"

    def _html_code(self, text: str) -> str:
        return f"<code>{self._html_escape(text)}</code>"

    def _html_underline(self, text: str) -> str:
        return f"<u>{self._html_escape(text)}</u>"

    def _format_source_label(self, source: str) -> str:
        source_key = (source or "").lower()
        label = self._html_code(source)
        url = SOURCE_LINKS.get(source_key)
        if url:
            href = html.escape(url, quote=True)
            return f'<a href="{href}">{label}</a>'
        return label

    async def _build_search_context(self, prompt: str, lang: str) -> Optional[str]:
        if not self.search_client:
            return None

        try:
            knowledge = await self.search_client.search(prompt)
        except Exception as exc:
            logger.exception("Tavily search failed: %s", exc)
            return None

        if not knowledge:
            return None

        header = "Hasil pencarian web:" if lang == "ID" else "Web search findings:"
        lines = [header]

        if getattr(knowledge, "answer", None):
            lines.append(knowledge.answer.strip())

        sources = getattr(knowledge, "sources", [])
        fallback = "Ringkasan tidak tersedia." if lang == "ID" else "Summary not available."
        for idx, result in enumerate(sources[:3], start=1):
            snippet = (result.snippet or "").strip().replace("\n", " ") or fallback
            title = result.title or result.url or fallback
            lines.append(f"{idx}. {title} — {snippet} (source: {result.url})")

        context = "\n".join(lines)
        logger.debug("Search context prepared: %s", context)
        return context

    def _parse_conversion(self, prompt: str) -> Optional[ConversionRequest]:
        match = _CONVERSION_PATTERN.match(prompt)
        if not match:
            return None

        amount_raw = match.group("amount")
        base = match.group("base")
        quote = match.group("quote") or "USD"

        try:
            amount = Decimal(amount_raw.replace(",", "."))
        except InvalidOperation:
            return None

        if amount <= 0:
            return None

        return ConversionRequest(amount=amount, base_symbol=base.upper(), quote_symbol=quote.upper())

    def _parse_project(self, prompt: str) -> Optional[str]:
        token = "[PROJECT]"
        if prompt.upper().startswith(token):
            return prompt[len(token):].strip()
        return None

    def _parse_gas(self, prompt: str) -> Optional[GasRequest]:
        token = "[GAS]"
        if not prompt.upper().startswith(token):
            return None
        remainder = prompt[len(token):].strip()
        if not remainder:
            return GasRequest(network=None, currency=None)

        if remainder.startswith("{") and remainder.endswith("}"):
            try:
                data = json.loads(remainder)
            except json.JSONDecodeError:
                pass
            else:
                return GasRequest(
                    network=data.get("network"),
                    currency=data.get("currency"),
                )

        cleaned = remainder.replace("=", " ")
        parts = [part for part in cleaned.split() if part]
        network = None
        currency = None
        if parts:
            if len(parts) >= 2:
                currency = parts[-1]
                network = " ".join(parts[:-1])
            else:
                network = parts[0]

        return GasRequest(network=network, currency=currency)

    def _parse_rpc(self, prompt: str) -> Optional[RpcRequest]:
        token = "[RPC]"
        if not prompt.upper().startswith(token):
            return None
        remainder = prompt[len(token):].strip()
        if not remainder:
            return RpcRequest(network=None)

        if remainder.startswith("{") and remainder.endswith("}"):
            try:
                data = json.loads(remainder)
            except json.JSONDecodeError:
                pass
            else:
                return RpcRequest(network=data.get("network"))

        cleaned = remainder.replace("=", " ")
        network = cleaned.strip() or None
        return RpcRequest(network=network)

    def _build_project_context(self, analysis: ProjectAnalysis, project_query: str) -> str:
        payload = {
            "query": project_query,
            "name": analysis.name,
            "symbol": analysis.symbol,
            "category": analysis.category,
            "stage": analysis.stage,
            "description": analysis.description,
            "sentiment": analysis.sentiment,
            "funding_total": analysis.funding_total,
            "reward_opportunities": analysis.reward_opportunities,
            "investors": analysis.investors,
            "socials": analysis.socials,
            "website": analysis.website,
            "plan_notes": analysis.plan_notes,
            "tavily_answer": analysis.tavily_answer,
            "tavily_sources": analysis.tavily_sources,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _extract_language(self, activity_id: str, prompt: str) -> tuple[str, str]:
        lang = self._language_pref.get(activity_id, _DEFAULT_LANG)
        match = _LANG_TOKEN.match(prompt)
        if match:
            lang = match.group(1).upper()
            if lang not in _SUPPORTED_LANGS:
                lang = _DEFAULT_LANG
            self._language_pref[activity_id] = lang
            prompt = prompt[match.end():].lstrip()
        else:
            self._language_pref.setdefault(activity_id, lang)
        return lang, prompt

    def _msg(self, lang: str, key: str, **kwargs) -> str:
        messages = _LANG_MESSAGES.get(lang, _LANG_MESSAGES[_DEFAULT_LANG])
        template = messages.get(key, _LANG_MESSAGES[_DEFAULT_LANG][key])
        return template.format(**kwargs)

    def _trim_history(self, history: List[Dict[str, str]]) -> None:
        max_messages = self._max_turns * 2
        if len(history) > max_messages:
            del history[: len(history) - max_messages]

    def _format_amount(self, value: Decimal) -> str:
        if value == 0:
            return "0"
        quant = Decimal("0.01") if value >= 1 else Decimal("0.000001")
        formatted = value.quantize(quant, rounding=ROUND_HALF_UP)
        return f"{formatted:,}"
