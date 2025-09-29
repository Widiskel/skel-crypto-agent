import os
import sys
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sentient_agent_framework import DefaultServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from skel_crypto_agent.agent import CryptoChatAgent
from skel_crypto_agent.config.settings import config
from skel_crypto_agent.providers.agent_provider import AgentProvider
from skel_crypto_agent.providers.price_service import PriceService
from skel_crypto_agent.providers.project_analyzer import ProjectAnalyzer
from skel_crypto_agent.providers.web_search import TavilySearchClient
from skel_crypto_agent.providers.gas_service import GasService
from skel_crypto_agent.utils.logger import setup_logger


if __name__ == "__main__":
    logger = setup_logger()
    logger.info("Initializing Skel Crypto Agent server…")

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

    project_analyzer = ProjectAnalyzer(
        api_key=config.cryptorank_api_key,
        tavily_client=search_client,
    )

    gas_service = GasService(price_service=price_service)

    agent = CryptoChatAgent(
        name="Skel Crypto Agent",
        model_provider=model_provider,
        price_service=price_service,
        search_client=search_client,
        project_analyzer=project_analyzer,
        gas_service=gas_service,
    )

    server = DefaultServer(agent)

    favicon_dir = Path(__file__).resolve().parent / "favicon"
    if favicon_dir.exists():
        app = server._app
        app.mount("/favicon", StaticFiles(directory=str(favicon_dir)), name="favicon")
        favicon_path = favicon_dir / "favicon.ico"
        if favicon_path.exists():

            @app.get("/favicon.ico")
            async def favicon() -> FileResponse:  # type: ignore[override]
                return FileResponse(favicon_path)

    logger.info("Server is running. Awaiting connections…")
    try:
        server.run()
    finally:
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            if search_client:
                try:
                    loop.run_until_complete(search_client.close())
                except RuntimeError as exc:  # pragma: no cover - defensive
                    logger.debug("Ignoring search client close error: {}", exc)
            try:
                loop.run_until_complete(project_analyzer.close())
            except RuntimeError as exc:  # pragma: no cover - defensive
                logger.debug("Ignoring project analyzer close error: {}", exc)
            try:
                loop.run_until_complete(gas_service.close())
            except RuntimeError as exc:  # pragma: no cover - defensive
                logger.debug("Ignoring gas service close error: {}", exc)
            loop.run_until_complete(price_service.close())
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            loop.close()
