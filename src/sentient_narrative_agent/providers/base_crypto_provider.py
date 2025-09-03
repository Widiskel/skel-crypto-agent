from abc import ABC, abstractmethod
from typing import List, Dict, Any
from sentient_narrative_agent.providers.base_crypto_schemas import Coin, CoinMarketData, TrendingCoin

class BaseCryptoProvider(ABC):
    """
    An abstract base class that defines a comprehensive and robust interface
    for any crypto data provider, using Pydantic models for data consistency.
    """
    
    @abstractmethod
    async def get_coin_list(self) -> List[Coin]:
        """
        Fetches the complete list of all supported cryptocurrencies.
        This list can be cached to map symbols to IDs.
        """
        pass
    
    @abstractmethod
    async def get_trending(self) -> List[TrendingCoin]:
        """
        Fetches a list of trending cryptocurrency assets.
        """
        pass

    @abstractmethod
    async def get_coin_market_data(self, coin_ids: List[str]) -> List[CoinMarketData]:
        """
        Fetches the latest market data for a list of specific coin IDs.
        """
        pass