import asyncio
import json
from loguru import logger
from sentient_agent_framework import AbstractAgent, ResponseHandler, Session, Query
from typing import List, Dict
from collections import defaultdict
from .utils.agent_utils import (
    format_trending_data_as_table,
    get_intent_and_entity,
    format_technical_analysis_as_table,
    format_news_as_table,
    compute_overall_sentiment,
    sanitize_text,
    update_trending_memory,
    extract_symbol_from_prompt,
    extract_name_from_prompt,
    extract_index_from_prompt,
)

from .providers.agent_provider import AgentProvider
from .providers.coingecko_provider import CoinGeckoProvider
from .utils.event import EventBuilder, SourceType

class NarrativeAgent(AbstractAgent):
    def __init__(
        self,
        name: str,
        model_provider: AgentProvider,
        crypto_provider: CoinGeckoProvider,
        news_provider=None
    ):
        super().__init__(name)
        self.model_provider = model_provider
        self.crypto_provider = crypto_provider
        self.news_provider = news_provider
        self.welcome_message = "Hello! I am the Sentient Narrative Agent. You can ask me about crypto trends or for an analysis of a specific coin."
        self.chat_histories: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        self._trending_memory: Dict[str, List] = {}
        self._trending_symbol_to_ids: Dict[str, Dict[str, List[str]]] = {}
        self._trending_name_to_ids: Dict[str, Dict[str, List[str]]] = {}
        self._trending_index_to_id: Dict[str, Dict[int, str]] = {}


    async def assist(self, session: Session, query: Query, response_handler: ResponseHandler):
        events = EventBuilder(handler=response_handler)
        request_id = session.request_id
        activity_id = str(session.activity_id)
        prompt = query.prompt
        
        logger.info(f"Request {request_id} for Activity {activity_id}: Received prompt: '{prompt}'")
        
        try:
            if not prompt:
                await events.start("Prepairing Greetings Message...")
                await events.start("Greet the user...")
                await events.final_block(self.welcome_message)
                return

            await events.start("Analyzing request...")
            
            history = self.chat_histories[activity_id]
            intent_data = await get_intent_and_entity(prompt, history, self.model_provider)
            intent = intent_data.get("intent")
            entity = intent_data.get("entity")
            sentiment_prefix: str | None = None
            
            if intent != "analyze_coin":
                sym_map = self._trending_symbol_to_ids.get(activity_id, {})
                name_map = self._trending_name_to_ids.get(activity_id, {})
                idx_map = self._trending_index_to_id.get(activity_id, {})
                candidate = extract_symbol_from_prompt(prompt, list(sym_map.keys()))
                if candidate:
                    intent = "analyze_coin"
                    entity = {"coin": candidate}
                else:
                    name_candidate = extract_name_from_prompt(prompt, list(name_map.keys()))
                    if name_candidate:
                        intent = "analyze_coin"
                        entity = {"coin": name_candidate}
                    else:
                        idx = extract_index_from_prompt(prompt, len(idx_map))
                        if idx:
                            intent = "analyze_coin"
                            entity = {"coin": str(idx)}
            
            messages_for_llm = history.copy()
            tool_context = ""
            has_news = False
            news_table = ""

            if intent == "get_trending":
                await events.fetch("trending coins from CoinGecko")
                trending_data = await self.crypto_provider.get_trending()
                update_trending_memory(
                    self._trending_memory,
                    self._trending_symbol_to_ids,
                    self._trending_name_to_ids,
                    self._trending_index_to_id,
                    activity_id,
                    trending_data,
                )
                await events.sources(provider="coingecko", type=SourceType.TRENDING, data=self.crypto_provider.get_last_trending_raw())
                
                table_string = format_trending_data_as_table(trending_data)

                trending_json_list = []
                try:
                    for i, tc in enumerate(trending_data, start=1):
                        item = getattr(tc, 'item', None)
                        data = getattr(item, 'data', None) if item else None
                        pct_24h = None
                        if data and getattr(data, 'price_change_percentage_24h', None):
                            pct_24h = data.price_change_percentage_24h.get('usd', None)
                        trending_json_list.append({
                            'index': i,
                            'id': getattr(item, 'id', None) if item else None,
                            'name': getattr(item, 'name', None) if item else None,
                            'symbol': (getattr(item, 'symbol', None) or '').upper() if item else None,
                            'rank': getattr(item, 'market_cap_rank', None) if item else None,
                            'price_usd': getattr(data, 'price', None) if data else None,
                            'pct_24h': pct_24h,
                        })
                except Exception:
                    pass
                try:
                    valid = [t for t in trending_json_list if isinstance(t.get('pct_24h'), (int, float))]
                    top_gainers = sorted(valid, key=lambda t: t['pct_24h'], reverse=True)[:3]
                    top_losers = sorted(valid, key=lambda t: t['pct_24h'])[:3]
                    most_volatile = sorted(valid, key=lambda t: abs(t['pct_24h']), reverse=True)[:3]
                    gainers_count = sum(1 for t in valid if t['pct_24h'] > 0)
                    losers_count = sum(1 for t in valid if t['pct_24h'] < 0)
                    unchanged_count = sum(1 for t in valid if t['pct_24h'] == 0)
                    skew = 'positive' if gainers_count > losers_count else ('negative' if losers_count > gainers_count else 'mixed')
                    trending_payload_json = json.dumps({
                        'trending': trending_json_list,
                        'top_gainers': top_gainers,
                        'top_losers': top_losers,
                        'most_volatile': most_volatile,
                        'breadth': {
                            'gainers': gainers_count,
                            'losers': losers_count,
                            'unchanged': unchanged_count,
                            'skew': skew,
                        },
                        'user_question': prompt,
                        'timeframe': '24h'
                    }, ensure_ascii=False)
                except Exception:
                    trending_payload_json = json.dumps({'trending': trending_json_list, 'user_question': prompt, 'timeframe': '24h'})

                tool_context = (
                    "You have just received real-time trending crypto data (24h snapshot). "
                    "Respond in the same language as the user's latest message. Start with a brief narrative summary grounded in the table, "
                    "then paste the following Markdown table exactly as-is. Do NOT invent metrics not present in the table. "
                    "Leave a blank line before and after the table.\n\n"
                    f"\n{table_string}\n\n"
                )
            
            elif intent == "analyze_coin" and entity:
                sym = entity.get("coin") if isinstance(entity, dict) else None
                sym = sym.upper() if isinstance(sym, str) else None
                sym_map = self._trending_symbol_to_ids.get(activity_id, {})
                name_map = self._trending_name_to_ids.get(activity_id, {})
                idx_map = self._trending_index_to_id.get(activity_id, {})
                trending_count = len(idx_map) if idx_map else 0
                coin_ids: List[str] = []
                
                if sym and sym in sym_map:
                    
                    coin_ids = (sym_map[sym] or [])[:3]
                    await events.fetch(f"Using trending memory for symbol '{sym}' → ids: {coin_ids}")
                    await events.sources(provider="coingecko", type=SourceType.TRENDING, data=self.crypto_provider.get_last_trending_raw())
                else:
                    name_candidate = None
                    if isinstance(entity, dict) and isinstance(entity.get("coin"), str):
                        name_candidate = entity.get("coin").strip().upper()
                    if name_candidate and name_candidate in name_map:
                        coin_ids = (name_map[name_candidate] or [])[:3]
                        await events.fetch(f"Using trending memory for name '{name_candidate}' → ids: {coin_ids}")
                        await events.sources(provider="coingecko", type=SourceType.TRENDING, data=self.crypto_provider.get_last_trending_raw())
                    if not coin_ids and trending_count:
                        idx = extract_index_from_prompt(prompt, trending_count)
                        if idx and idx in idx_map:
                            coin_ids = [idx_map[idx]]
                            await events.fetch(f"Using trending memory for index #{idx} → id: {coin_ids}")
                            await events.sources(provider="coingecko", type=SourceType.TRENDING, data=self.crypto_provider.get_last_trending_raw())
                    if not coin_ids:
                        await events.fetch(f"Searching for coins with symbol: '{sym}'")
                        matches = await self.crypto_provider.find_coins_by_symbol(sym) if sym else []
                        await events.sources(provider="coingecko", type=SourceType.COIN_LIST, data=self.crypto_provider.get_last_coin_list_raw())
                        ranked = await self.crypto_provider.ranked_ids_by_symbol(sym, limit=3) if sym else []
                        if ranked:
                            coin_ids = ranked
                        else:
                            coin_ids = [m.id for m in matches[:3]]
                
                if not coin_ids:
                    tool_context = f"You were asked to analyze '{entity}', but you could not find any cryptocurrency with that symbol. Inform the user."
                else:
                    await events.fetch(f"Fetching details for coin ID(s): {coin_ids}")
                    all_details = await asyncio.gather(*(self.crypto_provider.get_coin_details(cid) for cid in coin_ids))
                    details_raw = {cid: self.crypto_provider.get_last_coin_details_raw(cid) for cid in coin_ids}
                    await events.sources(provider="coingecko", type=SourceType.COIN_DETAILS, data=details_raw)
                    
                    analysis_table = format_technical_analysis_as_table(all_details)
                    descriptions = "\n".join([f"- {d.name}: {d.description.get('en', 'No description available.')[:200]}..." for d in all_details])

                    news_table = ""
                    has_news = False
                    bull_bear_counts = None
                    news_json_list = []
                    if self.news_provider and sym:
                        try:
                            news_sym = None
                            if all_details and getattr(all_details[0], 'symbol', None):
                                news_sym = str(all_details[0].symbol).upper()
                            else:
                                news_sym = sym
                            await events.fetch(f"fetching news for {news_sym} from CryptoPanic...")
                            news_items = await self.news_provider.get_news(news_sym, all_details[0].name if all_details else news_sym, limit=8)
                            raw = None
                            if hasattr(self.news_provider, "get_last_raw"):
                                raw = self.news_provider.get_last_raw(news_sym, limit=8)
                            status = None
                            if raw is not None:
                                await events.sources(provider="cryptopanic", type=SourceType.NEWS, data=raw)
                            if hasattr(self.news_provider, "get_last_status"):
                                status = self.news_provider.get_last_status()
                                await events.metrics(provider="cryptopanic", status=status)
                            if news_items:
                                news_table = format_news_as_table(news_items)
                                has_news = True
                                try:
                                    for it in news_items:
                                        news_json_list.append({
                                            'title': getattr(it, 'title', None),
                                            'source': getattr(it, 'source', None),
                                            'url': getattr(it, 'url', None),
                                            'published_at': getattr(it, 'published_at', None),
                                        })
                                except Exception:
                                    pass
                            try:
                                if hasattr(self.news_provider, 'get_bull_bear_counts'):
                                    bull_bear_counts = await self.news_provider.get_bull_bear_counts(news_sym)
                                    await events.metrics(provider="cryptopanic", **{"bull_bear_counts": bull_bear_counts})
                            except Exception:
                                bull_bear_counts = None
                            await events.metrics(provider="cryptopanic", status=(status or "ok"))
                        except Exception as _:
                            await events.metrics(provider="cryptopanic", status="degraded")

                    overall = compute_overall_sentiment(all_details, bull_bear_counts)

                    try:
                        llm_coins = []
                        for d in all_details:
                            md = getattr(d, 'market_data', None)
                            rank_val = getattr(d, 'market_cap_rank', None) or (getattr(md, 'market_cap_rank', None) if md else None)
                            price_usd = md.current_price.get('usd', None) if md and getattr(md, 'current_price', None) else None
                            llm_coins.append({
                                'name': getattr(d, 'name', None),
                                'symbol': getattr(d, 'symbol', None),
                                'rank': rank_val,
                                'price_usd': price_usd,
                                'pct_24h': getattr(md, 'price_change_percentage_24h', None) if md else None,
                                'pct_7d': getattr(md, 'price_change_percentage_7d', None) if md else None,
                                'pct_30d': getattr(md, 'price_change_percentage_30d', None) if md else None,
                            })
                        llm_data_json = json.dumps({'coins': llm_coins}, ensure_ascii=False)
                    except Exception:
                        llm_data_json = json.dumps({'coins': []})

                    guidance_common = (
                        f"You have received technical and descriptive data for coin(s) matching '{entity}'. "
                        "Your task is to provide a concise, objective analysis IN THE SAME LANGUAGE as the user's latest message.\n"
                        "Ground your statements ONLY on the exact metrics provided below; do not invent or assume values.\n"
                        "If 7d or 30d percentage is null (not provided), explicitly state that data for that timeframe is not available and DO NOT claim an increase/decrease for it.\n"
                        "Use normal paragraphs (no tables).\n\n"
                        f"COIN_DATA_JSON:\n{llm_data_json}\n"
                    )

                    if has_news:
                        tool_context = (
                            guidance_common +
                            "Do NOT repeat the 'Overall Sentiment' line; it will be printed before your response.\n"
                            "Focus this narrative on technical analysis only: reference rank, price, and 24h/7d/30d performance if available. Do not summarize news here.\n"
                        )
                    else:
                        tool_context = guidance_common

            if not tool_context and intent not in ("get_trending", "analyze_coin"):
                tool_context = (
                    "Respond in the same language as the user's latest message. Use normal paragraphs for text.\n"
                    "When you include tables, use GitHub-Flavored Markdown with a header row, a separator row, and one data row per line.\n"
                    "Leave a blank line before and after each table.\n\n"
                    f"User message:\n{prompt}"
                )
            if tool_context:
                messages_for_llm.append({"role": "user", "content": tool_context})
            else:
                messages_for_llm.append({"role": "user", "content": prompt})
            
            await events.start("Synthesizing final response...")
            final_stream = events.final_stream()
            full_assistant_response = []
            if has_news:
                header = f"Overall Sentiment: {overall['label']} (score: {overall['score']}/100)\n\n"
                await final_stream.emit_chunk(sanitize_text(header))
            async for chunk in self.model_provider.query_stream(messages_for_llm, temperature=0.0):
                clean = sanitize_text(chunk)
                full_assistant_response.append(clean)
                await final_stream.emit_chunk(clean)
            final_response_text = "".join(full_assistant_response)

            if 'analysis_table' in locals():
                def _build_tech_narr():
                    try:
                        d = all_details[0]
                        md = d.market_data
                        name = d.name
                        rank_val = getattr(d, 'market_cap_rank', None) or getattr(md, 'market_cap_rank', None)
                        rank = f"#{rank_val}" if rank_val else "N/A"
                        price = f"${md.current_price.get('usd', 0.0):,.4f}"
                        c24 = md.price_change_percentage_24h
                        c7 = md.price_change_percentage_7d
                        c30 = md.price_change_percentage_30d
                        def _fmt(val):
                            return "N/A" if val is None else f"{val:+.2f}%"
                        return (
                            f"{name} currently ranks {rank} at {price}. "
                            f"Change: 24h {_fmt(c24)}, 7d {_fmt(c7)}, 30d {_fmt(c30)}."
                        )
                    except Exception:
                        return ""
                has_paragraph = any(line.strip() and '|' not in line for line in final_response_text.splitlines())
                if not has_paragraph:
                    tech_narr = _build_tech_narr()
                    if tech_narr:
                        await final_stream.emit_chunk(sanitize_text("\n" + tech_narr + "\n\n"))
                await final_stream.emit_chunk(sanitize_text("\n" + analysis_table + "\n\n"))
                if has_news and news_table:
                    await final_stream.emit_chunk(sanitize_text("News Headlines:\n" + news_table + "\n\n"))
                    news_context = (
                        "Write a brief narrative analyzing the news headlines above. "
                        "Connect these headlines to the current market context and to the overall sentiment provided earlier. "
                        "Highlight key drivers, risks, and likely near-term implications. "
                        "Respond in the same language as the user's latest message. "
                        "Do not include any tables or lists; use 2–5 concise sentences.\n\n"
                        f"Overall Sentiment: {overall['label']} (score: {overall['score']}/100)\n\n"
                        f"News Headlines Table:\n{news_table}"
                    )
                    news_messages = self.chat_histories[activity_id].copy()
                    news_messages.append({"role": "user", "content": news_context})
                    async for chunk in self.model_provider.query_stream(news_messages, temperature=0.5):
                        await final_stream.emit_chunk(sanitize_text(chunk))

                try:
                    conclusion_payload = json.dumps({
                        'coins': json.loads(llm_data_json).get('coins', []),
                        'news': news_json_list,
                        'overall': overall,
                        'user_question': prompt,
                    }, ensure_ascii=False)
                except Exception:
                    conclusion_payload = json.dumps({'coins': [], 'news': [], 'overall': overall, 'user_question': prompt})

                conclusion_instructions = (
                    "Using only the JSON below, write a concise conclusion that directly answers the user's question. "
                    "Tie together price action (24h/7d/30d if available) and the news context. "
                    "Do NOT invent numbers or claims; if some timeframe is missing, state that it's not available. "
                    "Respond in the user's language inferred from the user's message. Start with a single-line header meaning 'Conclusion:' in that language (e.g., 'Kesimpulan:' in Indonesian, 'Conclusion:' in English), then write 2–4 sentences. "
                    "Avoid tables or lists in your response.\n\n"
                    f"DATA_JSON:\n{conclusion_payload}\n"
                )
                conclusion_messages = self.chat_histories[activity_id].copy()
                conclusion_messages.append({"role": "user", "content": conclusion_instructions})
                await final_stream.emit_chunk("\n\n")
                async for chunk in self.model_provider.query_stream(conclusion_messages, temperature=0.0):
                    await final_stream.emit_chunk(sanitize_text(chunk))

            if 'trending_payload_json' in locals():
                trending_conclusion_instructions = (
                    "Using only the JSON below, write a concise conclusion that directly answers the user's question about today's trending cryptocurrencies. "
                    "Summarize the key movers (24h), use the 'breadth' field to describe whether gainers or losers dominate, and add a brief volatility caution. "
                    "If the user's question mentions a specific coin present in the list, address it explicitly using its 24h % from the JSON. "
                    "Do NOT speculate about why an asset is 'top 1' unless the JSON provides a reason; if not provided, state that the list is a 24h trending snapshot and the specific reason is not included. "
                    "Respond in the user's language inferred from the user's message. Start with a single-line header meaning 'Conclusion:' in that language (e.g., 'Kesimpulan:' in Indonesian, 'Conclusion:' in English), then write 2–4 sentences. "
                    "Avoid tables or lists in your response. Do not provide financial advice.\n\n"
                    f"DATA_JSON:\n{trending_payload_json}\n"
                )
                trending_conclusion_messages = self.chat_histories[activity_id].copy()
                trending_conclusion_messages.append({"role": "user", "content": trending_conclusion_instructions})
                await final_stream.emit_chunk("\n\n")
                async for chunk in self.model_provider.query_stream(trending_conclusion_messages, temperature=0.0):
                    await final_stream.emit_chunk(sanitize_text(chunk))
            await final_stream.complete()

            self.chat_histories[activity_id].append({"role": "user", "content": prompt})
            self.chat_histories[activity_id].append({"role": "assistant", "content": final_response_text})
        
        except Exception as e:
            logger.error(f"Request {request_id}: An error occurred: {e}", exc_info=True)
            await events.fail(f"An internal error occurred: {e}")
        finally:
            await response_handler.complete()
