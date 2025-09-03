from loguru import logger
from sentient_agent_framework import AbstractAgent, ResponseHandler, Session, Query

from .providers.agent_provider import AgentProvider
from .providers.coingecko_provider import CoinGeckoProvider
from .utils.event import EventBuilder

class NarrativeAgent(AbstractAgent):
    """
    An agent that analyzes market narratives by communicating with an LLM
    and fetching real-time crypto data, with enhanced logging and response formatting.
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

    async def assist(self, session: Session, query: Query, response_handler: ResponseHandler):
        """
        Processes user queries with improved logging and more detailed responses.
        """
        events = EventBuilder(handler=response_handler)
        request_id = session.request_id
        prompt = query.prompt
        logger.info(f"Request {request_id}: Received prompt: '{prompt}'")
        
        try:
            if not prompt:
                await events.final_block(self.welcome_message)
                return

            prompt_lower = prompt.lower()
            if "trending" in prompt_lower:
                await events.start("Analyzing crypto market trends...")
                await events.fetch("trending coins from CoinGecko")
                
                trending_data = await self.crypto_provider.get_trending()
                
                logger.debug(f"Request {request_id}: Received {len(trending_data)} trending coins data from provider.")
                
                await events.sources(provider="CoinGecko", count=len(trending_data))
                
                col_num = 3
                col_name = 20
                col_symbol = 8
                col_rank = 8
                col_price = 15
                col_24h = 10
                
                header = (
                    f"{'#':<{col_num}} {'Name':<{col_name}} {'Symbol':<{col_symbol}} "
                    f"{'Rank':<{col_rank}} {'Price (USD)':>{col_price}} {'24h %':>{col_24h}}"
                )
                separator = (
                    f"{'-'*col_num} {'-'*col_name} {'-'*col_symbol} "
                    f"{'-'*col_rank} {'-'*col_price} {'-'*col_24h}"
                )
                
                response_lines = [header, separator]
                
                for i, coin in enumerate(trending_data):
                    item = coin.item
                    if item.data:
                        num = str(i + 1)
                        name = (item.name[:col_name-3] + '...') if len(item.name) > col_name else item.name
                        symbol = f"(${item.symbol.upper()})"
                        rank = f"#{item.market_cap_rank}" if item.market_cap_rank else "N/A"
                        price = f"${item.data.price:,.4f}"
                        change_24h = item.data.price_change_percentage_24h.get('usd', 0.0)
                        change_str = f"{change_24h:+.2f}%"

                        row = (
                            f"{num:<{col_num}} {name:<{col_name}} {symbol:<{col_symbol}} "
                            f"{rank:<{col_rank}} {price:>{col_price}} {change_str:>{col_24h}}"
                        )
                        response_lines.append(row)
                
                final_response = "```\n" + "\n".join(response_lines) + "\n```"
                await events.final_block(final_response)
            
            else:
                await events.start("Engaging narrative analysis model...")
                final_stream = events.final_stream()
                async for chunk in self.model_provider.query_stream(prompt):
                    await final_stream.emit_chunk(chunk)
                await final_stream.complete()

        except Exception as e:
            logger.error(f"Request {request_id}: An error occurred: {e}", exc_info=True)
            await events.fail(f"An internal error occurred: {e}")
        finally:
            await response_handler.complete()