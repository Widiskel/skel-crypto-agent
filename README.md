# Skel Crypto Agent

## Overview

Skel Crypto Agent is an HTTP service built on top of the Sentient Agent Framework. It powers lightweight crypto conversations, on-demand price conversions, and Tavily-backed web search that can be consumed by downstream clients (such as the Telegram bot in this repository).

## Features

- Session-aware chat with Fireworks AI (20 turns of context per activity).
- Aggregated real-time pricing from CoinGecko, CoinMarketCap, Binance, Bybit, and DefiLlama.
- Crypto project intelligence that blends CryptoRank data with Tavily search highlights, complete with plan limitation messaging.
- Live gas-fee quoting for multiple networks (Ethereum, Base, BNB Chain, Linea, Polygon/"Plasma") with optional fiat conversion.
- Chainlist-backed RPC directory lookup to surface mainnet and testnet endpoints on demand.
- FastAPI server that streams responses via Server-Sent Events (`/assist`).

## Requirements

- Python 3.12+
- Fireworks API key (`FIREWORKS_API_KEY`).
- Optional: CoinGecko, CoinMarketCap, Bybit, and Tavily credentials.
- Optional: CryptoRank API key (`CRYPTORANK_API_KEY`) for richer project metadata.

## Setup

```bash
./setup.sh
cp .env.example .env
# fill in the required environment variables
```

## Run the server

```bash
./start.sh
```

By default the service listens on `http://0.0.0.0:8000/assist` and streams SSE events.

> **Vercel note:** `vercel.json` targets `main-vercel.py` with the `@vercel/python` runtime. Configure the listed environment variables in Vercel before deploying.

## Directory layout

```
skel-crypto-agent/
├── main.py
├── main-vercel.py
├── src/
│   └── skel_crypto_agent/
│       ├── agent.py
│       ├── config/
│       │   └── settings.py
│       ├── providers/
│       │   ├── agent_provider.py
│       │   ├── gas_service.py
│       │   ├── price_service.py
│       │   ├── project_analyzer.py
│       │   ├── web_search.py
│       │   └── price_sources/
│       └── utils/
│           ├── event.py
│           └── logger.py
├── requirements.txt
└── pyproject.toml
```

## Web search usage

Provide prompts that begin with `search`, `find`, or `google` (for example `search latest bitcoin etf news`). The agent will query Tavily and weave the highlights into its response.

## Project analysis

Prefix a request with `[PROJECT]`, e.g. `[PROJECT] sentient`, to gather a structured project snapshot. The output blends CryptoRank metadata (when available) with Tavily insights and includes polite notes when the current plan restricts certain data.

## Gas fee lookups

Prefix a request with `[GAS]` to retrieve live gas information. You can pass structured JSON (e.g. `[GAS]{"network":"base","currency":"IDR"}`) or a simple string such as `[GAS] base IDR`. The agent automatically pulls RPC endpoints from Chainlist, tries each option until it succeeds, and reports low/average/high fee tiers together with estimated costs for common actions (transfers, contract execution, swaps, NFT sales, bridging, borrowing). Any network listed on Chainlist is supported—just mention it by name, symbol, or chain ID (e.g. `polygon`, `matic`, `137`, `arbitrum one`). Currency defaults to USD if a requested fiat quote is unavailable.

Prefix a request with `[RPC]` (e.g. `[RPC] base`) to fetch the Chainlist RPC directory for a network. The response includes mainnet/testnet distinctions, endpoint lists, explorer links, and faucet references when available.

## Notes for Skel Helper Bot

The Skel Helper Bot lives in `skel-telegram-bot/`. Ensure the agent service is running before launching the bot so `/project`, `/gas`, and general chat requests can be fulfilled.
