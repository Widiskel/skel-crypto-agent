from typing import AsyncIterator, Dict, List, Optional

from loguru import logger
from openai import AsyncOpenAI


_DEFAULT_PROMPT = (
    "You are Skel Crypto Agent, a helpful AI assistant that chats with people about crypto topics over chat. "
    "Be concise, friendly, and adapt to the language the user employs. If the user asks for something you cannot do, "
    "explain the limitation and suggest alternative steps when possible."
)


class AgentProvider:
    """Lightweight wrapper around the Fireworks chat completion API."""

    def __init__(self, api_key: str, model_name: str, system_prompt: Optional[str] = None) -> None:
        self._client = AsyncOpenAI(base_url="https://api.fireworks.ai/inference/v1", api_key=api_key)
        self._model = model_name
        self.system_prompt = system_prompt or _DEFAULT_PROMPT

    async def query_stream(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
    ) -> AsyncIterator[str]:
        """Yield the response incrementally as chunks for streaming UIs."""

        payload = [{"role": "system", "content": self.system_prompt}] + messages
        logger.debug("Sending {} messages to model {}", len(payload), self._model)

        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=payload,
            stream=True,
            temperature=0.5 if temperature is None else float(temperature),
        )
        async for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                yield content

    async def query(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
    ) -> str:
        """Return the full response as a single string."""

        parts = [part async for part in self.query_stream(messages, temperature=temperature)]
        return "".join(parts)
