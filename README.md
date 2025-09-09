
# Sentient Narrative Agent

## 📜 Overview

The **Sentient Narrative Agent** is a sophisticated, modular AI agent designed to analyze and discuss market narratives in the cryptocurrency space. It leverages a powerful Large Language Model (LLM) for natural language understanding and generation, combined with real-time data providers to deliver insightful, context-aware responses.

This agent features an advanced architecture that includes:
* An LLM-based intent classifier to understand user requests in multiple languages.
* An internal, session-based memory manager for stateful, multi-turn conversations (including trending memory per session).
* A "tool-use" capability, allowing it to fetch and reason about real-time market data from CoinGecko.
* A structured event system (`EventBuilder`) for detailed, real-time communication with the client.

## ✨ Core Features

* **Conversational Memory**: Maintains an internal chat history for each session (`activity_id`), allowing for contextual follow-up questions.
* **LLM-Powered Intent Classification**: Intelligently determines user intent (e.g., a data request vs. a general chat question) to provide the most relevant response.
* **Hybrid Response Generation**: For data-specific queries (like "trending"), it fetches real-time data from CoinGecko, uses Python to format it into a precise table, and then instructs the LLM to generate an insightful narrative around that data.
* **Structured Event Communication**: Emits a rich set of events (`START`, `FETCH`, `PROGRESS`, `SOURCES`, `METRICS`, `FINAL_RESPONSE`, `ERROR`) so that clients can display a clear, step-by-step progress of the agent's actions.
* **Fully Modular & Scalable**: Built with a clean `src` layout and a provider pattern that makes it easy to add new data sources (like NewsAPI) or capabilities in the future.

## 🚀 Setup and Installation

Follow these steps to set up and run the project locally.

### 1. Prerequisites
* Python 3.13+
* An active API Key from [Fireworks AI](https://fireworks.ai/).
* A Demo/Public API Key from [CoinGecko](https://www.coingecko.com/en/api).

### 2. Installation Steps

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/Widiskel/sentient-narrative-agent.git
    cd sentient-narrative-agent
    ```

2.  **Create and Activate Virtual Environment**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Configure Environment Variables**
    Create a `.env` file from the provided example and add your secret keys.
    ```bash
    cp .env.example .env
    nano .env
    ```
    Your `.env` file must contain:
    ```env
    FIREWORKS_API_KEY="your_fireworks_api_key_here"
    COINGECKO_API_KEY="your_coingecko_demo_key_here"
    ```

4.  **Install Dependencies**
    Install the project and all its dependencies in editable mode using the `pyproject.toml` file.
    ```bash
    pip install -e .
    ```

## ▶️ Running the Agent

Once the installation is complete, start the agent server with:
```bash
python main.py
```

The server will run on `http://0.0.0.0:8000`.

To interact with the agent, use the [Sentient Agent Client](https://github.com/sentient-agi/Sentient-Agent-Client) or a similar tool to send `POST` requests to the `/assist` endpoint.

### Example Conversation Flow

1.  **User:** `what is trending in crypto?` → Agent fetches CoinGecko trending, saves it to session trending memory, emits SOURCES with raw JSON, and presents a narrative + table.
2.  **User:** `what do you think about SKY?` → Agent detects `SKY` in the trending memory, resolves its coin id(s) without search, fetches details directly, emits SOURCES for coin_details, and presents the analysis.
3.  **User:** `tell me more about the first one on that list` → Agent uses chat history to resolve references like "the first one".

## 📡 Event System

The agent communicates progress using structured events via `EventBuilder`. Below are the event names and payload shapes.

- START: plain text block indicating the agent started processing.
- FETCH: plain text block describing what the agent is fetching.
- PROGRESS: JSON with `{"done": number, "total": number, ...}` for long-running tasks.
- METRICS: JSON for optional telemetry (latencies, counters, etc.).
- FINAL_RESPONSE: streamed or full text response for the user.
- ERROR: JSON error payload `{"message": str, "error_code": int, "details": {...}}`.

### SOURCES Event

Emitted when the agent uses external data. Payload schema:

```json
{
  "provider": "coingecko",
  "type": "trending" | "coin_list" | "coin_details",
  "data": {} // raw JSON response from Data Sources
}
```

Types are defined by the enum:

```text
SourceType
- trending
- coin_list
- coin_details
```

Examples:
- Trending: `type = "trending"`, `data` = object returned by `/search/trending`.
- Coin List (used for symbol search fallback): `type = "coin_list"`, `data` = array returned by `/coins/list`.
- Coin Details: `type = "coin_details"`, `data` = map `{ "<coin_id>": <raw coin JSON>, ... }` for the set of coins fetched.

## 🧠 Trending Memory

When a user asks for trending, the agent saves the session’s trending data and builds a `SYMBOL → [coin_id]` map. In later turns:

- If the user mentions a symbol present in trending (e.g., `SKY` or `$SKY`), the agent resolves coin ids from this memory and fetches details directly without using a broad symbol search.
- If the symbol is not in current session trending memory, the agent falls back to an exact symbol search and emits a SOURCES event for `coin_list` used in that search.

Note: Trending responses are cached briefly on the provider to reduce rate-limits while keeping near real-time behavior.

## 🔮 Future Development

* **NewsAPI Integration**: The next logical step is to build a `NewsProvider` to fetch news articles related to trending tokens.
* **Enhanced Narrative Analysis**: Combine market data from CoinGecko with headlines from the NewsProvider to generate true, data-backed market narratives.
