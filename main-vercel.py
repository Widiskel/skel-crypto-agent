import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from sentient_agent_framework import DefaultServer

from skel_crypto_agent.agent import CryptoChatAgent
from skel_crypto_agent.config.settings import config
from skel_crypto_agent.providers.agent_provider import AgentProvider
from skel_crypto_agent.providers.price_service import PriceService
from skel_crypto_agent.providers.web_search import TavilySearchClient
from skel_crypto_agent.utils.logger import setup_logger

logger = setup_logger()
logger.info("Initializing Skel Crypto Agent for Vercel…")

model_provider = AgentProvider(
    api_key=config.fireworks_api_key,
    model_name=config.fireworks_model_name,
)

price_service = PriceService(
    coingecko_api_key=config.coingecko_api_key,
    coinmarketcap_api_key=config.coinmarketcap_api_key,
)

search_client = None
if config.tavily_api_key:
    search_client = TavilySearchClient(
        api_key=config.tavily_api_key,
        search_depth=config.tavily_search_depth,
        max_results=config.tavily_max_results,
    )

agent = CryptoChatAgent(
    name="Skel Crypto Agent",
    model_provider=model_provider,
    price_service=price_service,
    search_client=search_client,
)

server = DefaultServer(agent)
app = server._app
