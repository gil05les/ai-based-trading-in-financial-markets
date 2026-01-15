# Database integration tests
import pytest
from datetime import datetime
from decimal import Decimal

from backend.database import DatabaseClient
from backend.database.models import (
    ArticleRaw,
    ArticleCleaned,
    ArticleEmbedding,
    StockSnapshot,
)


@pytest.fixture
def db_client():
    # Test DB instance
    return DatabaseClient()


def test_save_raw_article(db_client):
    # Basic INSERT for raw HTML
    article = ArticleRaw(
        url="https://example.com/test",
        raw_html="<html>Test</html>",
        ticker="AAPL"
    )
    article_id = db_client.save_raw_article(article)
    assert article_id is not None


def test_save_cleaned_article(db_client):
    # Save processed news
    raw_article = ArticleRaw(
        url="https://example.com/test2",
        raw_html="<html>Test</html>",
        ticker="TSLA"
    )
    raw_id = db_client.save_raw_article(raw_article)
    
    cleaned = ArticleCleaned(
        raw_article_id=raw_id,
        title="Test Article",
        ticker="TSLA",
        content_text="Test content",
        is_usable=True,
        reason="Test article"
    )
    cleaned_id = db_client.save_cleaned_article(cleaned)
    assert cleaned_id is not None


def test_save_stock_snapshot(db_client):
    # Save price data
    snapshot = StockSnapshot(
        ticker="AAPL",
        price=Decimal("150.50"),
        volume=1000000,
        high=Decimal("151.00"),
        low=Decimal("149.00"),
        open_price=Decimal("150.00"),
        close_price=Decimal("150.50")
    )
    snapshot_id = db_client.save_stock_snapshot(snapshot)
    assert snapshot_id is not None


def test_get_latest_snapshot(db_client):
    # Fetch most recent record
    snapshot = StockSnapshot(
        ticker="MSFT",
        price=Decimal("300.00"),
        volume=2000000
    )
    db_client.save_stock_snapshot(snapshot)
    
    latest = db_client.get_latest_snapshot("MSFT")
    assert latest is not None
    assert latest["ticker"] == "MSFT"


def test_get_recent_articles(db_client):
    # Query with time filter
    raw_article = ArticleRaw(
        url="https://example.com/test3",
        raw_html="<html>Test</html>",
        ticker="GOOGL"
    )
    raw_id = db_client.save_raw_article(raw_article)
    
    cleaned = ArticleCleaned(
        raw_article_id=raw_id,
        title="Recent Article",
        ticker="GOOGL",
        content_text="Recent content",
        is_usable=True,
        timestamp=datetime.utcnow()
    )
    db_client.save_cleaned_article(cleaned)
    
    articles = db_client.get_recent_articles(ticker="GOOGL", hours=24)
    assert len(articles) > 0

