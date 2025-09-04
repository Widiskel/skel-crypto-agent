
# Sentient Narrative Agent

## 📜 Overview

The **Sentient Narrative Agent** is a sophisticated, modular AI agent designed to analyze and discuss market narratives in the cryptocurrency space. It leverages a powerful Large Language Model (LLM) for natural language understanding and generation, combined with real-time data providers to deliver insightful, context-aware responses.

This agent features an advanced architecture that includes:
* An LLM-based intent classifier to understand user requests in multiple languages.
* An internal, session-based memory manager for stateful, multi-turn conversations.
* A "tool-use" capability, allowing it to fetch and reason about real-time market data from CoinGecko.
* A structured event system (`EventBuilder`) for detailed, real-time communication with the client.

## ✨ Core Features

* **Conversational Memory**: Maintains an internal chat history for each session (`activity_id`), allowing for contextual follow-up questions.
* **LLM-Powered Intent Classification**: Intelligently determines user intent (e.g., a data request vs. a general chat question) to provide the most relevant response.
* **Hybrid Response Generation**: For data-specific queries (like "trending"), it fetches real-time data from CoinGecko, uses Python to format it into a precise table, and then instructs the LLM to generate an insightful narrative around that data.
* **Structured Event Communication**: Emits a rich set of events (`INFO`, `FETCH`, `SOURCES`, `FINAL_RESPONSE`, `ERROR`) so that any client application can display a detailed, step-by-step progress of the agent's actions.
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

1.  **User:** `what is trending in crypto?` (Agent fetches data, LLM creates a narrative + table)
2.  **User:** `tell me more about the first one on that list` (Agent uses chat history to understand "the first one" and provides a detailed answer)

## 🔮 Future Development

* **NewsAPI Integration**: The next logical step is to build a `NewsProvider` to fetch news articles related to trending tokens.
* **Enhanced Narrative Analysis**: Combine market data from CoinGecko with headlines from the NewsProvider to generate true, data-backed market narratives.
