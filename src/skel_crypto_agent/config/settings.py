import os
from typing import Optional

from dotenv import load_dotenv


class Config:
    """Loads configuration required by the chat agent."""

    def __init__(self) -> None:
        load_dotenv()

        self.fireworks_api_key: str = self._get_required_env("FIREWORKS_API_KEY")
        self.fireworks_model_name: str = os.getenv(
            "FIREWORKS_MODEL_NAME",
            "sentientfoundation/dobby-unhinged-llama-3-3-70b-new",
        )

        self.coingecko_api_key: Optional[str] = os.getenv("COINGECKO_API_KEY")
        self.coinmarketcap_api_key: Optional[str] = os.getenv("COINMARKETCAP_API_KEY")
        self.bybit_api_key: Optional[str] = os.getenv("BYBIT_API_KEY")
        self.bybit_api_secret: Optional[str] = os.getenv("BYBIT_API_SECRET")

        self.tavily_api_key: Optional[str] = os.getenv("TAVILY_API_KEY")
        depth = os.getenv("TAVILY_SEARCH_DEPTH", "basic").lower()
        self.tavily_search_depth: str = depth if depth in {"basic", "advanced"} else "basic"
        try:
            self.tavily_max_results: int = max(1, min(int(os.getenv("TAVILY_MAX_RESULTS", "5")), 10))
        except ValueError:
            self.tavily_max_results = 5

        self.cryptorank_api_key: Optional[str] = os.getenv("CRYPTORANK_API_KEY")

    def _get_required_env(self, var_name: str) -> str:
        value = os.getenv(var_name)
        if not value:
            raise ValueError(f"Error: Environment variable '{var_name}' is not set.")
        return value


config = Config()
