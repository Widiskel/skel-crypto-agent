from abc import ABC, abstractmethod
from typing import List
from .base_crypto_schemas import Coin, TrendingCoin, CoinDetails

class BaseCryptoProvider(ABC):
    @abstractmethod
    async def get_coin_list(self) -> List[Coin]:
        pass
    
    @abstractmethod
    async def get_trending(self) -> List[TrendingCoin]:
        pass
        
    @abstractmethod
    async def get_coin_details(self, coin_id: str) -> CoinDetails:
        pass

    @abstractmethod
    async def find_coins_by_symbol(self, symbol: str) -> List[Coin]:
        """Find coins that exactly match a given symbol (case-insensitive)."""
        pass
