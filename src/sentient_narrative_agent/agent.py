import asyncio
import re
from loguru import logger
from sentient_agent_framework import AbstractAgent, ResponseHandler, Session, Query
from typing import List, Dict
from collections import defaultdict
from .utils.agent_utils import format_trending_data_as_table, get_intent_and_entity, format_technical_analysis_as_table

from .providers.agent_provider import AgentProvider
from .providers.coingecko_provider import CoinGeckoProvider
from .utils.event import EventBuilder, SourceType

class NarrativeAgent(AbstractAgent):
    def __init__(
        self,
        name: str,
        model_provider: AgentProvider,
        crypto_provider: CoinGeckoProvider
    ):
        super().__init__(name)
        self.model_provider = model_provider
        self.crypto_provider = crypto_provider
        self.welcome_message = "Hello! I am the Sentient Narrative Agent. You can ask me about crypto trends or for an analysis of a specific coin."
        self.chat_histories: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        self._trending_memory: Dict[str, List] = {}
        self._trending_symbol_to_ids: Dict[str, Dict[str, List[str]]] = {}

    def _update_trending_memory(self, activity_id: str, trending_data: List) -> None:
        self._trending_memory[activity_id] = trending_data
        symbol_map: Dict[str, List[str]] = defaultdict(list)
        try:
            for tc in trending_data:
                item = getattr(tc, "item", None)
                if not item:
                    continue
                sym = str(item.symbol).upper()
                cid = str(item.id)
                if cid not in symbol_map[sym]:
                    symbol_map[sym].append(cid)
        except Exception as e:
            logger.warning(f"Failed building trending symbol map: {e}")
        self._trending_symbol_to_ids[activity_id] = symbol_map

    def _extract_symbol_from_prompt(self, prompt: str, symbols: List[str]) -> str | None:
        if not prompt or not symbols:
            return None
        for sym in symbols:
            pattern = rf"(?i)(?:\$)?\b{re.escape(sym)}\b"
            if re.search(pattern, prompt):
                return sym
        return None

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
            
            if intent != "analyze_coin":
                sym_map = self._trending_symbol_to_ids.get(activity_id, {})
                candidate = self._extract_symbol_from_prompt(prompt, list(sym_map.keys()))
                if candidate:
                    intent = "analyze_coin"
                    entity = {"coin": candidate}
            
            messages_for_llm = history.copy()
            tool_context = ""

            if intent == "get_trending":
                await events.fetch("trending coins from CoinGecko")
                trending_data = await self.crypto_provider.get_trending()
                self._update_trending_memory(activity_id, trending_data)
                await events.sources(provider="coingecko", type=SourceType.TRENDING, data=self.crypto_provider.get_last_trending_raw())
                
                table_string = format_trending_data_as_table(trending_data)
                
                tool_context = (
                    "You have just received real-time trending crypto data. "
                    "Present this to the user. Start with a brief narrative summary, "
                    "then present the markdown table exactly as provided."
                    f"\n\nPre-formatted Data Table:\n{table_string}"
                )
            
            elif intent == "analyze_coin" and entity:
                sym = entity.get("coin") if isinstance(entity, dict) else None
                sym = sym.upper() if isinstance(sym, str) else None
                sym_map = self._trending_symbol_to_ids.get(activity_id, {})
                coin_ids: List[str] = []
                if sym and sym in sym_map:
                    coin_ids = sym_map[sym]
                    await events.fetch(f"Using trending memory for symbol '{sym}' → ids: {coin_ids}")
                    await events.sources(provider="coingecko", type=SourceType.TRENDING, data=self.crypto_provider.get_last_trending_raw())
                else:
                    await events.fetch(f"Searching for coins with symbol: '{sym}'")
                    matches = await self.crypto_provider.find_coins_by_symbol(sym) if sym else []
                    await events.sources(provider="coingecko", type=SourceType.COIN_LIST, data=self.crypto_provider.get_last_coin_list_raw())
                    coin_ids = [m.id for m in matches]
                
                if not coin_ids:
                    tool_context = f"You were asked to analyze '{entity}', but you could not find any cryptocurrency with that symbol. Inform the user."
                else:
                    await events.fetch(f"Fetching details for coin ID(s): {coin_ids}")
                    all_details = await asyncio.gather(*(self.crypto_provider.get_coin_details(cid) for cid in coin_ids))
                    details_raw = {cid: self.crypto_provider.get_last_coin_details_raw(cid) for cid in coin_ids}
                    await events.sources(provider="coingecko", type=SourceType.COIN_DETAILS, data=details_raw)
                    
                    analysis_table = format_technical_analysis_as_table(all_details)
                    descriptions = "\n".join([f"- {d.name}: {d.description.get('en', 'No description available.')[:200]}..." for d in all_details])

                    tool_context = (
                        f"You have received technical and descriptive data for coin(s) matching '{entity}'. "
                        "Your task is to provide a concise analysis for the user.\n"
                        "1. Start with a brief narrative summarizing the key findings. If there are multiple coins, briefly explain each based on their description.\n"
                        "2. Present the technical analysis table you've been given.\n\n"
                        f"Technical Analysis:\n{analysis_table}\n\n"
                        f"Descriptions:\n{descriptions}"
                    )

            if tool_context:
                messages_for_llm.append({"role": "user", "content": tool_context})
            else: 
                messages_for_llm.append({"role": "user", "content": prompt})
            
            await events.start("Synthesizing final response...")
            final_stream = events.final_stream()
            full_assistant_response = []
            async for chunk in self.model_provider.query_stream(messages_for_llm):
                full_assistant_response.append(chunk)
                await final_stream.emit_chunk(chunk)
            await final_stream.complete()

            final_response_text = "".join(full_assistant_response)
            self.chat_histories[activity_id].append({"role": "user", "content": prompt})
            self.chat_histories[activity_id].append({"role": "assistant", "content": final_response_text})
        
        except Exception as e:
            logger.error(f"Request {request_id}: An error occurred: {e}", exc_info=True)
            await events.fail(f"An internal error occurred: {e}")
        finally:
            await response_handler.complete()
