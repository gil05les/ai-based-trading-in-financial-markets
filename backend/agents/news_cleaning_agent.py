# Cleans raw HTML into structured data
from typing import Dict, Any
from datetime import datetime
import structlog

from .base_agent import BaseAgent
from backend.clients import LLMClient
from backend.database.models import ArticleCleaned


class NewsCleaningAgent(BaseAgent):
    # Extracts news from HTML
    
    def __init__(self, llm_client: LLMClient):
        super().__init__(llm=llm_client)
    
    def clean_article(self, raw_html: str, raw_article_id: int) -> ArticleCleaned:
        # Get JSON from LLM
        try:
            extracted = self.llm.extract_article_json(raw_html)
            
            if extracted.get("timestamp"):
                try:
                    from dateutil import parser
                    timestamp = parser.isoparse(extracted["timestamp"])
                except:
                    timestamp = datetime.utcnow()
            else:
                timestamp = datetime.utcnow()
            
            cleaned = ArticleCleaned(
                raw_article_id=raw_article_id,
                title=extracted.get("title", "Unknown"),
                ticker=extracted.get("ticker"),
                content_text=extracted.get("content_text", ""),
                is_usable=extracted.get("is_usable", False),
                reason=extracted.get("reason"),
                timestamp=timestamp,
                llm_model=self.llm.chat_model,
                llm_response=extracted
            )
            
            self.logger.info(
                "Article cleaned",
                raw_id=raw_article_id,
                usable=cleaned.is_usable,
                ticker=cleaned.ticker
            )
            
            return cleaned
        
        except Exception as e:
            self.logger.error("Failed to clean article", raw_id=raw_article_id, error=str(e))
            return ArticleCleaned(
                raw_article_id=raw_article_id,
                title="Error",
                ticker=None,
                content_text="",
                is_usable=False,
                reason=f"Cleaning failed: {str(e)}",
                timestamp=datetime.utcnow()
            )

