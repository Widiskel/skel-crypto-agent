import json
from loguru import logger
from typing import List, Dict

from sentient_narrative_agent.providers.agent_provider import AgentProvider
from sentient_narrative_agent.providers.base_crypto_schemas import CoinDetails, TrendingCoin


def format_technical_analysis_as_table(details: List[CoinDetails]) -> str:
    """Formats technical analysis data into a clean text table."""
    col_name, col_rank, col_price, col_24h, col_7d, col_30d = 20, 8, 15, 10, 10, 10
    
    header = (
        f"{'Name':<{col_name}} {'Rank':<{col_rank}} {'Price (USD)':>{col_price}} "
        f"{'24h %':>{col_24h}} {'7d %':>{col_7d}} {'30d %':>{col_30d}}"
    )
    separator = (
        f"{'-'*col_name} {'-'*col_rank} {'-'*col_price} "
        f"{'-'*col_24h} {'-'*col_7d} {'-'*col_30d}"
    )
    response_lines = [header, separator]

    for coin in details:
        md = coin.market_data
        name = (coin.name[:col_name-3] + '...') if len(coin.name) > col_name else coin.name
        rank_val = coin.market_cap_rank if hasattr(coin, "market_cap_rank") else None
        if rank_val is None:
            rank_val = getattr(md, "market_cap_rank", None)
        rank = f"#{rank_val}" if rank_val else "N/A"
        price = f"${md.current_price.get('usd', 0.0):,.4f}"
        
        change_24h = f"{md.price_change_percentage_24h or 0.0:+.2f}%"
        change_7d = f"{md.price_change_percentage_7d or 0.0:+.2f}%"
        change_30d = f"{md.price_change_percentage_30d or 0.0:+.2f}%"
        
        row = (
            f"{name:<{col_name}} {rank:<{col_rank}} {price:>{col_price}} "
            f"{change_24h:>{col_24h}} {change_7d:>{col_7d}} {change_30d:>{col_30d}}"
        )
        response_lines.append(row)
            
    return "```\n" + "\n".join(response_lines) + "\n```"

async def get_intent_and_entity(prompt: str, history: List[Dict[str, str]], model_provider: AgentProvider) -> Dict[str, str]:
    """Uses the LLM to classify intent and extract the coin entity."""
    logger.info(f"Classifying intent and entity for prompt: '{prompt}'")
    
    classification_prompt = (
        "You are an expert intent classifier and entity extractor. Analyze the user's 'LATEST MESSAGE'.\n"
        "First, classify the intent. Available intents are: 'get_trending', 'analyze_coin', 'general_chat'.\n"
        "Second, if the intent is 'analyze_coin', extract the cryptocurrency symbol (e.g., from '$SOL', extract 'SOL').\n"
        "Respond ONLY with JSON in this schema: {\"intent\": \"...\", \"entity\": {\"coin\": \"SYM\"} } for 'analyze_coin',\n"
        "or {\"intent\": \"...\", \"entity\": null} otherwise. No extra text.\n\n"
        f"LATEST MESSAGE: \"{prompt}\"\n\n"
        "JSON Response:"
    )
    
    classification_messages = [{"role": "user", "content": classification_prompt}]
    response_text = await model_provider.query(classification_messages)
    
    try:
        cleaned_json = response_text.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(cleaned_json)
        intent = result.get("intent", "general_chat")
        raw_entity = result.get("entity")
        entity_out = None
        if intent == "analyze_coin":
            symbol = None
            if isinstance(raw_entity, dict):
                symbol = raw_entity.get("coin") or raw_entity.get("symbol")
            elif isinstance(raw_entity, str):
                symbol = raw_entity
            if isinstance(symbol, str):
                symbol = symbol.replace("$", "").strip().upper()
            entity_out = {"coin": symbol} if symbol else None
        logger.info(f"LLM classified as: intent={intent}, entity={entity_out}")
        return {"intent": intent, "entity": entity_out}
    except json.JSONDecodeError:
        logger.error(f"Failed to decode JSON from intent classifier: {response_text}")
        return {"intent": "general_chat", "entity": None}

def format_trending_data_as_table(trending_data: List[TrendingCoin]) -> str:
    headers = ["#", "Name", "Symbol", "Rank", "Price (USD)", "24h %"]
    sep = " | ".join(["---"] * len(headers))
    lines: List[str] = [" | ".join(headers), sep]
    for i, coin in enumerate(trending_data):
        item = coin.item
        if item.data:
            num = str(i + 1)
            name = item.name
            symbol = item.symbol.upper()
            rank = f"#{item.market_cap_rank}" if item.market_cap_rank else "N/A"
            price = f"${item.data.price:,.4f}"
            change_24h = item.data.price_change_percentage_24h.get("usd", 0.0)
            change_str = f"{change_24h:+.2f}%"
            row = [num, name, symbol, rank, price, change_str]
            lines.append(" | ".join(row))
    return "\n".join(lines)
