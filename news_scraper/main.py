# News scraper orchestrator
import time
import structlog
from datetime import datetime, timezone

from backend.config import settings
from backend.database import DatabaseClient, ArticleRaw, ArticleCleaned, ArticleEmbedding
from backend.clients import LLMClient
from news_scraper.scraper import NewsScraper


logger = structlog.get_logger(__name__)


class NewsScrapingService:
    # Runs the scraper loop and handles LLM cleaning
    
    def __init__(self):
        # Setup clients and scraper
        self.db = DatabaseClient()
        self.llm = LLMClient(chat_model="gpt-5-nano-2025-08-07")  # Use nano for article cleaning
        self.scraper = NewsScraper()
        logger.info("News scraping service initialized")
    
    def process_article(self, article_meta: dict) -> None:
        # Scrape, clean, and embed a single story
        url = article_meta.get("url", "")
        if not url:
            logger.warning("Article missing URL", article=article_meta.get("title"))
            return
        
        ticker = article_meta.get("ticker", "")
        
        # Check if already processed
        if self.db.cleaned_article_exists(url, ticker):
            logger.debug("Article already cleaned, skipping", url=url[:60], ticker=ticker)
            return
        
        summary = article_meta.get("summary", "")
        
        try:
            content, scrape_success = self.scraper.scrape_article_content(url, summary)
        except Exception as e:
            logger.error("Failed to scrape article", url=url[:60], error=str(e))
            return
        
        raw_article = {
            "url": url,
            "raw_html": content,
            "ticker": ticker,
            "source_url": article_meta.get("source", "finnhub"),
            "scraped_at": datetime.utcnow(),
        }
        
        article_datetime = article_meta.get("datetime", 0)
        if article_datetime:
            try:
                article_timestamp = datetime.fromtimestamp(article_datetime, tz=timezone.utc)
            except:
                article_timestamp = datetime.utcnow()
        else:
            article_timestamp = datetime.utcnow()
        
        # Try to extract with LLM, but have a fallback if it fails
        try:
            # Pass the ticker to the LLM so it can verify the company is mentioned
            extracted = self.llm.extract_article_json(content, ticker=ticker)
            extracted["llm_model"] = self.llm.chat_model
        except Exception as e:
            logger.warning("LLM extraction failed, using fallback", url=url[:60], error=str(e))
            # Fallback: create basic cleaned article without LLM
            extracted = {
                "title": article_meta.get("title", "Unknown"),
                "ticker": ticker,
                "content_text": content[:5000] if content else "",
                "is_usable": bool(content and len(content) > 100),
                "reason": "LLM processing failed, using raw content",
                "timestamp": article_timestamp,
                "llm_model": None,
            }
        
        extracted["ticker"] = ticker or extracted.get("ticker")
        extracted["title"] = article_meta.get("title", extracted.get("title", "Unknown"))
        extracted["timestamp"] = article_timestamp
        
        if not extracted.get("content_text") and content:
            extracted["content_text"] = content[:5000]
        
        # Save both in a single transaction
        try:
            raw_id, cleaned_id = self.db.save_raw_and_cleaned_article(
                ArticleRaw(**raw_article),
                ArticleCleaned(**extracted)
            )
            
            if not raw_id or not cleaned_id:
                logger.error("Failed to save article", url=url[:60])
                return
            
            logger.info("Saved raw and cleaned article", url=url[:60], raw_id=raw_id, cleaned_id=cleaned_id, usable=extracted.get("is_usable"))
            
            # Try to get embedding, but don't fail if it doesn't work
            if extracted.get("is_usable") and extracted.get("content_text"):
                try:
                    embedding = self.llm.get_embedding(extracted["content_text"])
                    if embedding:
                        self.db.save_article_embedding(ArticleEmbedding(
                            cleaned_article_id=cleaned_id,
                            embedding=embedding
                        ))
                        logger.info("Saved article embedding", cleaned_id=cleaned_id)
                    else:
                        logger.debug("Embedding not available (skipped)", cleaned_id=cleaned_id)
                except Exception as e:
                    logger.warning("Failed to save embedding, continuing", cleaned_id=cleaned_id, error=str(e))
        
        except Exception as e:
            logger.error("Failed to save article to database", url=url[:60], error=str(e))
    
    def run_cycle(self) -> None:
        # Loop through all configured tickers
        logger.info("Starting scraping cycle", tickers=settings.stocks)
        
        articles = self.scraper.scrape_all(settings.stocks)
        logger.info("Scraped articles", count=len(articles))
        
        for article in articles:
            self.process_article(article)
            time.sleep(1)
        
        logger.info("Scraping cycle complete")
    
    def run(self, interval_minutes: int = 30) -> None:
        # Continuous loop
        logger.info("Starting news scraping service", interval_minutes=interval_minutes)
        
        while True:
            try:
                self.run_cycle()
                logger.info("Sleeping until next cycle", minutes=interval_minutes)
                time.sleep(interval_minutes * 60)
            except KeyboardInterrupt:
                logger.info("Shutting down news scraping service")
                break
            except Exception as e:
                logger.error("Error in scraping cycle", error=str(e))
                time.sleep(60)


if __name__ == "__main__":
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer()
        ]
    )
    
    service = NewsScrapingService()
    service.run(interval_minutes=30)

