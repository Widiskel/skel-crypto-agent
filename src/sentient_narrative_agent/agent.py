import json
from loguru import logger
from sentient_agent_framework import AbstractAgent, ResponseHandler, Session, Query

from .providers.agent_provider import AgentProvider
from .providers.coingecko_provider import CoinGeckoProvider
from .utils.event import EventBuilder

class NarrativeAgent(AbstractAgent):
    """
    An agent that now uses an LLM-based intent classifier to understand user
    requests before fetching data or engaging in conversation.
    """
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

    def _build_context_from_history(self, session: Session, max_turns: int = 5) -> str:
        history_lines = []
        interactions = session.get_interactions()
        recent_interactions = interactions[-max_turns:]
        for interaction in recent_interactions:
            try:
                user_prompt = interaction.request.prompt
                if user_prompt: history_lines.append(f"User: {user_prompt}")
            except (AttributeError, IndexError): continue
            assistant_response = ""
            for response in interaction.responses:
                if response.name == "FINAL_RESPONSE" and response.content:
                    assistant_response = response.content
                    break
            if assistant_response: history_lines.append(f"Assistant: {assistant_response}")
        if not history_lines: return ""
        history_text = "\n".join(history_lines)
        return f"Conversation History:\n---\n{history_text}\n---\n"
    
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
    
    async def _get_intent(self, prompt: str) -> str:
        """Uses the LLM to classify the user's intent."""
        logger.info(f"Classifying intent for prompt: '{prompt}'")
        
        classification_prompt = (
            "Analyze the user's request and classify its primary intent. "
            "Respond with ONLY one of the following keywords: "
            "'get_trending' or 'general_chat'.\n\n"
            f"User request: \"{prompt}\""
        )
        
        intent = await self.model_provider.query(classification_prompt)
        
        cleaned_intent = intent.strip().lower()
        logger.info(f"LLM classified intent as: '{cleaned_intent}'")
        
        if "trending" in cleaned_intent:
            return "get_trending"
        return "general_chat"

    async def assist(self, session: Session, query: Query, response_handler: ResponseHandler):
        events = EventBuilder(handler=response_handler)
        request_id = session.request_id
        prompt = query.prompt
        logger.info(f"Request {request_id}: Received prompt: '{prompt}'")
        
        try:
            if not prompt:
                await events.final_block(self.welcome_message)
                return

            await events.start("Analyzing request...")
            
            intent = await self._get_intent(prompt)
            
            tool_context = ""

            if intent == "get_trending":
                await events.fetch("trending coins from CoinGecko")
                trending_data = await self.crypto_provider.get_trending()
                logger.debug(f"Request {request_id}: Received {len(trending_data)} trending coins.")
                await events.sources(provider="CoinGecko", count=len(trending_data))
                
                table_string = self._format_trending_data_as_table(trending_data)
                
                tool_context = (
                    "You have just received real-time trending crypto data, which has been pre-formatted into a markdown table. "
                    "Your task is to present this information to the user. "
                    "Start with a brief, insightful, one-paragraph narrative or summary based on the data in the table (e.g., mention the top performers or any significant market movements). "
                    "After the narrative, present the markdown table exactly as provided."
                    f"\n\nPre-formatted Data Table:\n{table_string}"
                )

            history_context = self._build_context_from_history(session)
            
            if tool_context:
                full_prompt = f"{history_context}Current Task:\n{tool_context}"
            else:
                full_prompt = f"{history_context}Current Question: {prompt}"
            
            await events.start("Synthesizing final response...")
            final_stream = events.final_stream()
            async for chunk in self.model_provider.query_stream(full_prompt):
                await final_stream.emit_chunk(chunk)
            await final_stream.complete()

        except Exception as e:
            logger.error(f"Request {request_id}: An error occurred: {e}", exc_info=True)
            await events.fail(f"An internal error occurred: {e}")
        finally:
            await response_handler.complete()