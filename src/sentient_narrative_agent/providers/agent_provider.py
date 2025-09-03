from openai import AsyncOpenAI
from typing import AsyncIterator
from loguru import logger

class AgentProvider:
    """Provider to interact with the Fireworks AI LLM."""
    def __init__(self, api_key: str, model_name: str):
        self._client = AsyncOpenAI(base_url="https://api.fireworks.ai/inference/v1", api_key=api_key)
        self._model = model_name
        self.system_prompt = (
            "You are the 'Sentient Narrative Agent.' Your primary function is to analyze news, "
            "market data, and sentiment to uncover the underlying narratives driving crypto price movements. "
            "Provide concise, data-driven summaries of these narratives. "
            "Do not provide financial advice. Your tone is objective and analytical."
        )

    async def query_stream(self, prompt: str) -> AsyncIterator[str]:
        """Sends a prompt to the model and yields the response in a stream of chunks."""
        logger.info(f"Sending prompt to LLM. Preview: '{prompt[:100]}...'")
        messages = [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": prompt}]
        stream = await self._client.chat.completions.create(
            model=self._model, messages=messages, stream=True, temperature=0.5
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content