import json
import re
from loguru import logger
from typing import List, Dict, Optional
import math
from tabulate import tabulate

from sentient_narrative_agent.providers.agent_provider import AgentProvider
from sentient_narrative_agent.providers.base_crypto_schemas import CoinDetails, TrendingCoin
from sentient_narrative_agent.providers.base_news_schemas import NewsItem


def format_technical_analysis_as_table(details: List[CoinDetails]) -> str:
    headers = ["Name", "Rank", "Price (USD)", "24h %", "7d %", "30d %"]
    rows: List[List[str]] = []
    for coin in details:
        md = coin.market_data
        name = coin.name
        rank_val = getattr(coin, "market_cap_rank", None)
        if rank_val is None:
            rank_val = getattr(md, "market_cap_rank", None)
        rank = f"#{rank_val}" if rank_val else "N/A"
        price = f"${md.current_price.get('usd', 0.0):,.4f}"
        change_24h = f"{(md.price_change_percentage_24h or 0.0):+.2f}%"
        change_7d = f"{(md.price_change_percentage_7d or 0.0):+.2f}%"
        change_30d = f"{(md.price_change_percentage_30d or 0.0):+.2f}%"
        rows.append([name, rank, price, change_24h, change_7d, change_30d])
    return tabulate(rows, headers=headers, tablefmt="github")

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
    response_text = await model_provider.query(classification_messages, temperature=0.0)
    
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
    rows: List[List[str]] = []
    for i, coin in enumerate(trending_data):
        item = coin.item
        if item and item.data:
            num = str(i + 1)
            name = item.name
            symbol = item.symbol.upper()
            rank = f"#{item.market_cap_rank}" if item.market_cap_rank else "N/A"
            price = f"${item.data.price:,.4f}"
            change_24h = item.data.price_change_percentage_24h.get("usd", 0.0)
            change_str = f"{change_24h:+.2f}%"
            rows.append([num, name, symbol, rank, price, change_str])
    return tabulate(rows, headers=headers, tablefmt="github")

def format_news_as_table(items: List[NewsItem]) -> str:
    headers = ["Title", "Source", "Published"]
    rows: List[List[str]] = []
    for it in items:
        title = it.title
        source = it.source or (it.url or "-")
        published = it.published_at or "-"
        rows.append([title, source, published])
    return tabulate(rows, headers=headers, tablefmt="github")

def format_news_sources_table(items: List[NewsItem]) -> str:
    headers = ["Title", "URL"]
    sep = " | ".join(["---"] * len(headers))
    lines: List[str] = [" | ".join(headers), sep]
    for it in items:
        title = it.title
        url = it.url or "-"
        lines.append(" | ".join([title, url]))
    return "\n".join(lines)

def compute_overall_sentiment(details: List[CoinDetails], news_counts: Optional[Dict[str, int]] = None) -> Dict[str, object]:
    """
    Compute a deterministic overall sentiment from price momentum and CryptoPanic bull/bear counts.

    - Momentum component from 24h/7d/30d percentage changes (weights 0.5/0.3/0.2), squashed by tanh.
    - News component from (bull - bear) / max(1, bull + bear).
    - Combined score: 0.6*momentum + 0.4*news, mapped to 0..100.

    Returns a dict: {label: str, score: int, components: {momentum: float, news: float}}
    """
    if not details:
        return {"label": "Neutral", "score": 50, "components": {"momentum": 0.0, "news": 0.0}}

    md = getattr(details[0], "market_data", None)
    p24 = float(getattr(md, "price_change_percentage_24h", 0.0) or 0.0) if md else 0.0
    p7 = float(getattr(md, "price_change_percentage_7d", 0.0) or 0.0) if md else 0.0
    p30 = float(getattr(md, "price_change_percentage_30d", 0.0) or 0.0) if md else 0.0

    weighted = 0.5 * p24 + 0.3 * p7 + 0.2 * p30
    mom = math.tanh(weighted / 25.0)

    bull = int((news_counts or {}).get("bullish", 0) or 0)
    bear = int((news_counts or {}).get("bearish", 0) or 0)
    total = bull + bear
    news = 0.0 if total == 0 else (bull - bear) / total

    combined = 0.6 * mom + 0.4 * news
    score = int(round((combined + 1.0) * 50))
    if score < 0:
        score = 0
    if score > 100:
        score = 100
    if score >= 66:
        label = "Bullish"
    elif score <= 34:
        label = "Bearish"
    else:
        label = "Neutral"

    return {"label": label, "score": score, "components": {"momentum": mom, "news": news}}

def sanitize_text(text: str) -> str:
    """Basic profanity filter for streamed output."""
    if not text:
        return text
    replacements = {
        "fuck": "f***",
        "fucking": "f***ing",
        "shit": "s***",
        "bullshit": "b******t",
    }
    out = text
    for bad, rep in replacements.items():
        pattern = re.compile(rf"(?i)\b{re.escape(bad)}\b")
        out = pattern.sub(rep, out)
    return out

def detect_language(text: str) -> str:
    """Very light language heuristic: returns 'id' for Indonesian, else 'en'."""
    if not text:
        return 'en'
    t = text.lower()
    id_markers = [
        'tolong', 'bagaimana', 'iya', 'tidak', 'bisa', 'mohon', 'segera', 'analisa',
        'koin', 'berita', 'nomor', 'tentang', 'menurutmu', 'yang', 'dan', 'atau', 'ini', 'itu'
    ]
    for m in id_markers:
        if m in t:
            return 'id'
    return 'en'

def update_trending_memory(
    trending_memory_store: Dict[str, List],
    symbol_map_store: Dict[str, Dict[str, List[str]]],
    name_map_store: Dict[str, Dict[str, List[str]]],
    index_map_store: Dict[str, Dict[int, str]],
    activity_id: str,
    trending_data: List[TrendingCoin],
) -> None:
    symbol_map: Dict[str, List[str]] = {}
    name_map: Dict[str, List[str]] = {}
    index_map: Dict[int, str] = {}
    try:
        for idx, tc in enumerate(trending_data, start=1):
            item = getattr(tc, 'item', None)
            if not item:
                continue
            sym = str(item.symbol).upper()
            cid = str(item.id)
            symbol_map.setdefault(sym, [])
            if cid not in symbol_map[sym]:
                symbol_map[sym].append(cid)
            name = str(item.name).strip().upper()
            name_map.setdefault(name, [])
            if cid not in name_map[name]:
                name_map[name].append(cid)
            index_map[idx] = cid
    except Exception as e:
        logger.warning(f"Failed building trending symbol/name/index maps: {e}")
    trending_memory_store[activity_id] = trending_data
    symbol_map_store[activity_id] = symbol_map
    name_map_store[activity_id] = name_map
    index_map_store[activity_id] = index_map

def extract_symbol_from_prompt(prompt: str, symbols: List[str]) -> Optional[str]:
    if not prompt or not symbols:
        return None
    for sym in symbols:
        pattern = rf"(?i)(?:\$)?\b{re.escape(sym)}\b"
        if re.search(pattern, prompt):
            return sym
    return None

def extract_name_from_prompt(prompt: str, names: List[str]) -> Optional[str]:
    if not prompt or not names:
        return None
    p = prompt.strip().upper()
    for name in names:
        if name in p:
            return name
    return None

def extract_index_from_prompt(prompt: str, max_index: int) -> Optional[int]:
    if not prompt or max_index <= 0:
        return None
    patterns = [
        r"(?i)\bno\s*(\d{1,2})\b",
        r"(?i)\bnomor\s*(\d{1,2})\b",
        r"#\s*(\d{1,2})\b",
        r"(?i)\bke-\s*(\d{1,2})\b",
        r"(?i)\btop\s*(\d{1,2})\b",
        r"(?<!\d)(\d{1,2})(?!\d)",
    ]
    for pat in patterns:
        m = re.search(pat, prompt)
        if m:
            try:
                val = int(m.group(1))
                if 1 <= val <= max_index:
                    return val
            except Exception:
                pass
    return None
