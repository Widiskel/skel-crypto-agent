# Sentient Narrative Agent

## Overview

An AI agent that analyzes cryptocurrency market narratives using an LLM combined with real-time data from CoinGecko and CryptoPanic (Developer API). The agent formats data as Markdown tables, appends sources, computes a deterministic sentiment score, and adapts to the user’s language (English/Indonesian).

Highlights:
- Intent classification with an LLM and session-scoped chat history.
- Trending memory per session with resolution by symbol, name, or index.
- Coin details and trending from CoinGecko; news from CryptoPanic.
- Structured events for UI integrations (start, fetch, sources, metrics, final, error).

## Features

- Conversational memory per `activity_id`.
- Real-time data fetch and narrative generation with pre-formatted tables.
- Deterministic Overall Sentiment header (0–100) from price momentum (24h/7d/30d) and CryptoPanic bull/bear counts.
- News “Sources” uses the publisher’s `original_url` (not cryptopanic-hosted URLs).
- Language adaptation (responds in user’s language) and profanity sanitization.
- Coin resolution from trending by symbol, name, or index; fallback to CoinGecko `/search` ranked by market_cap_rank; cap to top results.
- Markdown pipe tables for technicals and news.

## Setup

Prerequisites:
- Python 3.13+
- Fireworks AI API key
- CoinGecko demo API key
- Optional: CryptoPanic Developer API key

Install:
```bash
git clone https://github.com/Widiskel/sentient-narrative-agent.git
cd sentient-narrative-agent
python3 -m venv venv && source venv/bin/activate
cp .env.example .env
pip install -e .
```

Environment variables (`.env`):
```env
FIREWORKS_API_KEY="..."
COINGECKO_API_KEY="..."
# Optional (enables news):
CRYPTOPANIC_API_KEY="..."
```

## Run

```bash
python main.py
```

Default server: `http://0.0.0.0:8000`. Use the Sentient Agent Client or any HTTP client to call `/assist`.

## Events

Emitted via `EventBuilder`:
- START, FETCH, PROGRESS, SOURCES, METRICS, FINAL_RESPONSE, ERROR

Source types:
- `trending`, `coin_list`, `coin_details`, `news`

Example:
```json
{
  "provider": "cryptopanic",
  "type": "news",
  "data": { "results": [ /* raw Developer API payload */ ] }
}
```

## Trending Memory

After fetching trending, the agent stores per-session:
- Symbol→[coin_id]
- Name→[coin_id]
- Index→coin_id

When asked “analyze $BTC”, “bagaimana soal Aethir”, or “analisa nomor 3”, it resolves to coin IDs from memory. If resolution fails, it falls back to CoinGecko `/search` and selects the top-ranked IDs.

## Sentiment & News

- CryptoPanic Developer API: uses `auth_token`, `public=true`, and `regions=en`.
- Deterministic sentiment: combines price momentum (24h/7d/30d) and counts of `filter=bullish` vs `filter=bearish` posts.
- Sources list uses `original_url` only.
- Provider is resilient: retry/backoff, brief caching, and cooldown on rate limits.

## Example Interaction Flow

Enter your message: hello
EventName.FINAL_RESPONSE
Hello! I’m here to break down the crypto narratives driving price moves. Ask about trends or any coin, and I’ll keep it concise.

Enter your message: give me information about trending cryptocurrency today
EventName.FINAL_RESPONSE
Today’s market shows strong movers and some pullbacks. Quick snapshot:

# | Name | Symbol | Rank | Price (USD) | 24h %
--- | --- | --- | --- | --- | ---
1 | Avantis | AVNT | #812 | $0.2663 | -29.11%
2 | MYX Finance | MYX | #73 | $16.7062 | +134.21%
3 | Worldcoin | WLD | #47 | $1.8844 | +28.91%
4 | OpenLedger | OPEN | #298 | $1.1322 | -26.33%
5 | Sui | SUI | #18 | $3.4774 | -0.30%

Enter your message: give me information about SUI
EventName.FINAL_RESPONSE
Overall Sentiment: Neutral (score: 49/100)

Name | Rank | Price (USD) | 24h % | 7d % | 30d %
--- | --- | --- | --- | --- | ---
Sui | #18 | $3.4700 | -0.77% | +5.58% | -9.18%

Sui holds steady with a slight 24h dip and a weekly gain, while headlines highlight ecosystem activity and a recent protocol incident.

Title | Source | Published
--- | --- | ---
Lion Group Moves Solana and Sui Holdings to Hyperliquid | https://cryptopanic.com/news/25071764/Lion-Group-Moves-Solana-and-Sui-Holdings-to-Hyperliquid | 2025-09-08T13:45:45Z
GoPlus Expands SafeToken Locker Service to Support Sui Blockchain | https://cryptopanic.com/news/25091783/GoPlus-Expands-SafeToken-Locker-Service-to-Support-Sui-Blockchain | 2025-09-08T13:01:08Z
Nemo Protocol Loses $2.4M in Sui Network Hack | https://cryptopanic.com/news/25070498/Crypto-News-Nemo-Protocol-Loses-24M-in-Sui-Network-Hack | 2025-09-08T12:02:14Z
Altcoin Shake‑Up: Which Alts Are Poised for Gains in September? | https://cryptopanic.com/news/25066835/Altcoin-Shake-Up-Which-Alts-Are-Poised-for-Biggest-Gains-in-September | 2025-09-08T10:17:59Z
