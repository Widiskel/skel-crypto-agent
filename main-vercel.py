from sentient_agent_framework import DefaultServer
from sentient_narrative_agent.providers.agent_provider import AgentProvider
from sentient_narrative_agent.providers.coingecko_provider import CoinGeckoProvider
from sentient_narrative_agent.providers.cryptopanic_provider import CryptoPanicNewsProvider
from sentient_narrative_agent.config.settings import config
from sentient_narrative_agent.utils.logger import setup_logger
from sentient_narrative_agent.agent import NarrativeAgent

logger = setup_logger()
logger.info("Initializing Sentient Narrative Agent...")

coingecko_provider = CoinGeckoProvider(api_key=config.coingecko_api_key)
model_provider = AgentProvider(
    api_key=config.fireworks_api_key, 
    model_name=config.fireworks_model_name
)

news_provider = None
if config.cryptopanic_api_key:
    news_provider = CryptoPanicNewsProvider(api_key=config.cryptopanic_api_key)

agent = NarrativeAgent(
    name="Sentient Narrative Agent",
    model_provider=model_provider,
    crypto_provider=coingecko_provider,
    news_provider=news_provider,
)

server = DefaultServer(agent)
app = server._app