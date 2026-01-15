# Alpaca API client
from typing import Optional, Dict, Any, List
from decimal import Decimal
import structlog
from alpaca_trade_api import REST
from alpaca_trade_api.entity import Order as AlpacaOrder
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from backend.config import settings


logger = structlog.get_logger(__name__)


class AlpacaClient:
    # Handles Alpaca REST calls
    
    def __init__(self, paper: bool = True):
        # Init REST client (default to paper)
        base_url = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
        self.client = REST(
            key_id=settings.alpaca_api_key,
            secret_key=settings.alpaca_api_secret,
            base_url=base_url
        )
        logger.info("Alpaca client initialized", paper=paper)
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def get_account(self) -> Dict[str, Any]:
        # Get buying power and status
        try:
            account = self.client.get_account()
            return {
                "cash": float(account.cash),
                "portfolio_value": float(account.portfolio_value),
                "buying_power": float(account.buying_power),
                "equity": float(account.equity),
            }
        except Exception as e:
            logger.error("Failed to get account", error=str(e))
            raise
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def get_positions(self) -> List[Dict[str, Any]]:
        # Current open positions
        try:
            positions = self.client.list_positions()
            return [
                {
                    "symbol": pos.symbol,
                    "qty": float(pos.qty),
                    "avg_entry_price": float(pos.avg_entry_price),
                    "current_price": float(pos.current_price),
                    "market_value": float(pos.market_value),
                    "unrealized_pl": float(pos.unrealized_pl),
                }
                for pos in positions
            ]
        except Exception as e:
            logger.error("Failed to get positions", error=str(e))
            raise
    
    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        retry=retry_if_exception_type((Exception,)),
        reraise=True
    )
    def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str = "market",
        limit_price: Optional[Decimal] = None
    ) -> Dict[str, Any]:
        # Send new order
        try:
            order_side = "buy" if side.upper() == "BUY" else "sell"
            time_in_force = "day"
            
            if order_type.lower() == "market":
                order = self.client.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side=order_side,
                    type="market",
                    time_in_force=time_in_force
                )
            else:
                if not limit_price:
                    raise ValueError("Limit price required for limit orders")
                order = self.client.submit_order(
                    symbol=symbol,
                    qty=qty,
                    side=order_side,
                    type="limit",
                    limit_price=float(limit_price),
                    time_in_force=time_in_force
                )
            
            logger.info(
                "Order submitted",
                symbol=symbol,
                side=side,
                qty=qty,
                order_id=order.id
            )
            
            return {
                "id": str(order.id),
                "symbol": order.symbol,
                "qty": float(order.qty),
                "side": order.side,
                "status": order.status,
                "order_type": order.type,
                "price": float(order.filled_avg_price) if hasattr(order, 'filled_avg_price') and order.filled_avg_price else None,
            }
        except Exception as e:
            logger.error("Failed to submit order", symbol=symbol, error=str(e))
            raise
    
    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        # Single position check
        try:
            position = self.client.get_position(symbol)
            return {
                "symbol": position.symbol,
                "qty": float(position.qty),
                "avg_entry_price": float(position.avg_entry_price),
                "current_price": float(position.current_price),
                "market_value": float(position.market_value),
                "unrealized_pl": float(position.unrealized_pl),
            }
        except Exception as e:
            logger.debug("Position not found", symbol=symbol, error=str(e))
            return None

