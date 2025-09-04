from loguru import logger
from sentient_agent_framework import AbstractAgent, ResponseHandler, Session, Query
from typing import List, Dict
from collections import defaultdict
from sentient_narrative_agent.utils.agent_utils import format_trending_data_as_table, get_intent

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
            intent = await get_intent(prompt, history, self.model_provider)
            
            messages_for_llm = history.copy()

            if intent == "get_trending":
                await events.fetch("trending coins from CoinGecko")
                trending_data = await self.crypto_provider.get_trending()
                await events.sources(provider="CoinGecko", count=len(trending_data))
                
                table_string = format_trending_data_as_table(trending_data)
                
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