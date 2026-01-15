# AI-Based Trading in Financial Markets
Multi-Agent Autonomous Trading via LLM Reasoning & Debate

This repository contains the implementation of a multi-agent autonomous trading system developed for our Bachelor Project at the University of St. Gallen (HSG). The system leverages Large Language Models (LLMs) to transform unstructured financial news into executable trading strategies through a structured, adversarial reasoning process.

## Getting Started

### Prerequisites

- Docker and Docker Compose
- API keys for Finnhub, Alpaca (Paper Trading), and OpenAI

### Configuration

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Open the `.env` file and fill in your API keys and configuration:
   - `FINNHUB_KEY`: Your Finnhub API key for market news and data.
   - `ALPACA_API_KEY`: Your Alpaca paper trading API key.
   - `ALPACA_API_SECRET`: Your Alpaca secret key.
   - `OPENAI_API_KEY`: Your OpenAI API key for a supporting LLM.
   - `STOCK_LIST`: A comma-separated list of stock tickers to monitor (e.g., AAPL,TSLA).

### Running the System

Use the provided Makefile to manage the services:

```bash
# Build the containers
make build

# Start all services in the background
make up

# View real-time logs
make logs
```

The frontend dashboard will be available at `http://localhost:8081`.

## Architecture

The system is composed of four main services orchestrated via Docker Compose:

1. **News Scraper**: Continuously monitors the configured stock list, fetches news via Finnhub, scrapes full article content, and uses an LLM to clean the data and generate vector embeddings.
2. **Trading Backend**: The core engine that runs the trading logic cycles. It coordinates the agents and maintains the trading state machine.
3. **Frontend Dashboard**: A FastAPI-based web interface and WebSocket server that provides real-time monitoring of trades, positions, and agent reasoning.
4. **Database**: A PostgreSQL instance with the pgvector extension for storing structured data and high-dimensional article embeddings.

## Trading Workflow (LangGraph)

The system uses LangGraph to manage a sophisticated state machine for every ticker analysis. The workflow is designed as a directed graph with the following steps:

1. **Analysis**: The Trader Agent scans recent headlines to determine if a ticker has significant "interesting" news.
2. **Debate**: If news is significant, the system triggers a formal debate between a Bull Agent and a Bear Agent.
3. **Proposal**: Based on the debate transcript and final consensus, the Trader Agent generates a specific trade proposal (Buy/Sell/Hold) with a confidence score.
4. **Review**: The Portfolio Manager reviews the proposal against current holdings and risk parameters.
5. **Execution**: If approved, the trade is executed via the Alpaca API and logged to the database.

## Agents

The system leverages specialized agents that inherit from a common `BaseAgent` class:

- **Trader Agent**: Acts as the primary analyst and decision-maker. It filters news at a high level and synthesizes the final trade proposal from expert debates.
- **Bull Agent**: Specialized in identifying growth catalysts, positive sentiment, and upside potential in news content.
- **Bear Agent**: Specialized in identifying risks, negative sentiment, and downside potential.
- **Portfolio Manager**: The final arbiter of risk. It ensures the system follows strict confidence thresholds and manages overall portfolio concentration.

## Development and Testing

The project includes a comprehensive test suite to ensure the stability of agents and database operations.

```bash
# Run the test suite within the Docker environment
make test
```

Logs are stored in the `./logs` directory for debugging and auditing agent reasoning.
