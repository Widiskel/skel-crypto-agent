from sentient_agent_framework import DefaultServer
from sentient_narrative_agent.providers.agent_provider import AgentProvider
from sentient_narrative_agent.providers.coingecko_provider import CoinGeckoProvider
from sentient_narrative_agent.config.settings import config
from sentient_narrative_agent.utils.logger import setup_logger
from sentient_narrative_agent.agent import NarrativeAgent

if __name__ == "__main__":
    logger = setup_logger()
    logger.info("Initializing Sentient Narrative Agent...")

    coingecko_provider = CoinGeckoProvider(api_key=config.coingecko_api_key)
    
    model_provider = AgentProvider(
        api_key=config.fireworks_api_key, 
        model_name=config.fireworks_model_name
    )
    
    agent = NarrativeAgent(
        name="Sentient Narrative Agent",
        model_provider=model_provider,
        crypto_provider=coingecko_provider
    )
    
    server = DefaultServer(agent)
    logger.info("Server is running. Awaiting connections...")
    server.run()
