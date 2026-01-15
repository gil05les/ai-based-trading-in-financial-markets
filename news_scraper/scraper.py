# Finnhub API and HTML content fetcher
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import structlog
import requests
import time
from bs4 import BeautifulSoup

from backend.config import settings


logger = structlog.get_logger(__name__)


class NewsScraper:
    # Gets article metadata and full text
    
    def __init__(self):
        # Configure requests session
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        self.finnhub_key = settings.finnhub_key
        logger.info("News scraper initialized")
    
    def fetch_news_for_ticker(self, ticker: str) -> List[Dict[str, Any]]:
        # Get last 24h news from Finnhub
        today = datetime.now(timezone.utc)
        yesterday = today - timedelta(days=1)
        
        url = (
            f"https://finnhub.io/api/v1/company-news?"
            f"symbol={ticker}&from={yesterday.strftime('%Y-%m-%d')}&to={today.strftime('%Y-%m-%d')}"
            f"&token={self.finnhub_key}"
        )
        
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            news_items = response.json()
            
            articles = []
            for item in news_items[:20]:
                articles.append({
                    "url": item.get("url", ""),
                    "title": item.get("headline", "No headline"),
                    "ticker": ticker,
                    "summary": item.get("summary", ""),
                    "datetime": item.get("datetime", 0),
                    "source": "finnhub"
                })
            
            logger.info("Fetched Finnhub news", ticker=ticker, count=len(articles))
            return articles
        except Exception as e:
            logger.error("Failed to fetch Finnhub news", ticker=ticker, error=str(e))
            return []
    
    
    def scrape_article_content(self, url: str, summary: str = "") -> tuple[str, bool]:
        # Extract plain text from article URL
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            paragraphs = soup.find_all(["p", "article", "div"])
            content = "\n".join([
                p.get_text(strip=True) for p in paragraphs 
                if len(p.get_text(strip=True)) > 40
            ])
            
            if not content or not content.strip():
                logger.debug("No content found, using summary", url=url[:60])
                return (summary if summary else "No content available", False)
            
            if len(content) > 10000:
                content = content[:10000]
                logger.debug("Truncated content", url=url[:60])
            
            return (content, True)
        except Exception as e:
            logger.warning("Failed to scrape article", url=url[:60], error=str(e))
            return (summary if summary else "No content available", False)
    
    def scrape_all(self, tickers: List[str]) -> List[Dict[str, Any]]:
        # Batch fetch for multiple symbols
        all_articles = []
        
        for ticker in tickers:
            articles = self.fetch_news_for_ticker(ticker)
            all_articles.extend(articles)
            time.sleep(1)
        
        logger.info("News fetching complete", total_articles=len(all_articles))
        return all_articles

