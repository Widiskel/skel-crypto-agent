from abc import ABC, abstractmethod
from typing import List
from .base_news_schemas import NewsItem


class BaseNewsProvider(ABC):
    @abstractmethod
    async def get_news(self, symbol: str, name: str, limit: int = 10) -> List[NewsItem]:
        pass

