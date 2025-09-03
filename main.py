# File: main.py
from sentient_agent_framework import DefaultServer
from src.sentient_narrative_agent.config.settings import config
from src.sentient_narrative_agent.utils.logger import setup_logger
from src.sentient_narrative_agent.providers.model import ModelProvider
from src.sentient_narrative_agent.agent import AltcoinAnalystAgent

if __name__ == "__main__":
    logger = setup_logger()
    logger.info("Initializing Sentient Narrative Agent...")

    model_provider = ModelProvider(
        api_key=config.fireworks_api_key, 
        model_name=config.fireworks_model_name
    )
    agent = AltcoinAnalystAgent(
        name="Sentient Narrative Agent",
        model_provider=model_provider
    )
    server = DefaultServer(agent)
    
    logger.info("Server is running. Awaiting connections...")
    server.run()