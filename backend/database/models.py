# Pydantic models for the system
from datetime import datetime
from typing import Optional, Dict, Any
from decimal import Decimal
from pydantic import BaseModel, Field


class ArticleRaw(BaseModel):
    # Raw HTML from web
    id: Optional[int] = None
    url: str
    raw_html: str
    scraped_at: Optional[datetime] = None
    ticker: Optional[str] = None
    source_url: Optional[str] = None


class ArticleCleaned(BaseModel):
    # LLM processed news
    id: Optional[int] = None
    raw_article_id: Optional[int] = None
    title: str
    ticker: Optional[str] = None
    content_text: str
    is_usable: bool
    reason: Optional[str] = None
    timestamp: Optional[datetime] = None
    created_at: Optional[datetime] = None
    llm_model: Optional[str] = None
    llm_response: Optional[Dict[str, Any]] = None


class ArticleEmbedding(BaseModel):
    # Vector data for search
    id: Optional[int] = None
    cleaned_article_id: int
    embedding: list[float]
    created_at: Optional[datetime] = None


class StockSnapshot(BaseModel):
    # Price and basics
    id: Optional[int] = None
    ticker: str
    price: Decimal
    volume: Optional[int] = None
    high: Optional[Decimal] = None
    low: Optional[Decimal] = None
    open_price: Optional[Decimal] = None
    close_price: Optional[Decimal] = None
    market_cap: Optional[int] = None
    pe_ratio: Optional[Decimal] = None
    dividend_yield: Optional[Decimal] = None
    snapshot_time: Optional[datetime] = None
    data_source: str = "finnhub"


class AnalysisEvent(BaseModel):
    # Step in agent pipeline
    id: Optional[int] = None
    ticker: str
    event_type: str
    reasoning: str
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    agent_name: Optional[str] = None
    created_at: Optional[datetime] = None


class Debate(BaseModel):
    # Bull/Bear talk
    id: Optional[int] = None
    ticker: str
    debate_type: str = "bull_vs_bear"
    transcript: Dict[str, Any]
    bull_argument: str
    bear_argument: str
    final_consensus: Optional[str] = None
    created_at: Optional[datetime] = None
    trader_agent_id: Optional[int] = None


class TradeProposal(BaseModel):
    # Order to review
    id: Optional[int] = None
    ticker: str
    action: str = Field(..., pattern="^(BUY|SELL|HOLD)$")
    quantity: int
    proposed_price: Optional[Decimal] = None
    reasoning: str
    confidence_score: Optional[float] = Field(None, ge=0, le=100)
    analysis_event_id: Optional[int] = None
    debate_id: Optional[int] = None
    created_at: Optional[datetime] = None
    status: str = Field(default="PENDING", pattern="^(PENDING|APPROVED|REJECTED|EXECUTED)$")


class ExecutedTrade(BaseModel):
    # Final trade record
    id: Optional[int] = None
    trade_proposal_id: Optional[int] = None
    ticker: str
    action: str = Field(..., pattern="^(BUY|SELL)$")
    quantity: int
    execution_price: Decimal
    alpaca_order_id: Optional[str] = None
    portfolio_manager_reasoning: Optional[str] = None
    executed_at: Optional[datetime] = None
    status: str = Field(default="FILLED", pattern="^(FILLED|PARTIAL|CANCELLED|REJECTED)$")

