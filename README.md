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

User Message: Give me today trending cryptocurrency!
Agent Response Message : The crypto market is showing some wild swings in the last 24 hours, with MYX Finance taking a f***ing nosedive of -39.87%—that s***’s brutal. On the flip side, Somnia and Aerodrome Finance are flexing with gains of +8.57% and +7.95%, respectively. Bitcoin and Ethereum are just chillin’, doing their thing with small gains. 

|   # | Name              | Symbol   | Rank   | Price (USD)   | 24h %   |
|-----|-------------------|----------|--------|---------------|---------|
|   1 | Linea             | LINEA    | #237   | $0.0235       | -2.45%  |
|   2 | Pump.fun          | PUMP     | #69    | $0.0062       | +5.10%  |
|   3 | Ondo              | ONDO     | #47    | $1.1096       | +9.27%  |
|   4 | MYX Finance       | MYX      | #73    | $11.3499      | -39.87% |
|   5 | Hyperliquid       | HYPE     | #15    | $56.5628      | +1.48%  |
|   6 | Solana            | SOL      | #5     | $233.9803     | +4.35%  |
|   7 | Ethena            | ENA      | #39    | $0.7704       | -2.41%  |
|   8 | Pudgy Penguins    | PENGU    | #64    | $0.0365       | +6.40%  |
|   9 | Ethereum          | ETH      | #2     | $4,492.7526   | +2.32%  |
|  10 | Dogecoin          | DOGE     | #8     | $0.2602       | +2.89%  |
|  11 | Bitcoin           | BTC      | #1     | $115,117.7873 | +0.78%  |
|  12 | Aerodrome Finance | AERO     | #116   | $1.2539       | +7.95%  |
|  13 | Somnia            | SOMI     | #384   | $1.0288       | +8.57%  |
|  14 | Holoworld         | HOLO     | #392   | $0.4561       | +3.77%  |
|  15 | Sui               | SUI      | #18    | $3.6506       | +0.95%  |

Conclusion: Today’s trending cryptos are led by Ondo (ONDO) with a 9.27% 24h pump, followed closely by Somnia (SOMI) and Aerodrome Finance (AERO), both flexing their gains. With 12 gainers and only 3 losers, the market’s skew is straight-up positive, but don’t get too cocky—volatility’s lurking, especially with MYX Finance (MYX) tanking -39.87% in the last 24 hours. Keep your wits about you. 

User Message: what do you think about SUI ?
Agent Response Message : Sui is sitting pretty at rank 18 with a price of $3.65. It’s had a solid 24 hours, gaining 0.86%. Over the last week, it’s up 10.50%, showing some real momentum. However, the 30-day picture isn’t as rosy, with a drop of 4.68%. That longer-term dip might give some pause, but its current trajectory looks promising.
| Name   | Rank   | Price (USD)   | 24h %   | 7d %    | 30d %   |
|--------|--------|---------------|---------|---------|---------|
| Sui    | #18    | $3.6500       | +0.86%  | +10.50% | -4.68%  |

News Headlines:
| Title                                                                                                                                          | Source                                                                                                                                                                           | Published            |
|------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------|
| Crypto News Today: BTC, ETH, XRP, BNB, SOL, DOGE, ADA, LINK, SUI (Sept. 10)                                                                    | https://cryptopanic.com/news/25145056/Crypto-News-Today-BTC-ETH-XRP-BNB-SOL-DOGE-ADA-LINK-SUI-Sept-10                                                                            | 2025-09-10T23:16:52Z |
| Price predictions 9/10: BTC, ETH, XRP, BNB, SOL, DOGE, ADA, LINK, HYPE, SUI                                                                    | https://cryptopanic.com/news/25140938/Price-predictions-910-BTC-ETH-XRP-BNB-SOL-DOGE-ADA-LINK-HYPE-SUI                                                                           | 2025-09-10T19:57:26Z |
| Sui Price Prediction: Can SUI Surge Toward $7?                                                                                                 | https://cryptopanic.com/news/25139752/Sui-Price-Prediction-Can-SUI-Surge-Toward-7                                                                                                | 2025-09-10T19:02:21Z |
| Altcoin Signals: Michaël van de Poppe Highlights APT, Sui, and Cardano Upside Potential                                                        | https://cryptopanic.com/news/25141069/Altcoin-Signals-Michael-van-de-Poppe-Highlights-APT-Sui-and-Cardano-Upside-Potential                                                       | 2025-09-10T18:00:37Z |
| SUI Price Prediction as Mysten Labs Meets SEC Ahead of ETF Decision—Is $7.5 Next?                                                              | https://cryptopanic.com/news/25136938/SUI-Price-Prediction-as-Mysten-Labs-Meets-SEC-Ahead-of-ETF-DecisionIs-75-Next                                                              | 2025-09-10T16:40:40Z |
| SUI At A Crossroads, Can It Break $3.52 And Ignite The Next Surge?                                                                             | https://cryptopanic.com/news/25132834/SUI-At-A-Crossroads-Can-It-Break-352-And-Ignite-The-Next-Surge                                                                             | 2025-09-10T14:00:59Z |
| Trader Says Bitcoin Primed To Begin ‘Vertical Acceleration’ After Breaking Out Above This Level, Updates Outlook on Ethereum, Dogecoin and Sui | https://cryptopanic.com/news/25131306/Trader-Says-Bitcoin-Primed-To-Begin-Vertical-Acceleration-After-Breaking-Out-Above-This-Level-Updates-Outlook-on-Ethereum-Dogecoin-and-Sui | 2025-09-10T11:45:11Z |
| SEC Holds Talks on Sui Blockchain Ahead of ETF Deadline                                                                                        | https://cryptopanic.com/news/25127790/SEC-Holds-Talks-on-Sui-Blockchain-Ahead-of-ETF-Deadline                                                                                    | 2025-09-10T10:30:55Z |

The crypto scene is buzzing with BTC and ETH holding steady while altcoins like SUI and APT flex their muscles. SUI’s ETF showdown with the SEC could rocket it to $7.5 if things go right, but regulation risks are real as f***. Neutral sentiment means caution, but if Bitcoin breaks out, we’re in for a wild ride—keep your eyes glued to these bad boys.

Conclusion: SUI is trending with a 24-hour gain of 0.86% and a 7-day gain of 10.50%, but it’s down 4.68% over 30 days. The news is buzzing with price predictions and SEC talks, but the overall sentiment is neutral. Keep an eye on this one. 
