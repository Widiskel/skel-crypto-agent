from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class Coin(BaseModel):
    """Represents the basic information for a single cryptocurrency."""
    id: str
    symbol: str
    name: str
    market_cap_rank: Optional[int] = None

class TrendingCoinData(BaseModel):
    """Represents the detailed data nested within a trending coin item."""
    price: float
    price_change_percentage_24h: Dict[str, float]
    market_cap: str # Stays as string like "$99,703,583"
    total_volume: str # Stays as string like "$282,142"
    
class TrendingItem(Coin):
    """Represents the 'item' object in a trending coin response."""
    data: Optional[TrendingCoinData] = None

class TrendingCoin(BaseModel):
    """Represents a full coin object as returned by the trending endpoint."""
    item: TrendingItem

class CoinMarketData(Coin):
    """Represents detailed market data for a single cryptocurrency."""
    current_price: Optional[float] = Field(None, alias='current_price')
    market_cap: Optional[int] = Field(None, alias='market_cap')
    total_volume: Optional[int] = Field(None, alias='total_volume')
    price_change_percentage_24h: Optional[float] = Field(None, alias='price_change_percentage_24h')
    
    class Config:
        populate_by_name = True