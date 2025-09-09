from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class NewsItem(BaseModel):
    id: Optional[str] = None
    title: str
    url: str
    source: Optional[str] = None
    published_at: Optional[str] = None
    currencies: List[str] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict)
