from openai import AsyncOpenAI
from typing import AsyncIterator, List, Dict
from loguru import logger

class AgentProvider:
    """Provider to interact with the Fireworks AI LLM."""
    def __init__(self, api_key: str, model_name: str):
        self._client = AsyncOpenAI(base_url="https://api.fireworks.ai/inference/v1", api_key=api_key)
        self._model = model_name
        self.system_prompt = (
            "You are the 'Sentient Narrative Agent.' Your primary function is to analyze news, "
            "market data, trending crypto data, and sentiment to uncover the underlying narratives driving crypto price movements. "
            "Provide concise, data-driven summaries of these narratives. "
            "Do not provide financial advice. Your tone is objective and analytical. "
            "Always respond in the user's language, inferred from the latest user message. If unclear, default to English."
        )

    async def query_stream(self, messages: List[Dict[str, str]]) -> AsyncIterator[str]:
        """
        Sends a structured list of messages to the model and yields the response in chunks.
        """
        full_messages = [{"role": "system", "content": self.system_prompt}] + messages
        
        logger.debug(f"Sending payload with {len(full_messages)} messages to LLM:")
        
        stream = await self._client.chat.completions.create(
            model=self._model, messages=full_messages, stream=True, temperature=0.5
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content
                
    async def query(self, messages: List[Dict[str, str]]) -> str:
        """Sends a structured list of messages and returns the full response."""
        chunks = [chunk async for chunk in self.query_stream(messages)]
        return "".join(chunks)
