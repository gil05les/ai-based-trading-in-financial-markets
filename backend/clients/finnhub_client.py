# Finnhub API client
from typing import Optional, Dict, Any
from decimal import Decimal
from datetime import datetime
import structlog
import finnhub
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from backend.config import settings


logger = structlog.get_logger(__name__)


class FinnhubClient:
    # Client for Finnhub data
    
    def __init__(self):
        # Setup Finnhub connection
        self.client = finnhub.Client(api_key=settings.finnhub_key)
        logger.info("Finnhub client initialized")
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def get_quote(self, ticker: str) -> Dict[str, Any]:
        # Get latest price info
        try:
            quote = self.client.quote(ticker)
            logger.debug("Fetched quote", ticker=ticker, quote=quote)
            return quote
        except Exception as e:
            logger.error("Failed to fetch quote", ticker=ticker, error=str(e))
            raise
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def get_company_profile(self, ticker: str) -> Dict[str, Any]:
        # Get industry and business info
        try:
            profile = self.client.company_profile2(symbol=ticker)
            logger.debug("Fetched company profile", ticker=ticker)
            return profile
        except Exception as e:
            logger.error("Failed to fetch company profile", ticker=ticker, error=str(e))
            raise
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def get_financials(self, ticker: str, statement: str = "bs") -> Dict[str, Any]:
        # Basic financials (BS/PL/CF)
        try:
            financials = self.client.financials(symbol=ticker, statement=statement)
            logger.debug("Fetched financials", ticker=ticker, statement=statement)
            return financials
        except Exception as e:
            logger.error("Failed to fetch financials", ticker=ticker, error=str(e))
            raise
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def get_market_status(self, exchange: str = "US") -> Dict[str, Any]:
        # Check if exchange is open
        try:
            # Use direct API call for market status
            url = "https://finnhub.io/api/v1/stock/market-status"
            params = {
                "exchange": exchange,
                "token": settings.finnhub_key
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            status = response.json()
            logger.debug("Fetched market status", exchange=exchange, status=status)
            return status
        except Exception as e:
            logger.error("Failed to fetch market status", exchange=exchange, error=str(e))
            raise
    
    def is_market_open(self, exchange: str = "US") -> bool:
        # Simple open/closed check
        try:
            status = self.get_market_status(exchange)
            # Finnhub returns 'isOpen' as boolean
            is_open = status.get("isOpen", False) if isinstance(status, dict) else False
            logger.info("Market status checked", exchange=exchange, is_open=is_open)
            return is_open
        except Exception as e:
            logger.warning("Failed to check market status, assuming closed", exchange=exchange, error=str(e))
            return False
    
    def get_stock_snapshot(self, ticker: str) -> Dict[str, Any]:
        # Combined price and profile data
        try:
            quote = self.get_quote(ticker)
            profile = self.get_company_profile(ticker)
            
            market_cap = profile.get("marketCapitalization") if profile else None
            if market_cap and isinstance(market_cap, float):
                market_cap = int(market_cap)
            
            pe_ratio = profile.get("finnhubIndustry") if profile else None
            if pe_ratio and not isinstance(pe_ratio, (int, float, Decimal)):
                pe_ratio = None
            
            snapshot = {
                "ticker": ticker,
                "price": Decimal(str(quote.get("c", 0))),
                "high": Decimal(str(quote.get("h", 0))) if quote.get("h") else None,
                "low": Decimal(str(quote.get("l", 0))) if quote.get("l") else None,
                "open_price": Decimal(str(quote.get("o", 0))) if quote.get("o") else None,
                "close_price": Decimal(str(quote.get("pc", 0))) if quote.get("pc") else None,
                "volume": quote.get("v", 0),
                "market_cap": market_cap,
                "pe_ratio": Decimal(str(pe_ratio)) if pe_ratio and isinstance(pe_ratio, (int, float)) else None,
                "snapshot_time": datetime.utcnow(),
            }
            
            logger.info("Created stock snapshot", ticker=ticker)
            return snapshot
        except Exception as e:
            logger.error("Failed to create stock snapshot", ticker=ticker, error=str(e))
            raise

