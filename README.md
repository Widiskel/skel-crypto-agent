# Sentient Narrative Agent

## 📜 Overview

The **Sentient Narrative Agent** is a modular AI agent designed to analyze market narratives in the cryptocurrency space. It connects to a powerful Large Language Model (LLM) to provide insightful responses and integrates with real-time data sources to inform its analysis.

This initial version serves as a robust foundation, capable of handling general queries, fetching live trending crypto data from CoinGecko, and communicating its status through a structured event pattern. The project is built using the `sentient-agent-framework` with a clean, modular, and scalable architecture.

## ✨ Core Features

* **LLM Integration**: Connects directly to Fireworks AI to stream responses for general-purpose questions.
* **Real-time Market Data**: Fetches and displays formatted, real-time trending cryptocurrency data from the CoinGecko public API.
* **Structured Event Communication**: Uses a custom `EventBuilder` to communicate the agent's state (`START`, `FETCH`, `SOURCES`, `FINAL_RESPONSE`), allowing for a rich and interactive client-side experience.
* **Modular Provider Pattern**: External services (like the LLM and CoinGecko) are abstracted into separate "provider" classes, making the agent easy to extend with new data sources.
* **Welcome Message**: Greets the user with a welcome message on an empty initial prompt.

## ⚡ Event Pattern

Instead of returning a single, monolithic response, this agent communicates its workflow through a series of distinct events. This allows any client application to provide users with real-time feedback on the agent's progress.

The primary events include:
* **`START`**: Signals that the agent has begun processing a request.
* **`FETCH`**: Indicates that the agent is fetching data from an external source (e.g., "fetching trending coins from CoinGecko").
* **`SOURCES`**: Provides metadata about the data sources used (e.g., `{"provider": "CoinGecko", "count": 15}`).
* **`FINAL_RESPONSE`**: Delivers the final, user-facing answer, which can be a block of text or a stream of text chunks.
* **`ERROR`**: Emits a structured error message if something goes wrong.

This pattern is managed by the `EventBuilder` class in `utils/event.py`.

## 🚀 Setup and Installation

Follow these steps to set up and run the project locally.

### 1. Prerequisites
* Python 3.13+
* An active API Key from [Fireworks AI](https://fireworks.ai/).
* A Demo/Public API Key from [CoinGecko](https://www.coingecko.com/en/api).

### 2. Installation Steps

1.  **Clone the Repository**
    ```bash
    git clone [https://github.com/Widiskel/sentient-narrative-agent.git](https://github.com/Widiskel/sentient-narrative-agent.git)
    cd sentient-narrative-agent
    ```

2.  **Create and Activate Virtual Environment**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Configure Environment Variables**
    Create a `.env` file in the project root. You can copy the example file first:
    ```bash
    # cp .env.example .env 
    # nano .env
    ```
    Your `.env` file must contain the following keys:
    ```env
    FIREWORKS_API_KEY="your_fireworks_api_key_here"
    COINGECKO_API_KEY="your_coingecko_demo_key_here"
    ```

4.  **Install Dependencies**
    Install the project and all its dependencies in editable mode.
    ```bash
    pip install -e .
    ```

## ▶️ Running the Agent

Once the installation is complete, start the agent server with:
```bash
python main.py
```

Agent will run on port 8000

### ▶️ Test Sentient Agent Client

Look at sentient agent client [here](https://github.com/sentient-agi/Sentient-Agent-Client), follow setup guide and run client with 
```bash
python3 -m src.sentient_agent_client --url http://0.0.0.0:8000/assist
```