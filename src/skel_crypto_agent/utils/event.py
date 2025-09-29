from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Dict, Iterable, Protocol

from sentient_agent_framework import ResponseHandler


class _TextStream(Protocol):
    async def complete(self) -> None: ...
    def id(self) -> str: ...
    def is_complete(self) -> bool: ...
    async def emit_chunk(self, chunk: str) -> None: ...


class EventName(str, Enum):
    START = "START"
    FETCH = "FETCH"
    PROGRESS = "PROGRESS"
    SOURCES = "SOURCES"
    METRICS = "METRICS"
    FINAL_RESPONSE = "FINAL_RESPONSE"
    ERROR = "ERROR"


class SourceType(str, Enum):
    COIN_LIST = "coin_list"
    TRENDING = "trending"
    COIN_DETAILS = "coin_details"
    NEWS = "news"


async def emit_text(handler: ResponseHandler, name: EventName | str, text: str) -> None:
    await handler.emit_text_block(str(name), text)


async def emit_json(handler: ResponseHandler, name: EventName | str, data: Mapping[str, Any]) -> None:
    payload: Dict[str, Any] = dict(data)
    await handler.emit_json(str(name), payload)


async def emit_error(handler: ResponseHandler, message: str, *, code: int = 1, details: Optional[Mapping[str, Any]] = None) -> None:
    await handler.emit_error(message, error_code=code, details=dict(details or {}))


def create_stream(handler: ResponseHandler, name: EventName | str) -> _TextStream:
    return handler.create_text_stream(str(name))


async def stream_chunks(stream: _TextStream, chunks: Iterable[str]) -> None:
    for c in chunks:
        if c:
            await stream.emit_chunk(c)
    await stream.complete()


async def emit_start(handler: ResponseHandler, msg: str = "Initializing analysis…") -> None:
    await emit_text(handler, EventName.START, msg)


async def emit_fetch(handler: ResponseHandler, what: str) -> None:
    await emit_text(handler, EventName.FETCH, what)


async def emit_progress(handler: ResponseHandler, done: int, total: int, **extra: Any) -> None:
    await emit_json(handler, EventName.PROGRESS, {"done": done, "total": total, **extra})


async def emit_sources(handler: ResponseHandler, **info: Any) -> None:
    await emit_json(handler, EventName.SOURCES, info)


async def emit_metrics(handler: ResponseHandler, **metrics: Any) -> None:
    await emit_json(handler, EventName.METRICS, metrics)


async def emit_final_block(handler: ResponseHandler, text: str) -> None:
    await emit_text(handler, EventName.FINAL_RESPONSE, text)


def create_final_stream(handler: ResponseHandler) -> _TextStream:
    return create_stream(handler, EventName.FINAL_RESPONSE)


@dataclass
class EventBuilder:
    handler: ResponseHandler

    async def start(self, msg: str = "Initializing analysis…") -> None:
        await emit_start(self.handler, msg)

    async def fetch(self, what: str) -> None:
        await emit_fetch(self.handler, what)

    async def progress(self, done: int, total: int, **extra: Any) -> None:
        await emit_progress(self.handler, done, total, **extra)

    async def sources(self, provider: str, type: SourceType | str, data: Any) -> None:
        t = type.value if isinstance(type, SourceType) else str(type)
        await emit_sources(self.handler, provider=provider, type=t, data=data)

    async def metrics(self, **metrics_payload: Any) -> None:
        await emit_metrics(self.handler, **metrics_payload)

    def final_stream(self) -> _TextStream:
        return create_final_stream(self.handler)

    async def final_block(self, text: str) -> None:
        await emit_final_block(self.handler, text)
        if hasattr(self.handler, "complete"):
            await self.handler.complete()

    async def fail(self, message: str, *, code: int = 1, details: Optional[Mapping[str, Any]] = None) -> None:
        await emit_error(self.handler, message, code=code, details=details)
        if hasattr(self.handler, "complete"):
            await self.handler.complete()
