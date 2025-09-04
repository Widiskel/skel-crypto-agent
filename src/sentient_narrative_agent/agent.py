import json
from loguru import logger
from sentient_agent_framework import AbstractAgent, ResponseHandler, Session, Query
from typing import List, Dict
from collections import defaultdict

from .providers.agent_provider import AgentProvider
from .providers.coingecko_provider import CoinGeckoProvider
from .utils.event import EventBuilder

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
        self.welcome_message = "Hello! I am the Sentient Narrative Agent. You can ask me about crypto trends or chat with me."
        self.chat_histories: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    
    def _format_trending_data_as_table(self, trending_data) -> str:
        col_num, col_name, col_symbol, col_rank, col_price, col_24h = 3, 20, 8, 8, 15, 10
        header = f"{'#':<{col_num}} {'Name':<{col_name}} {'Symbol':<{col_symbol}} {'Rank':<{col_rank}} {'Price (USD)':>{col_price}} {'24h %':>{col_24h}}"
        separator = f"{'-'*col_num} {'-'*col_name} {'-'*col_symbol} {'-'*col_rank} {'-'*col_price} {'-'*col_24h}"
        response_lines = [header, separator]
        for i, coin in enumerate(trending_data):
            item = coin.item
            if item.data:
                num = str(i + 1); name = (item.name[:col_name-3] + '...') if len(item.name) > col_name else item.name
                symbol = f"(${item.symbol.upper()})"; rank = f"#{item.market_cap_rank}" if item.market_cap_rank else "N/A"
                price = f"${item.data.price:,.4f}"; change_24h = item.data.price_change_percentage_24h.get('usd', 0.0)
                change_str = f"{change_24h:+.2f}%"
                row = f"{num:<{col_num}} {name:<{col_name}} {symbol:<{col_symbol}} {rank:<{col_rank}} {price:>{col_price}} {change_str:>{col_24h}}"
                response_lines.append(row)
        return "```\n" + "\n".join(response_lines) + "\n```"

    async def _get_intent(self, prompt: str, history: List[Dict[str, str]]) -> str:
        """Uses the LLM to classify the user's intent based on the prompt and history."""
        logger.info(f"Classifying intent for prompt: '{prompt}'")
        
        classification_prompt = (
            "You are an expert intent classifier. Analyze the user's 'LATEST MESSAGE' in the context of the 'CONVERSATION HISTORY'. "
            "Your task is to determine if the user is asking for a real-time, up-to-date list of trending cryptocurrencies, or if they are having a general conversation (which may include follow-up questions about data already provided). "
            "Respond with ONLY one of the following keywords: 'get_trending' or 'general_chat'.\n\n"
            "--- CONVERSATION HISTORY ---\n"
            f"{json.dumps(history, indent=2)}\n\n"
            "--- LATEST MESSAGE ---\n"
            f"\"{prompt}\"\n\n"
            "Intent:"
        )
        
        classification_messages = [{"role": "user", "content": classification_prompt}]
        intent = await self.model_provider.query(classification_messages)
        
        cleaned_intent = intent.strip().lower().replace("'", "").replace("\"", "")
        logger.info(f"LLM classified intent as: '{cleaned_intent}'")
        
        if "trending" in cleaned_intent:
            return "get_trending"
        return "general_chat"


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
            intent = await self._get_intent(prompt, history)
            
            messages_for_llm = history.copy()

            if intent == "get_trending":
                await events.fetch("trending coins from CoinGecko")
                trending_data = await self.crypto_provider.get_trending()
                await events.sources(provider="CoinGecko", count=len(trending_data))
                
                table_string = self._format_trending_data_as_table(trending_data)
                
                final_prompt_content = (
                    "You have just received real-time trending crypto data, which has been pre-formatted into a markdown table. "
                    "Your task is to present this information to the user. "
                    "Start with a brief, insightful, one-paragraph narrative or summary based on the data in the table (e.g., mention the top performers or any significant market movements). "
                    "After the narrative, present the markdown table exactly as provided."
                    f"\n\nPre-formatted Data Table:\n{table_string}"
                )
                messages_for_llm.append({"role": "user", "content": final_prompt_content})

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
            logger.debug(f"Updated history for Activity {activity_id}. Total turns: {len(self.chat_histories[activity_id]) // 2}")

        except Exception as e:
            logger.error(f"Request {request_id}: An error occurred: {e}", exc_info=True)
            await events.fail(f"An internal error occurred: {e}")
        finally:
            await response_handler.complete()