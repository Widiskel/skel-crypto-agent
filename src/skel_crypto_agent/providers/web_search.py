from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Optional

from loguru import logger
from tavily import TavilyClient

@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str


@dataclass(slots=True)
class SearchKnowledge:
    answer: Optional[str]
    sources: List[SearchResult]


class TavilySearchClient:
    def __init__(
        self,
        api_key: str,
        *,
        search_depth: str = "advanced",
        max_results: int = 5,
    ) -> None:
        self._search_depth = search_depth if search_depth in {"basic", "advanced"} else "basic"
        self._max_results = max(1, min(max_results, 10))
        self._client = TavilyClient(api_key)

    async def close(self) -> None:
        return None

    async def search(self, query: str) -> Optional[SearchKnowledge]:
        loop = asyncio.get_running_loop()

        def _call() -> dict:
            return self._client.search(
                query=query,
                include_answer="advanced",
                search_depth=self._search_depth,
                max_results=self._max_results,
            )

        try:
            payload = await loop.run_in_executor(None, _call)
        except Exception as exc:
            logger.warning("Tavily request failed: %s", exc)
            return None

        answer = payload.get("answer")
        raw_results = payload.get("results") or []
        if not raw_results and not answer:
            logger.debug("Tavily returned no results for query: %s", query)
            return None

        parsed: List[SearchResult] = []
        for item in raw_results[: self._max_results]:
            title = item.get("title") or "(untitled)"
            url = item.get("url") or item.get("link") or ""
            snippet = item.get("content") or item.get("description") or ""
            parsed.append(SearchResult(title=title, url=url, snippet=snippet))

        return SearchKnowledge(answer=answer, sources=parsed)
