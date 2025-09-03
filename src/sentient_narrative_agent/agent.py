from loguru import logger
from sentient_agent_framework import AbstractAgent, Session, Query, ResponseHandler
from .providers.model import ModelProvider

class AltcoinAnalystAgent(AbstractAgent):
    """
    An agent that communicates with an LLM, supporting streaming
    and a welcome message, based on the official framework interface.
    """
    def __init__(self, name: str, model_provider: ModelProvider):
        super().__init__(name)
        self.model_provider = model_provider
        self.welcome_message = "Hello! I am the Sentient Narrative Agent. How can I help you today?"

    async def assist(self, session: Session, query: Query, response_handler: ResponseHandler):
        """Processes user queries according to the framework's interface."""
        request_id = session.request_id
        prompt = query.prompt
        
        logger.info(f"Request {request_id}: Received prompt: '{prompt}'")
        
        try:
            if not prompt:
                logger.info(f"Request {request_id}: Empty prompt, sending welcome message.")
                await response_handler.emit_text_block("FINAL_RESPONSE", self.welcome_message)
                return

            final_response_stream = response_handler.create_text_stream("FINAL_RESPONSE")
            
            async for chunk in self.model_provider.query_stream(prompt):
                await final_response_stream.emit_chunk(chunk)
            
            await final_response_stream.complete()

        except Exception as e:
            logger.error(f"Request {request_id}: An error occurred: {e}", exc_info=True)
            await response_handler.emit_text_block("ERROR", f"An internal error occurred: {e}")
        finally:
            await response_handler.complete()
            logger.info(f"Request {request_id}: Response completed.")