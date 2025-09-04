import json
from loguru import logger
from typing import List, Dict

from sentient_narrative_agent.providers.agent_provider import AgentProvider
from sentient_narrative_agent.providers.base_crypto_schemas import TrendingCoin


def format_trending_data_as_table(trending_data: List[TrendingCoin]) -> str:
    """Formats trending coin data into a clean, deterministic text table."""
    col_num, col_name, col_symbol, col_rank, col_price, col_24h = 3, 20, 8, 8, 15, 10
    header = f"{'#':<{col_num}} {'Name':<{col_name}} {'Symbol':<{col_symbol}} {'Rank':<{col_rank}} {'Price (USD)':>{col_price}} {'24h %':>{col_24h}}"
    separator = f"{'-'*col_num} {'-'*col_name} {'-'*col_symbol} {'-'*col_rank} {'-'*col_price} {'-'*col_24h}"
    response_lines = [header, separator]
    
    for i, coin in enumerate(trending_data):
        item = coin.item
        if item.data:
            num = str(i + 1)
            name = (item.name[:col_name-3] + '...') if len(item.name) > col_name else item.name
            symbol = f"(${item.symbol.upper()})"
            rank = f"#{item.market_cap_rank}" if item.market_cap_rank else "N/A"
            price = f"${item.data.price:,.4f}"
            change_24h = item.data.price_change_percentage_24h.get('usd', 0.0)
            change_str = f"{change_24h:+.2f}%"
            row = f"{num:<{col_num}} {name:<{col_name}} {symbol:<{col_symbol}} {rank:<{col_rank}} {price:>{col_price}} {change_str:>{col_24h}}"
            response_lines.append(row)
            
    return "```\n" + "\n".join(response_lines) + "\n```"

async def get_intent(prompt: str, history: List[Dict[str, str]], model_provider: AgentProvider) -> str:
    """Uses the LLM to classify the user's intent based on the prompt and history."""
    logger.info(f"Classifying intent for prompt: '{prompt}'")
    
    classification_prompt = (
        "You are an expert intent classifier. Analyze the user's 'LATEST MESSAGE' in the context of the 'CONVERSATION HISTORY'. "
        "Your task is to determine if the user is asking for a real-time, up-to-date list of trending cryptocurrencies, or if they are having a general conversation (which may include follow-up questions about data already provided). "
        "Respond with ONLY one of the following keywords: 'get_trending' or 'general_chat'.\n\n"
        "--- CONVERSATION HISTORY ---\n"
        f"{json.dumps(history, indent=2)}\n\n"
        "--- LATEST MESSAGE ---\n"
        f"\"{prompt}\"\n\n"
        "Intent:"
    )
    classification_messages = [{"role": "user", "content": classification_prompt}]
    intent = await model_provider.query(classification_messages)
    cleaned_intent = intent.strip().lower().replace("'", "").replace("\"", "")
    logger.info(f"LLM classified intent as: '{cleaned_intent}'")
    
    if "trending" in cleaned_intent:
        return "get_trending"
    return "general_chat"