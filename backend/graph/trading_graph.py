# LangGraph trading state machine
from typing import TypedDict, List, Optional, Dict, Any
import json
import structlog
from langgraph.graph import StateGraph, END

from backend.database import DatabaseClient
from backend.clients import LLMClient, FinnhubClient, AlpacaClient
from backend.agents import TraderAgent, DebateOrchestrator, PortfolioManagerAgent
from backend.database.models import TradeProposal


logger = structlog.get_logger(__name__)


class TradingState(TypedDict):
    # Workflow state
    ticker: Optional[str]
    analysis_result: Optional[Dict[str, Any]]
    needs_debate: bool
    debate_result: Optional[Dict[str, Any]]
    trade_proposal: Optional[TradeProposal]
    portfolio_decision: Optional[Dict[str, Any]]
    executed_trade: Optional[Dict[str, Any]]
    error: Optional[str]


class TradingGraph:
    # Orchestrates the trading logic chain
    
    def __init__(
        self,
        db: DatabaseClient,
        llm: LLMClient,
        finnhub: FinnhubClient,
        alpaca: AlpacaClient
    ):
        # Setup agents and compile graph
        self.db = db
        self.finnhub = finnhub
        self.trader = TraderAgent(db, llm, finnhub)
        self.debate = DebateOrchestrator(db, llm)
        self.portfolio = PortfolioManagerAgent(db, llm, alpaca)
        
        self.graph = self._build_graph()
        logger.info("Trading graph initialized")
    
    def _build_graph(self) -> StateGraph:
        # Define nodes and edges
        workflow = StateGraph(TradingState)
        
        workflow.add_node("analyze_ticker", self._analyze_ticker)
        workflow.add_node("conduct_debate", self._conduct_debate)
        workflow.add_node("create_proposal_from_debate", self._create_proposal_from_debate)
        workflow.add_node("review_proposal", self._review_proposal)
        workflow.add_node("execute_trade", self._execute_trade)
        
        workflow.set_entry_point("analyze_ticker")
        
        # After analyzing headlines, decide if debate is needed
        workflow.add_conditional_edges(
            "analyze_ticker",
            self._should_debate,
            {
                "debate": "conduct_debate",
                "skip": END
            }
        )
        
        # Always go through debate → create proposal → review → execute
        workflow.add_edge("conduct_debate", "create_proposal_from_debate")
        workflow.add_edge("create_proposal_from_debate", "review_proposal")
        
        workflow.add_conditional_edges(
            "review_proposal",
            self._should_execute,
            {
                "execute": "execute_trade",
                "reject": END
            }
        )
        
        workflow.add_edge("execute_trade", END)
        
        return workflow.compile()
    
    def _analyze_ticker(self, state: TradingState) -> TradingState:
        # Fast scan of news headlines
        try:
            ticker = state["ticker"]
            if not ticker:
                state["error"] = "No ticker provided"
                return state
            
            # Trader only looks at headlines, not full articles
            result = self.trader.analyze_ticker(ticker)
            state["analysis_result"] = result
            # needs_debate is always True if interesting (kept for backwards compatibility)
            state["needs_debate"] = result.get("analysis", {}).get("is_interesting", False)
            
            logger.info("Ticker analyzed from headlines", ticker=ticker, interesting=result.get("analysis", {}).get("is_interesting"))
        
        except Exception as e:
            logger.error("Failed to analyze ticker", error=str(e))
            state["error"] = str(e)
        
        return state
    
    def _should_debate(self, state: TradingState) -> str:
        # Check if news warrants deep dive
        if state.get("error"):
            return "skip"
        
        analysis = state.get("analysis_result", {}).get("analysis", {})
        if not analysis.get("is_interesting", False):
            logger.info("Ticker not interesting, skipping", ticker=state.get("ticker"))
            return "skip"
        
        # If interesting, ALWAYS go to debate (no self-analysis path)
        logger.info("Ticker is interesting, triggering debate", ticker=state.get("ticker"))
        return "debate"
    
    def _conduct_debate(self, state: TradingState) -> TradingState:
        # Run Bull vs Bear
        try:
            ticker = state["ticker"]
            analysis_result = state.get("analysis_result") or {}
            event_id = analysis_result.get("event_id")
            
            if not event_id:
                logger.error("No analysis event ID available for debate", ticker=ticker)
                state["error"] = "No analysis event ID available"
                return state
            
            debate = self.debate.conduct_debate(ticker, event_id)
            if debate and debate.id:
                state["debate_result"] = {
                    "debate_id": debate.id,
                    "bull_argument": debate.bull_argument or "",
                    "bear_argument": debate.bear_argument or "",
                    "consensus": debate.final_consensus or ""
                }
            else:
                logger.error("Debate returned no result", ticker=ticker)
                state["error"] = "Debate returned no result"
        
        except Exception as e:
            logger.error("Failed to conduct debate", error=str(e))
            state["error"] = str(e)
        
        return state
    
    def _create_proposal_from_debate(self, state: TradingState) -> TradingState:
        # Bull/Bear transcript to trade order
        try:
            ticker = state["ticker"]
            debate_result = state.get("debate_result") or {}
            analysis_result = state.get("analysis_result") or {}
            event_id = analysis_result.get("event_id")
            
            if not event_id:
                logger.error("No analysis event ID available for proposal", ticker=ticker)
                state["error"] = "No analysis event ID available"
                return state
            
            if not debate_result:
                logger.error("No debate result available for proposal", ticker=ticker)
                state["error"] = "No debate result available"
                return state
            
            # Get snapshot, fetch and save if it doesn't exist
            snapshot = self.db.get_latest_snapshot(ticker)
            if not snapshot:
                logger.info("No snapshot found, fetching from API", ticker=ticker)
                try:
                    snapshot_data = self.finnhub.get_stock_snapshot(ticker)
                    from backend.database.models import StockSnapshot
                    snapshot_id = self.db.save_stock_snapshot(StockSnapshot(**snapshot_data))
                    snapshot = self.db.get_latest_snapshot(ticker)
                    if not snapshot:
                        logger.error("Failed to retrieve snapshot after saving", ticker=ticker)
                        state["error"] = "Failed to retrieve snapshot after saving"
                        return state
                except Exception as e:
                    logger.error("Failed to fetch and save snapshot", ticker=ticker, error=str(e))
                    state["error"] = f"Failed to fetch snapshot: {str(e)}"
                    return state
            
            system_prompt = """Based on a debate between bull and bear analysts, create a trade proposal.

BULL ARGUMENT:
{bull_argument}

BEAR ARGUMENT:
{bear_argument}

CONSENSUS:
{consensus}

CRITICAL REQUIREMENTS FOR TRADING:
- You MUST have STRONG confidence (70+) to propose BUY or SELL
- If confidence is below 70, you MUST return "HOLD" regardless of the debate outcome
- Only trade when there's CONVERGING EVIDENCE from MULTIPLE news sources
- Consider transaction costs - only trade if the opportunity clearly justifies them
- Be conservative: when in doubt, HOLD
- A single news item is NOT sufficient - you need multiple independent sources confirming the narrative

Return JSON:
{{
  "action": "BUY" | "SELL" | "HOLD",
  "quantity": number of shares (0 if HOLD),
  "reasoning": "Detailed reasoning. Must explain why confidence is high enough to trade, or why HOLD is appropriate.",
  "confidence_score": 0-100 (MUST be 70+ for BUY/SELL, can be lower for HOLD)
}}

IMPORTANT: If confidence_score < 70, action MUST be "HOLD"."""
            
            user_prompt = system_prompt.format(
                bull_argument=debate_result.get("bull_argument", ""),
                bear_argument=debate_result.get("bear_argument", ""),
                consensus=debate_result.get("consensus", "")
            )
            
            response = self.trader.llm.chat_completion(
                [{"role": "user", "content": user_prompt}],
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            proposal_data = json.loads(response)
            
            # Enforce minimum confidence threshold
            confidence_score = proposal_data.get("confidence_score", 0)
            action = proposal_data.get("action", "HOLD")
            
            # Force HOLD if confidence is too low for trading
            if action in ("BUY", "SELL") and confidence_score < 70:
                logger.warning(
                    "Proposal confidence too low for trading",
                    ticker=ticker,
                    action=action,
                    confidence=confidence_score,
                    required=70
                )
                action = "HOLD"
                proposal_data["action"] = "HOLD"
                proposal_data["quantity"] = 0
                proposal_data["reasoning"] = f"{proposal_data.get('reasoning', '')} [Rejected: Confidence {confidence_score} < 70 required for trading]"
            
            proposal = TradeProposal(
                ticker=ticker,
                action=action,
                quantity=proposal_data.get("quantity", 0) if action != "HOLD" else 0,
                proposed_price=snapshot.get("price") if snapshot else None,
                reasoning=proposal_data.get("reasoning", ""),
                confidence_score=confidence_score,
                analysis_event_id=event_id,
                debate_id=debate_result.get("debate_id"),
                status="PENDING"
            )
            
            proposal_id = self.db.save_trade_proposal(proposal)
            proposal.id = proposal_id
            state["trade_proposal"] = proposal
        
        except Exception as e:
            logger.error("Failed to create proposal from debate", error=str(e))
            state["error"] = str(e)
        
        return state
    
    def _review_proposal(self, state: TradingState) -> TradingState:
        # Risk check by portfolio manager
        try:
            proposal = state.get("trade_proposal")
            if not proposal:
                state["error"] = "No proposal to review"
                return state
            
            decision = self.portfolio.review_proposal(proposal)
            state["portfolio_decision"] = decision
        
        except Exception as e:
            logger.error("Failed to review proposal", error=str(e))
            state["error"] = str(e)
        
        return state
    
    def _should_execute(self, state: TradingState) -> str:
        # Decision branch
        decision = state.get("portfolio_decision", {})
        if decision.get("decision") == "APPROVE":
            return "execute"
        return "reject"
    
    def _execute_trade(self, state: TradingState) -> TradingState:
        # Call Alpaca
        try:
            proposal = state.get("trade_proposal")
            decision = state.get("portfolio_decision", {})
            
            if not proposal or not decision:
                state["error"] = "Missing proposal or decision"
                return state
            
            executed = self.portfolio.execute_trade(proposal, decision)
            if executed:
                state["executed_trade"] = {
                    "id": executed.id,
                    "ticker": executed.ticker,
                    "action": executed.action,
                    "quantity": executed.quantity,
                    "price": float(executed.execution_price)
                }
        
        except Exception as e:
            logger.error("Failed to execute trade", error=str(e))
            state["error"] = str(e)
        
        return state
    
    def run(self, ticker: str) -> TradingState:
        # Main entry for one ticker scan
        initial_state: TradingState = {
            "ticker": ticker,
            "analysis_result": None,
            "needs_debate": False,
            "debate_result": None,
            "trade_proposal": None,
            "portfolio_decision": None,
            "executed_trade": None,
            "error": None
        }
        
        result = self.graph.invoke(initial_state)
        logger.info("Trading workflow completed", ticker=ticker, error=result.get("error"))
        
        return result

