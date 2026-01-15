# Manages risk and executes orders
from typing import Optional, Dict, Any
from decimal import Decimal
import structlog
import json
import time

from .base_agent import BaseAgent
from backend.database import DatabaseClient
from backend.clients import LLMClient, AlpacaClient
from backend.database.models import TradeProposal, ExecutedTrade


class PortfolioManagerAgent(BaseAgent):
    # Final approval and execution
    
    def __init__(self, db: DatabaseClient, llm: LLMClient, alpaca: AlpacaClient):
        super().__init__(llm=llm, db=db, alpaca=alpaca)
    
    def review_proposal(self, proposal: TradeProposal) -> Dict[str, Any]:
        # Approve or reject based on risk rules
        try:
            account = self.alpaca.get_account()
            positions = self.alpaca.get_positions()
            recent_trades = self.db.get_recent_trades(days=7)
            
            current_position = None
            for pos in positions:
                if pos["symbol"] == proposal.ticker:
                    current_position = pos
                    break
            
            # Check if we need buying power for this trade
            needs_buying_power = False
            required_cash = 0.0
            if proposal.action == "BUY" and proposal.quantity > 0:
                # Estimate required cash (using proposed price or current price)
                price = float(proposal.proposed_price) if proposal.proposed_price else 0.0
                if price == 0 and current_position:
                    price = current_position.get("current_price", 0.0)
                if price == 0:
                    # Fallback: get current price from snapshot
                    snapshot = self.db.get_latest_snapshot(proposal.ticker)
                    if snapshot:
                        price = float(snapshot.get("price", 0.0))
                
                required_cash = price * proposal.quantity
                needs_buying_power = required_cash > account.get("buying_power", 0.0)
            
            context = {
                "proposal": {
                    "ticker": proposal.ticker,
                    "action": proposal.action,
                    "quantity": proposal.quantity,
                    "reasoning": proposal.reasoning,
                    "confidence_score": proposal.confidence_score,
                    "proposed_price": float(proposal.proposed_price) if proposal.proposed_price else None
                },
                "account": account,
                "current_position": current_position,
                "positions": positions,
                "recent_trades": recent_trades[:10],
                "needs_buying_power": needs_buying_power,
                "required_cash": required_cash
            }
            
            system_prompt = """You are a conservative portfolio manager. Review trade proposals and decide whether to approve or reject them.

CRITICAL TRADING RULES:
- REJECT any proposal with confidence_score < 70 - we only trade on STRONG confidence
- REJECT proposals based on single news items - require MULTIPLE converging news sources
- Be very conservative: only approve trades when there's STRONG evidence and high confidence
- Consider transaction costs - reject marginal trades
- Avoid overtrading - consider recent trading frequency

Consider:
- Available cash/buying power
- Current positions
- Risk management
- Recent trading activity (avoid overtrading)
- Proposal quality and confidence (MUST be 70+)
- Whether the proposal is based on multiple news sources or just one

IMPORTANT: If this is a BUY order and there's insufficient buying power (needs_buying_power is true), you should:
1. Evaluate if the proposed trade is better than holding current positions
2. If yes, recommend selling another position to free up buying power
3. Specify which position to sell in the "position_to_sell" field

Return JSON:
{
  "decision": "APPROVE" | "REJECT",
  "reasoning": "Why you approve or reject. Must mention confidence level and whether multiple news sources were considered.",
  "adjusted_quantity": optional adjusted quantity if different from proposal,
  "position_to_sell": optional ticker symbol to sell if rebalancing needed,
  "sell_quantity": optional quantity to sell if rebalancing needed
}

REJECT if confidence_score < 70. REJECT if based on insufficient news sources."""
            
            user_prompt = f"Review this trade proposal:\n\n{json.dumps(context, indent=2)}"
            
            response = self.llm.chat_completion(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5,
                response_format={"type": "json_object"}
            )
            
            decision = json.loads(response)
            
            # Enforce minimum confidence threshold - reject if below 70
            confidence_score = proposal.confidence_score or 0
            if confidence_score < 70 and decision.get("decision") == "APPROVE":
                self.logger.warning(
                    "Rejecting proposal due to low confidence",
                    proposal_id=proposal.id,
                    confidence=confidence_score,
                    required=70
                )
                decision["decision"] = "REJECT"
                decision["reasoning"] = f"{decision.get('reasoning', '')} [Rejected: Confidence {confidence_score} < 70 required]"
            
            self.logger.info(
                "Proposal reviewed",
                proposal_id=proposal.id,
                decision=decision.get("decision"),
                ticker=proposal.ticker,
                confidence=confidence_score,
                needs_buying_power=needs_buying_power,
                position_to_sell=decision.get("position_to_sell")
            )
            
            return decision
        
        except Exception as e:
            self.logger.error("Failed to review proposal", proposal_id=proposal.id, error=str(e))
            return {
                "decision": "REJECT",
                "reasoning": f"Review failed: {str(e)}"
            }
    
    def _evaluate_position_to_sell(
        self, 
        proposal: TradeProposal, 
        positions: list, 
        required_cash: float
    ) -> Optional[Dict[str, Any]]:
        # Check if we should rebalance to fund this trade
        if not positions:
            return None
        
        # Get recent articles and snapshots for all positions
        position_data = []
        for pos in positions:
            if pos["symbol"] == proposal.ticker:
                continue  # Skip the ticker we're trying to buy
            
            snapshot = self.db.get_latest_snapshot(pos["symbol"])
            recent_articles = self.db.get_recent_articles(ticker=pos["symbol"], hours=24)
            
            position_data.append({
                "symbol": pos["symbol"],
                "qty": pos["qty"],
                "current_price": pos["current_price"],
                "market_value": pos["market_value"],
                "unrealized_pl": pos["unrealized_pl"],
                "avg_entry_price": pos["avg_entry_price"],
                "recent_articles_count": len(recent_articles),
                "headlines": [a.get("title", "") for a in recent_articles[:5]]
            })
        
        if not position_data:
            return None
        
        context = {
            "proposed_trade": {
                "ticker": proposal.ticker,
                "action": proposal.action,
                "quantity": proposal.quantity,
                "reasoning": proposal.reasoning,
                "confidence_score": proposal.confidence_score
            },
            "required_cash": required_cash,
            "current_positions": position_data
        }
        
        system_prompt = """You are a portfolio manager evaluating whether to sell an existing position to free up buying power for a new trade.

The proposed trade requires more buying power than available. You need to decide:
1. Is the proposed trade better than holding current positions?
2. If yes, which position should be sold to free up the required cash?

Consider:
- The quality and confidence of the proposed trade
- The performance and prospects of current positions
- Recent news/headlines for each position
- Portfolio diversification
- Risk management

Return JSON:
{
  "should_rebalance": true/false,
  "reasoning": "Why you should or shouldn't rebalance",
  "position_to_sell": ticker symbol to sell (if should_rebalance is true),
  "sell_quantity": quantity to sell (if should_rebalance is true)
}

Only recommend selling if the proposed trade is clearly better than holding the current position."""
        
        user_prompt = f"Evaluate if we should sell a position to free up buying power:\n\n{json.dumps(context, indent=2)}"
        
        try:
            response = self.llm.chat_completion(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5,
                response_format={"type": "json_object"}
            )
            
            evaluation = json.loads(response)
            
            if evaluation.get("should_rebalance") and evaluation.get("position_to_sell"):
                self.logger.info(
                    "Rebalancing recommended",
                    position_to_sell=evaluation.get("position_to_sell"),
                    sell_quantity=evaluation.get("sell_quantity"),
                    reasoning=evaluation.get("reasoning")
                )
                return {
                    "ticker": evaluation.get("position_to_sell"),
                    "quantity": evaluation.get("sell_quantity", 0),
                    "reasoning": evaluation.get("reasoning", "")
                }
            
            return None
        
        except Exception as e:
            self.logger.error("Failed to evaluate position to sell", error=str(e))
            return None
    
    def execute_trade(self, proposal: TradeProposal, decision: Dict[str, Any]) -> Optional[ExecutedTrade]:
        # Send order to Alpaca
        if decision.get("decision") != "APPROVE":
            self.db.update_proposal_status(proposal.id, "REJECTED")
            self.logger.info("Trade rejected", proposal_id=proposal.id)
            return None
        
        try:
            # Check if we need to sell a position first to free up buying power
            position_to_sell = decision.get("position_to_sell")
            sell_quantity = decision.get("sell_quantity")
            
            if position_to_sell and sell_quantity and proposal.action == "BUY":
                # First, check if we still need to sell (buying power might have changed)
                account = self.alpaca.get_account()
                price = float(proposal.proposed_price) if proposal.proposed_price else 0.0
                if price == 0:
                    snapshot = self.db.get_latest_snapshot(proposal.ticker)
                    if snapshot:
                        price = float(snapshot.get("price", 0.0))
                
                required_cash = price * proposal.quantity
                
                if required_cash > account.get("buying_power", 0.0):
                    # Verify the position still exists and we should still sell it
                    positions = self.alpaca.get_positions()
                    position_exists = any(pos["symbol"] == position_to_sell for pos in positions)
                    
                    if not position_exists:
                        self.logger.warning(
                            "Position to sell no longer exists",
                            ticker=position_to_sell,
                            proposal_id=proposal.id
                        )
                        self.db.update_proposal_status(proposal.id, "REJECTED")
                        return None
                    
                    # Re-evaluate as a safety check, but proceed if evaluation confirms or is inconclusive
                    rebalance_decision = self._evaluate_position_to_sell(proposal, positions, required_cash)
                    
                    if rebalance_decision and rebalance_decision["ticker"] == position_to_sell:
                        # Execute sell order first
                        self.logger.info(
                            "Selling position to free up buying power",
                            ticker=position_to_sell,
                            quantity=sell_quantity
                        )
                        
                        sell_order = self.alpaca.submit_order(
                            symbol=position_to_sell,
                            qty=int(sell_quantity),
                            side="SELL",
                            order_type="market"
                        )
                        
                        self.logger.info(
                            "Sell order executed for rebalancing",
                            ticker=position_to_sell,
                            order_id=sell_order.get("id")
                        )
                        
                        # Wait a moment for the order to settle (buying power to update)
                        time.sleep(2)
                    elif rebalance_decision is None:
                        # Evaluation didn't recommend selling, but we'll proceed with original decision
                        # as it was already approved in review_proposal
                        self.logger.info(
                            "Proceeding with rebalancing despite evaluation not recommending it",
                            ticker=position_to_sell,
                            reasoning="Original decision was approved"
                        )
                        
                        sell_order = self.alpaca.submit_order(
                            symbol=position_to_sell,
                            qty=int(sell_quantity),
                            side="SELL",
                            order_type="market"
                        )
                        
                        self.logger.info(
                            "Sell order executed for rebalancing",
                            ticker=position_to_sell,
                            order_id=sell_order.get("id")
                        )
                        
                        time.sleep(2)
                    else:
                        # Evaluation recommends selling a different position - reject for safety
                        self.logger.warning(
                            "Rebalancing decision changed, rejecting original proposal",
                            original_position=position_to_sell,
                            recommended_position=rebalance_decision.get("ticker")
                        )
                        self.db.update_proposal_status(proposal.id, "REJECTED")
                        return None
            
            # Execute the main trade
            quantity = decision.get("adjusted_quantity", proposal.quantity)
            
            order = self.alpaca.submit_order(
                symbol=proposal.ticker,
                qty=quantity,
                side=proposal.action,
                order_type="market"
            )
            
            execution_price = Decimal(str(order.get("price", 0)))
            if execution_price == 0 and proposal.proposed_price:
                execution_price = proposal.proposed_price
            
            executed_trade = ExecutedTrade(
                trade_proposal_id=proposal.id,
                ticker=proposal.ticker,
                action=proposal.action,
                quantity=quantity,
                execution_price=execution_price,
                alpaca_order_id=str(order.get("id", "")),
                portfolio_manager_reasoning=decision.get("reasoning"),
                status="FILLED"
            )
            
            trade_id = self.db.save_executed_trade(executed_trade)
            self.db.update_proposal_status(proposal.id, "EXECUTED")
            executed_trade.id = trade_id
            
            self.logger.info(
                "Trade executed",
                trade_id=trade_id,
                ticker=proposal.ticker,
                action=proposal.action,
                quantity=quantity
            )
            
            return executed_trade
        
        except Exception as e:
            self.logger.error("Failed to execute trade", proposal_id=proposal.id, error=str(e))
            self.db.update_proposal_status(proposal.id, "REJECTED")
            return None

