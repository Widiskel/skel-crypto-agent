import asyncio
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
                
                tool_context = (
                    "You have just received real-time trending crypto data. "
                    "Present this to the user IN THE SAME LANGUAGE as the user's latest message. Start with a brief narrative summary, regarding to the data"
                    "then present the markdown table from Pre-formatted Data Table exactly as provided in the new line after the narrative."
                    f"\n\nPre-formatted Data Table:\n{table_string}"
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
                            await events.metrics(provider="cryptopanic", status=(status or "ok"))
                        except Exception as _:
                            await events.metrics(provider="cryptopanic", status="degraded")

                    overall = compute_overall_sentiment(all_details, bull_bear_counts)

                    if has_news:
                        tool_context = (
                            f"You have received technical and descriptive data for coin(s) matching '{entity}'. "
                            "Your task is to provide a concise, objective analysis IN THE SAME LANGUAGE as the user's latest message.\n"
                            "Do NOT repeat the 'Overall Sentiment' line; it will be printed before your response.\n"
                            "Base your narrative on the provided technical table and the headlines.\n"
                            "Provide a narrative summary of the key signals (no strict sentence count).\n"
                            "Present the pre-formatted technical table exactly as provided below (no added heading text).\n"
                            "Then summarize the news sentiment/themes briefly and present the 'News Headlines' table.\n"
                            "Do not use profanity. Do not provide financial advice. Keep it concise.\n\n"
                            f"{analysis_table}\n\n"
                            f"Descriptions:\n{descriptions}"
                            + (f"\n\nNews Headlines:\n{news_table}" if news_table else "")
                        )
                    else:
                        tool_context = (
                            f"You have received technical and descriptive data for coin(s) matching '{entity}'. "
                            "Your task is to provide a concise, objective analysis IN THE SAME LANGUAGE as the user's latest message.\n"
                            "Base your narrative on the provided table.\n"
                            "Provide a brief narrative summary of the key signals (no need to count sentences).\n"
                            "Present the pre-formatted technical table exactly as provided below (no added heading text).\n"
                            "Do not use profanity. Do not provide financial advice. Keep it concise.\n\n"
                            f"{analysis_table}\n\n"
                            f"Descriptions:\n{descriptions}"
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
            async for chunk in self.model_provider.query_stream(messages_for_llm):
                clean = sanitize_text(chunk)
                full_assistant_response.append(clean)
                await final_stream.emit_chunk(clean)
            final_response_text = "".join(full_assistant_response)
            if has_news and news_table and ("Title | Source | Published" not in final_response_text):
                await final_stream.emit_chunk(sanitize_text("\nNews Headlines:\n" + news_table + "\n"))
            await final_stream.complete()

            self.chat_histories[activity_id].append({"role": "user", "content": prompt})
            self.chat_histories[activity_id].append({"role": "assistant", "content": final_response_text})
        
        except Exception as e:
            logger.error(f"Request {request_id}: An error occurred: {e}", exc_info=True)
            await events.fail(f"An internal error occurred: {e}")
        finally:
            await response_handler.complete()
