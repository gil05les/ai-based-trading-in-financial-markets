# Analyzes headlines and proposes trades
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import structlog
import json

from .base_agent import BaseAgent
from backend.database import DatabaseClient
from backend.clients import LLMClient, FinnhubClient
from backend.database.models import AnalysisEvent, TradeProposal


class TraderAgent(BaseAgent):
    # Main trading logic
    
    def __init__(self, db: DatabaseClient, llm: LLMClient, finnhub: FinnhubClient):
        super().__init__(llm=llm, db=db, finnhub=finnhub)
    
    def analyze_ticker(self, ticker: str) -> Dict[str, Any]:
        # Scan headlines to see if it's worth a debate
        try:
            # Get only recent article headlines (not full content)
            articles = self.db.get_recent_articles(ticker=ticker, hours=24)
            snapshot = self.db.get_latest_snapshot(ticker)
            
            if not snapshot:
                snapshot_data = self.finnhub.get_stock_snapshot(ticker)
                from backend.database.models import StockSnapshot
                snapshot_id = self.db.save_stock_snapshot(StockSnapshot(**snapshot_data))
                snapshot = self.db.get_latest_snapshot(ticker)
            
            # Only use headlines, not article content
            context = {
                "ticker": ticker,
                "current_price": float(snapshot["price"]) if snapshot else None,
                "price_change": float(snapshot.get("price_change", 0)) if snapshot else 0,
                "price_change_percent": float(snapshot.get("price_change_percent", 0)) if snapshot else 0,
                "recent_headlines_count": len(articles),
                "headlines": [
                    {
                        "title": a.get("title", "No title"),
                        "timestamp": str(a.get("timestamp", "")) if a.get("timestamp") else ""
                    }
                    for a in articles[:30]  # Look at up to 30 headlines
                ]
            }
            
            system_prompt = """You are a swing trading analyst. Your job is to scan news HEADLINES (not full articles) for a stock ticker and decide if it warrants deeper analysis through a debate.

You can ONLY see headlines - you cannot read full article content. Based on headlines alone, determine if:
- There are significant news events (earnings, product launches, regulatory changes, etc.)
- The headlines suggest potential trading opportunities
- The news volume and sentiment warrant a deeper debate

Return JSON:
{
  "is_interesting": true/false,
  "reasoning": "Why this ticker is interesting or not based on headlines",
  "confidence": 0-100
}

If is_interesting is true, a debate will be triggered where analysts will read full articles and conduct deep analysis."""
            
            user_prompt = f"Analyze headlines for this ticker:\n\n{json.dumps(context, indent=2)}"
            
            response = self.llm.chat_completion(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            analysis = json.loads(response)
            
            confidence = analysis.get("confidence", 0)
            
            event = AnalysisEvent(
                ticker=ticker,
                event_type="ticker_analysis",
                reasoning=analysis.get("reasoning", ""),
                input_data=context,
                output_data=analysis,
                agent_name="trader_agent"
            )
            
            event_id = self.db.save_analysis_event(event)
            self.logger.info(
                "Ticker analyzed from headlines",
                ticker=ticker,
                interesting=analysis.get("is_interesting"),
                confidence=confidence,
                article_count=len(articles)
            )
            
            return {
                "event_id": event_id,
                "analysis": analysis,
                "ticker": ticker
            }
        
        except Exception as e:
            self.logger.error("Failed to analyze ticker", ticker=ticker, error=str(e))
            return {
                "event_id": None,
                "analysis": {"is_interesting": False, "reasoning": f"Error: {str(e)}"},
                "ticker": ticker
            }
    
    def self_analyze(self, ticker: str, analysis_event_id: int) -> Optional[TradeProposal]:
        # Full deep dive and proposal
        try:
            articles = self.db.get_recent_articles(ticker=ticker, hours=24)
            snapshot = self.db.get_latest_snapshot(ticker)
            recent_trades = self.db.get_recent_trades(ticker=ticker, days=7)
            
            context = {
                "ticker": ticker,
                "current_price": float(snapshot["price"]) if snapshot else None,
                "articles": [a["content_text"][:1000] for a in articles[:10] if a.get("content_text")],
                "recent_trades": recent_trades[:5]
            }
            
            system_prompt = """You are a swing trading analyst. Analyze all available information and propose a trade.
            
Return JSON:
{
  "action": "BUY" | "SELL" | "HOLD",
  "quantity": number of shares,
  "reasoning": "Detailed reasoning for this trade",
  "confidence_score": 0-100
}"""
            
            user_prompt = f"Analyze and propose trade:\n\n{json.dumps(context, indent=2)}"
            
            response = self.llm.chat_completion(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            proposal_data = json.loads(response)
            
            proposal = TradeProposal(
                ticker=ticker,
                action=proposal_data.get("action", "HOLD"),
                quantity=proposal_data.get("quantity", 0),
                proposed_price=snapshot["price"] if snapshot else None,
                reasoning=proposal_data.get("reasoning", ""),
                confidence_score=proposal_data.get("confidence_score"),
                analysis_event_id=analysis_event_id,
                status="PENDING"
            )
            
            proposal_id = self.db.save_trade_proposal(proposal)
            proposal.id = proposal_id
            
            self.logger.info("Trade proposal created", ticker=ticker, action=proposal.action, proposal_id=proposal_id)
            
            return proposal
        
        except Exception as e:
            self.logger.error("Failed to self-analyze", ticker=ticker, error=str(e))
            return None

