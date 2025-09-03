import httpx
from typing import List, Dict, Any, Optional
from loguru import logger

from .base_crypto_provider import BaseCryptoProvider
from .base_crypto_schemas import Coin, CoinMarketData, TrendingCoin

class CoinGeckoProvider(BaseCryptoProvider):
    """
    A concrete implementation for the CoinGecko PUBLIC API,
    utilizing the optional demo/public API key for better rate limits.
    """
    def __init__(self, api_key: str):
        self._base_url = "https://api.coingecko.com/api/v3"
        self._api_key = api_key
        self._coin_list_cache: Optional[List[Coin]] = None
        self._symbol_id_map: Optional[Dict[str, str]] = None

    async def _initialize_coin_list_cache(self):
        """Initializes the in-memory cache for the coin list if not already present."""
        if self._coin_list_cache is None:
            logger.info("Initializing CoinGecko coin list cache...")
            self._coin_list_cache = await self.get_coin_list()
            self._symbol_id_map = {
                coin.symbol.lower(): coin.id for coin in self._coin_list_cache
            }
            logger.info(f"Coin list cache initialized with {len(self._coin_list_cache)} coins.")

    async def find_coin_id(self, symbol: str) -> Optional[str]:
        """Finds a coin ID from a symbol using the in-memory cache."""
        await self._initialize_coin_list_cache()
        return self._symbol_id_map.get(symbol.lower())

    async def get_coin_list(self) -> List[Coin]:
        """Fetches the complete list of all supported cryptocurrencies."""
        logger.info("Fetching full coin list from CoinGecko API...")
        url = f"{self._base_url}/coins/list"
        params = {'x_cg_demo_api_key': self._api_key}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return [Coin(**item) for item in response.json()]

    async def get_trending(self) -> List[TrendingCoin]:
        """Fetches the top-7 trending coins."""
        logger.info("Fetching trending coins from CoinGecko API...")
        url = f"{self._base_url}/search/trending"
        params = {'x_cg_demo_api_key': self._api_key}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return [TrendingCoin(**item) for item in response.json().get('coins', [])]

    async def get_coin_market_data(self, coin_ids: List[str]) -> List[CoinMarketData]:
        """Fetches market data for a given list of coin IDs."""
        if not coin_ids:
            return []
            
        logger.info(f"Fetching market data for coin IDs: {coin_ids}")
        ids_param = ",".join(coin_ids)
        params = {
            'vs_currency': 'usd',
            'ids': ids_param,
            'x_cg_demo_api_key': self._api_key
        }
        url = f"{self._base_url}/coins/markets"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return [CoinMarketData(**item) for item in response.json()]