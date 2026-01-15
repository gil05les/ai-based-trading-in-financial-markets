# Agent unit tests
import pytest
from unittest.mock import Mock, MagicMock

from backend.agents import TraderAgent, BullAgent, BearAgent
from backend.database import DatabaseClient
from backend.clients import LLMClient, FinnhubClient


@pytest.fixture
def mock_db():
    # Mock DB with default responses
    db = Mock(spec=DatabaseClient)
    db.get_recent_articles.return_value = []
    db.get_latest_snapshot.return_value = {"price": 150.0}
    db.get_recent_trades.return_value = []
    db.save_analysis_event.return_value = 1
    return db


@pytest.fixture
def mock_llm():
    # Mock LLM chat responses
    llm = Mock(spec=LLMClient)
    llm.chat_completion.return_value = '{"is_interesting": true, "reasoning": "Test", "needs_debate": false, "confidence": 75}'
    return llm


@pytest.fixture
def mock_finnhub():
    # Mock Finnhub stock data
    finnhub = Mock(spec=FinnhubClient)
    finnhub.get_stock_snapshot.return_value = {
        "ticker": "AAPL",
        "price": 150.0,
        "volume": 1000000
    }
    return finnhub


def test_trader_agent_analyze(mock_db, mock_llm, mock_finnhub):
    # Ensure trader can parse tickers
    agent = TraderAgent(mock_db, mock_llm, mock_finnhub)
    result = agent.analyze_ticker("AAPL")
    
    assert result is not None
    assert "analysis" in result
    assert result["ticker"] == "AAPL"


def test_bull_agent(mock_db, mock_llm):
    # Check bull case generation
    mock_llm.chat_completion.return_value = "This stock is great!"
    agent = BullAgent(mock_db, mock_llm)
    argument = agent.make_argument("AAPL", {})
    
    assert argument is not None
    assert len(argument) > 0


def test_bear_agent(mock_db, mock_llm):
    # Check bear case generation
    mock_llm.chat_completion.return_value = "This stock is risky!"
    agent = BearAgent(mock_db, mock_llm)
    argument = agent.make_argument("AAPL", {})
    
    assert argument is not None
    assert len(argument) > 0

