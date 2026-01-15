# Bull and Bear analysts for debate
from typing import Dict, Any
import structlog
import json

from .base_agent import BaseAgent
from backend.database import DatabaseClient
from backend.clients import LLMClient
from backend.database.models import Debate


class BullAgent(BaseAgent):
    # Bullish perspective
    
    def __init__(self, db: DatabaseClient, llm: LLMClient):
        super().__init__(llm=llm, db=db)
    
    def make_argument(self, ticker: str, context: Dict[str, Any]) -> str:
        # Build bullish case
        article_count = context.get("article_count", len(context.get("articles", [])))
        system_prompt = f"""You are a bullish stock analyst. Make a compelling argument for why this stock is a good buy.

IMPORTANT: You have access to {article_count} news articles. You MUST base your argument on MULTIPLE independent news sources, not just one. Look for CONVERGING EVIDENCE across different sources.

Focus on:
- Positive news and trends from MULTIPLE sources
- Growth potential supported by several news items
- Strong fundamentals confirmed across different articles
- Market opportunities mentioned in multiple independent reports

Be specific and data-driven. Reference MULTIPLE news sources in your argument. If you only have one or two news sources, acknowledge this limitation."""
        
        user_prompt = f"Make a bullish argument for {ticker}:\n\n{json.dumps(context, indent=2)}"
        
        response = self.llm.chat_completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.8
        )
        
        return response


class BearAgent(BaseAgent):
    # Bearish perspective
    
    def __init__(self, db: DatabaseClient, llm: LLMClient):
        super().__init__(llm=llm, db=db)
    
    def make_argument(self, ticker: str, context: Dict[str, Any]) -> str:
        # Build bearish case
        article_count = context.get("article_count", len(context.get("articles", [])))
        system_prompt = f"""You are a bearish stock analyst. Make a compelling argument for why this stock should be avoided or sold.

IMPORTANT: You have access to {article_count} news articles. You MUST base your argument on MULTIPLE independent news sources, not just one. Look for CONVERGING EVIDENCE across different sources.

Focus on:
- Negative news and risks from MULTIPLE sources
- Overvaluation concerns supported by several news items
- Weak fundamentals confirmed across different articles
- Market threats mentioned in multiple independent reports

Be specific and data-driven. Reference MULTIPLE news sources in your argument. If you only have one or two news sources, acknowledge this limitation."""
        
        user_prompt = f"Make a bearish argument for {ticker}:\n\n{json.dumps(context, indent=2)}"
        
        response = self.llm.chat_completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.8
        )
        
        return response


class DebateOrchestrator(BaseAgent):
    # Manages the debate flow
    
    def __init__(self, db: DatabaseClient, llm: LLMClient):
        super().__init__(llm=llm, db=db)
        self.bull = BullAgent(db, llm)
        self.bear = BearAgent(db, llm)
    
    def conduct_debate(self, ticker: str, trader_event_id: int) -> Debate:
        # Run rounds and get consensus
        try:
            articles = self.db.get_recent_articles(ticker=ticker, hours=24)
            snapshot = self.db.get_latest_snapshot(ticker)
            recent_trades = self.db.get_recent_trades(ticker=ticker, days=30)
            
            # Use more articles to ensure multiple news sources are considered
            # Take up to 20 articles to ensure we have multiple independent sources
            article_texts = [a["content_text"][:1000] for a in articles[:20] if a.get("content_text")]
            
            context = {
                "ticker": ticker,
                "current_price": float(snapshot["price"]) if snapshot else None,
                "articles": article_texts,
                "article_count": len(article_texts),
                "recent_trades": recent_trades[:5]
            }
            
            bull_argument = self.bull.make_argument(ticker, context)
            bear_argument = self.bear.make_argument(ticker, context)
            
            transcript = {
                "rounds": [
                    {
                        "bull": bull_argument,
                        "bear": bear_argument
                    }
                ]
            }
            
            consensus_prompt = f"""Based on these arguments, provide a final consensus:

BULL ARGUMENT:
{bull_argument}

BEAR ARGUMENT:
{bear_argument}

Provide a balanced assessment."""
            
            consensus = self.llm.chat_completion(
                [{"role": "user", "content": consensus_prompt}],
                temperature=0.7
            )
            
            debate = Debate(
                ticker=ticker,
                debate_type="bull_vs_bear",
                transcript=transcript,
                bull_argument=bull_argument,
                bear_argument=bear_argument,
                final_consensus=consensus,
                trader_agent_id=trader_event_id
            )
            
            debate_id = self.db.save_debate(debate)
            debate.id = debate_id
            
            self.logger.info("Debate conducted", ticker=ticker, debate_id=debate_id)
            
            return debate
        
        except Exception as e:
            self.logger.error("Failed to conduct debate", ticker=ticker, error=str(e))
            raise

