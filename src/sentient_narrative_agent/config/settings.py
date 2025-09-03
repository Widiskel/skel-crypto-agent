import os
from dotenv import load_dotenv

class Config:
    """A centralized configuration class to manage environment variables."""
    def __init__(self):
        load_dotenv()
        
        # --- Model Provider (Fireworks AI) ---
        self.fireworks_api_key: str = self._get_required_env("FIREWORKS_API_KEY")
        self.fireworks_model_name: str = "sentientfoundation/dobby-unhinged-llama-3-3-70b-new"

        # --- NEW: Crypto Provider (CoinGecko) ---
        self.coingecko_api_key: str = self._get_required_env("COINGECKO_API_KEY")

    def _get_required_env(self, var_name: str) -> str:
        """Fetches a required environment variable."""
        value = os.getenv(var_name)
        if not value:
            raise ValueError(f"Error: Environment variable '{var_name}' is not set.")
        return value

config = Config()