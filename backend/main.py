# Backend orchestrator
import time
import structlog
from datetime import datetime, timedelta

from backend.config import settings
from backend.database import DatabaseClient
from backend.clients import LLMClient, FinnhubClient, AlpacaClient
from backend.graph import TradingGraph


logger = structlog.get_logger(__name__)


class TradingSystem:
    # High-level system control
    
    def __init__(self):
        # Wire up all components
        self.db = DatabaseClient()
        self.llm = LLMClient(chat_model="gpt-5.2-2025-12-11")  # Use gpt-5.2 for trading agents
        self.finnhub = FinnhubClient()
        self.alpaca = AlpacaClient(paper=True)
        self.graph = TradingGraph(self.db, self.llm, self.finnhub, self.alpaca)
        logger.info("Trading system initialized")
    
    def update_stock_data(self) -> None:
        # Fetch latest prices from Finnhub
        logger.info("Updating stock data", tickers=settings.stocks)
        
        for ticker in settings.stocks:
            try:
                snapshot_data = self.finnhub.get_stock_snapshot(ticker)
                from backend.database.models import StockSnapshot
                snapshot = StockSnapshot(**snapshot_data)
                self.db.save_stock_snapshot(snapshot)
                logger.info("Stock data updated", ticker=ticker)
            except Exception as e:
                logger.error("Failed to update stock data", ticker=ticker, error=str(e))
    
    def process_ticker(self, ticker: str) -> None:
        # Run standard trading flow for one ticker
        try:
            logger.info("Processing ticker", ticker=ticker)
            result = self.graph.run(ticker)
            
            if result.get("error"):
                logger.error("Ticker processing failed", ticker=ticker, error=result["error"])
            elif result.get("executed_trade"):
                logger.info("Trade executed", ticker=ticker, trade=result["executed_trade"])
            else:
                logger.info("Ticker processed", ticker=ticker, proposal=result.get("trade_proposal"))
        
        except Exception as e:
            logger.error("Failed to process ticker", ticker=ticker, error=str(e))
    
    def run_cycle(self) -> None:
        # Update all and process all
        logger.info("Starting trading cycle", tickers=settings.stocks)
        
        self.update_stock_data()
        
        for ticker in settings.stocks:
            self.process_ticker(ticker)
            time.sleep(5)
        
        logger.info("Trading cycle complete")
    
    def should_run_trading_cycle(self) -> bool:
        # Check market hours and daily limits
        # Check if market is open
        if not self.finnhub.is_market_open():
            logger.debug("Market is closed, skipping trading cycle")
            return False
        
        # Check if we've already traded today
        if self.db.has_traded_today():
            logger.info("Already traded today, skipping trading cycle")
            return False
        
        # Prefer running within first 2 hours of market open (9:30-11:30 AM ET)
        # Market opens at 9:30 AM ET = 13:30 UTC (during DST) or 14:30 UTC (standard)
        # For simplicity, we'll just check if market is open and not yet traded
        # The hourly check ensures we'll catch it early in the day
        logger.info("Market is open and no trades today - ready to trade")
        return True
    
    def run(self, interval_minutes: int = 60) -> None:
        # Main infinite loop
        logger.info("Starting trading system", interval_minutes=interval_minutes, 
                   note="Will check hourly, trade once per day when market is open")
        
        while True:
            try:
                # Check conditions before running
                if self.should_run_trading_cycle():
                    self.run_cycle()
                    logger.info("Trading cycle completed for today")
                else:
                    logger.debug("Skipping trading cycle - conditions not met")
                
                logger.info("Sleeping until next check", minutes=interval_minutes)
                time.sleep(interval_minutes * 60)
            except KeyboardInterrupt:
                logger.info("Shutting down trading system")
                break
            except Exception as e:
                logger.error("Error in trading cycle check", error=str(e))
                time.sleep(60)


if __name__ == "__main__":
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer()
        ]
    )
    
    system = TradingSystem()
    system.run(interval_minutes=60)

