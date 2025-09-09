import httpx
from typing import List, Dict, Any, Optional
from loguru import logger

from .base_crypto_provider import BaseCryptoProvider
from .base_crypto_schemas import Coin, TrendingCoin, CoinDetails

class CoinGeckoProvider(BaseCryptoProvider):
    def __init__(self, api_key: str):
        self._base_url = "https://api.coingecko.com/api/v3"
        self._api_key = api_key
        self._coin_list_cache: Optional[List[Coin]] = None

    async def _initialize_coin_list_cache(self):
        if self._coin_list_cache is None:
            logger.info("Initializing CoinGecko coin list cache...")
            self._coin_list_cache = await self.get_coin_list()
            logger.info(f"Coin list cache initialized with {len(self._coin_list_cache)} coins.")

    async def find_coins_by_symbol(self, symbol: str) -> List[Coin]:
        await self._initialize_coin_list_cache()
        symbol_lower = symbol.lower()
        matches = [
            coin for coin in self._coin_list_cache 
            if symbol_lower == coin.symbol.lower()
        ]
        return matches

    async def get_coin_list(self) -> List[Coin]:
        url = f"{self._base_url}/coins/list"
        params = {'x_cg_demo_api_key': self._api_key}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return [Coin(**item) for item in response.json()]

    async def get_trending(self) -> List[TrendingCoin]:
        url = f"{self._base_url}/search/trending"
        params = {'x_cg_demo_api_key': self._api_key}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return [TrendingCoin(**item) for item in response.json().get('coins', [])]

    async def get_coin_details(self, coin_id: str) -> CoinDetails:
        logger.info(f"Fetching full details for coin ID: {coin_id}")
        params = {
            'localization': 'false', 
            'tickers': 'false', 
            'community_data': 'false', 
            'developer_data': 'false',
            'sparkline': 'false',
            'x_cg_demo_api_key': self._api_key
        }
        url = f"{self._base_url}/coins/{coin_id}"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return CoinDetails(**response.json())