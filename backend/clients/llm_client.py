# OpenAI wrapper for embeddings and chat
from typing import List, Dict, Any, Optional
import json
import time
import threading
import structlog
from openai import OpenAI
from openai import APIError as OpenAIAPIError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from backend.config import settings


logger = structlog.get_logger(__name__)


class RateLimiter:
    # Simple rate limiting logic
    
    def __init__(self, max_calls: int, period_seconds: int, db_client=None):
        # Tracks call frequency
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self.min_interval = period_seconds / max_calls  # Minimum seconds between calls
        self.last_call_time = 0.0
        self.lock = threading.Lock()
        self.db_client = db_client
        logger.info("Rate limiter initialized", max_calls=max_calls, period_seconds=period_seconds, min_interval=self.min_interval, shared=db_client is not None)
    
    def wait_if_needed(self):
        # Block if over limit
        with self.lock:
            current_time = time.time()
            time_since_last_call = current_time - self.last_call_time
            
            if time_since_last_call < self.min_interval:
                sleep_time = self.min_interval - time_since_last_call
                logger.debug("Rate limiting", sleep_time=sleep_time, calls_per_minute=self.max_calls)
                time.sleep(sleep_time)
            
            self.last_call_time = time.time()


class LLMClient:
    # OpenAI interaction
    
    def __init__(self, chat_model: Optional[str] = None):
        # Setup OpenAI and limiter
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.embedding_model = "text-embedding-3-small"
        self.chat_model = chat_model or "gpt-5-nano-2025-08-07"  # Default to nano
        # Rate limiter: OpenAI paid tiers have high limits, but keep conservative rate limiting
        # Adjust based on your OpenAI tier (free: 3 RPM, paid: much higher)
        self.rate_limiter = RateLimiter(max_calls=1000, period_seconds=60)
        logger.info("LLM client initialized", chat_model=self.chat_model, embedding_model=self.embedding_model, rate_limit="1000 calls/minute")
    
    def get_embedding(self, text: str) -> Optional[List[float]]:
        # Get text vector
        # Rate limit: wait if needed
        self.rate_limiter.wait_if_needed()
        
        try:
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=text
            )
            embedding = response.data[0].embedding
            logger.debug("Generated embedding", text_length=len(text))
            return embedding
        except OpenAIAPIError as e:
            # Handle authentication/permission errors
            status_code = getattr(e, 'status_code', None)
            if status_code in (401, 403):
                logger.debug("Embedding model not available - embeddings disabled", model=self.embedding_model, status_code=status_code)
                return None
            logger.warning("Failed to get embedding", status_code=status_code, error=str(e))
            return None
        except Exception as e:
            logger.warning("Failed to get embedding", error=str(e))
            return None
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((OpenAIAPIError,)),
        reraise=True
    )
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        response_format: Optional[Dict[str, str]] = None
    ) -> str:
        # Standard GPT chat
        # Rate limit: wait if needed
        self.rate_limiter.wait_if_needed()
        
        try:
            kwargs = {
                "model": self.chat_model,
                "messages": messages,
            }
            # gpt-5-nano models only support default temperature (1), so skip temperature parameter
            # For other models, include temperature if it's not the default
            if "gpt-5-nano" not in self.chat_model.lower():
                kwargs["temperature"] = temperature
            elif temperature != 1.0:
                logger.debug("Skipping temperature parameter for gpt-5-nano model (only supports default)")
            
            if response_format:
                kwargs["response_format"] = response_format
            
            response = self.client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            
            # Validate response is not empty
            if not content or len(content.strip()) == 0:
                logger.error("Empty response from LLM")
                raise ValueError("Empty response from LLM")
            
            logger.debug("Got chat completion", messages_count=len(messages))
            return content
        except OpenAIAPIError as e:
            status_code = getattr(e, 'status_code', None)
            if status_code in (401, 403):
                logger.error("OpenAI API authentication failed - check API key", status_code=status_code)
            elif status_code == 429:
                logger.error("Rate limit exceeded despite rate limiter", status_code=429)
            else:
                logger.error("Failed to get chat completion", status_code=status_code, error=str(e))
            raise
        except Exception as e:
            logger.error("Failed to get chat completion", error=str(e))
            raise
    
    def extract_article_json(self, raw_html: str, ticker: Optional[str] = None) -> Dict[str, Any]:
        # Parse news HTML to JSON
        system_prompt = """You are a financial news article extractor. Extract structured information from raw HTML.

CRITICAL RULE: An article is ONLY usable if it specifically mentions the company/ticker symbol in the article content.

Return a JSON object with the following structure:
{
  "title": "Article title",
  "ticker": "Stock ticker symbol if mentioned (e.g., AAPL, TSLA)",
  "content_text": "Clean article text without HTML tags",
  "is_usable": true/false,
  "reason": "Why this article is usable or not",
  "timestamp": "ISO 8601 timestamp if available"
}

Rules for is_usable:
- Set is_usable to TRUE ONLY if:
  * The article specifically mentions the company/ticker symbol in the content
  * The article contains substantial information about the company (not just a passing mention)
  * The article is about the company's business, financials, products, or news
  * The content is substantial (at least 200 characters of meaningful text)
  
- Set is_usable to FALSE if:
  * The company/ticker is NOT mentioned in the article content
  * The article is about a different company
  * The article only mentions the company in passing without substantial information
  * The article is too short, corrupted, or contains no meaningful content
  * The article is generic market commentary without company-specific details
  * The article is about unrelated topics (politics, sports, etc.) unless directly impacting the company

Content extraction:
- Extract only the main article content, remove navigation, ads, headers, footers
- If no ticker is mentioned in content, set ticker to null
- Extract timestamp if available in the article
- Return ONLY valid JSON, no markdown formatting"""
        
        user_prompt = f"Extract article information from this HTML"
        if ticker:
            user_prompt += f". Expected ticker: {ticker} - the article MUST mention this company to be usable."
        user_prompt += f"\n\n{raw_html[:8000]}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response = self.chat_completion(
            messages,
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM JSON response", response=response[:200])
            return {
                "title": "Unknown",
                "ticker": None,
                "content_text": "",
                "is_usable": False,
                "reason": "Failed to parse LLM response",
                "timestamp": None
            }

