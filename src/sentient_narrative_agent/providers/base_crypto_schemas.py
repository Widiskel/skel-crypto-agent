from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class Coin(BaseModel):
    id: str
    symbol: str
    name: str
    market_cap_rank: Optional[int] = None

class TrendingCoinData(BaseModel):
    price: float
    price_change_percentage_24h: Dict[str, float]
    market_cap: str
    total_volume: str
    
class TrendingItem(Coin):
    data: Optional[TrendingCoinData] = None

class TrendingCoin(BaseModel):
    item: TrendingItem

class MarketData(BaseModel):
    current_price: Dict[str, float] = Field(default_factory=dict)
    market_cap: Dict[str, float] = Field(default_factory=dict)
    total_volume: Dict[str, float] = Field(default_factory=dict)
    price_change_percentage_24h: Optional[float] = None
    price_change_percentage_7d: Optional[float] = None
    price_change_percentage_30d: Optional[float] = None
    market_cap_rank: Optional[int] = None

class CoinDetails(Coin):
    description: Dict[str, str] = Field(default_factory=dict)
    market_data: MarketData = Field(default_factory=MarketData)