# Postgre client with vector support
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from decimal import Decimal
import structlog
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from psycopg2.pool import ThreadedConnectionPool
from pgvector.psycopg2 import register_vector
import numpy as np

from backend.config import settings
from backend.database.models import (
    ArticleRaw,
    ArticleCleaned,
    ArticleEmbedding,
    StockSnapshot,
    AnalysisEvent,
    Debate,
    TradeProposal,
    ExecutedTrade,
)


logger = structlog.get_logger(__name__)


class DatabaseClient:
    # Handles persistence and vector search
    
    def __init__(self):
        # Create pool
        self.pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=settings.postgres_url,
        )
        logger.info("Database connection pool initialized")
    
    def _get_conn(self):
        # Checkout from pool
        return self.pool.getconn()
    
    def _put_conn(self, conn):
        # Checkin to pool
        self.pool.putconn(conn)
    
    def _execute_query(self, query: str, params: tuple = None, fetch: bool = True):
        # Run SQL with cursor management
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                if fetch:
                    results = cur.fetchall()
                    conn.commit()
                    return results
                else:
                    conn.commit()
                    return cur.rowcount
        except Exception as e:
            conn.rollback()
            logger.error("Database query failed", error=str(e), query=query[:100])
            raise
        finally:
            self._put_conn(conn)
    
    # Article operations
    def save_raw_article(self, article: ArticleRaw) -> Optional[int]:
        # Save HTML before processing
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    INSERT INTO articles_raw (url, raw_html, ticker, source_url, scraped_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (url) DO UPDATE SET
                        raw_html = EXCLUDED.raw_html,
                        scraped_at = EXCLUDED.scraped_at
                    RETURNING id
                """
                cur.execute(
                    query,
                    (article.url, article.raw_html, article.ticker, article.source_url, article.scraped_at or datetime.utcnow())
                )
                result = cur.fetchone()
                if not result:
                    logger.error("No ID returned from INSERT", url=article.url[:60] if article.url else "no url")
                    conn.rollback()
                    return None
                article_id = result["id"]
                conn.commit()
                return article_id
        except Exception as e:
            conn.rollback()
            logger.error("Failed to save raw article", error=str(e), url=article.url[:60] if article.url else "no url")
            raise
        finally:
            self._put_conn(conn)
    
    def save_cleaned_article(self, article: ArticleCleaned) -> Optional[int]:
        # Save LLM output
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    INSERT INTO articles_cleaned 
                    (raw_article_id, title, ticker, content_text, is_usable, reason, timestamp, llm_model, llm_response)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """
                cur.execute(
                    query,
                    (
                        article.raw_article_id,
                        article.title,
                        article.ticker,
                        article.content_text,
                        article.is_usable,
                        article.reason,
                        article.timestamp,
                        article.llm_model,
                        json.dumps(article.llm_response) if article.llm_response else None,
                    )
                )
                result = cur.fetchone()
                if not result:
                    logger.error("No ID returned from cleaned article INSERT", raw_id=article.raw_article_id)
                    conn.rollback()
                    return None
                article_id = result["id"]
                conn.commit()
                return article_id
        except Exception as e:
            conn.rollback()
            logger.error("Failed to save cleaned article", error=str(e), raw_id=article.raw_article_id)
            raise
        finally:
            self._put_conn(conn)
    
    def save_raw_and_cleaned_article(self, raw_article: ArticleRaw, cleaned_article: ArticleCleaned) -> tuple[Optional[int], Optional[int]]:
        # Atomic save for both raw and cleaned
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # First, save raw article
                raw_query = """
                    INSERT INTO articles_raw (url, raw_html, ticker, source_url, scraped_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (url) DO UPDATE SET
                        raw_html = EXCLUDED.raw_html,
                        scraped_at = EXCLUDED.scraped_at
                    RETURNING id
                """
                cur.execute(
                    raw_query,
                    (raw_article.url, raw_article.raw_html, raw_article.ticker, raw_article.source_url, raw_article.scraped_at or datetime.utcnow())
                )
                raw_result = cur.fetchone()
                if not raw_result:
                    logger.error("No ID returned from raw article INSERT", url=raw_article.url[:60] if raw_article.url else "no url")
                    conn.rollback()
                    return None, None
                raw_id = raw_result["id"]
                
                # Then, save cleaned article using the same connection
                cleaned_query = """
                    INSERT INTO articles_cleaned 
                    (raw_article_id, title, ticker, content_text, is_usable, reason, timestamp, llm_model, llm_response)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """
                cur.execute(
                    cleaned_query,
                    (
                        raw_id,
                        cleaned_article.title,
                        cleaned_article.ticker,
                        cleaned_article.content_text,
                        cleaned_article.is_usable,
                        cleaned_article.reason,
                        cleaned_article.timestamp,
                        cleaned_article.llm_model,
                        json.dumps(cleaned_article.llm_response) if cleaned_article.llm_response else None,
                    )
                )
                cleaned_result = cur.fetchone()
                if not cleaned_result:
                    logger.error("No ID returned from cleaned article INSERT", raw_id=raw_id)
                    conn.rollback()
                    return None, None
                cleaned_id = cleaned_result["id"]
                
                conn.commit()
                return raw_id, cleaned_id
        except Exception as e:
            conn.rollback()
            logger.error("Failed to save raw and cleaned article", error=str(e), url=raw_article.url[:60] if raw_article.url else "no url")
            raise
        finally:
            self._put_conn(conn)
    
    def save_article_embedding(self, embedding: ArticleEmbedding) -> Optional[int]:
        # Save vector for search
        conn = self._get_conn()
        try:
            register_vector(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO article_embeddings (cleaned_article_id, embedding) VALUES (%s, %s) RETURNING id",
                    (embedding.cleaned_article_id, np.array(embedding.embedding))
                )
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else None
        except Exception as e:
            conn.rollback()
            logger.error("Failed to save embedding", error=str(e))
            raise
        finally:
            self._put_conn(conn)
    
    def get_recent_articles(self, ticker: Optional[str] = None, hours: int = 24) -> List[Dict[str, Any]]:
        # Filter cleaned news by time
        since = datetime.utcnow() - timedelta(hours=hours)
        if ticker:
            query = """
                SELECT ac.*, ae.embedding IS NOT NULL as has_embedding
                FROM articles_cleaned ac
                LEFT JOIN article_embeddings ae ON ac.id = ae.cleaned_article_id
                WHERE ac.ticker = %s AND ac.is_usable = true AND ac.timestamp >= %s
                ORDER BY ac.timestamp DESC
            """
            params = (ticker, since)
        else:
            query = """
                SELECT ac.*, ae.embedding IS NOT NULL as has_embedding
                FROM articles_cleaned ac
                LEFT JOIN article_embeddings ae ON ac.id = ae.cleaned_article_id
                WHERE ac.is_usable = true AND ac.timestamp >= %s
                ORDER BY ac.timestamp DESC
            """
            params = (since,)
        
        return self._execute_query(query, params)
    
    def get_article_by_id(self, article_id: int) -> Optional[Dict[str, Any]]:
        # Fetch detailed article info
        query = """
            SELECT 
                ac.*,
                ar.url as raw_url,
                ar.raw_html,
                ar.scraped_at,
                ae.embedding IS NOT NULL as has_embedding
            FROM articles_cleaned ac
            LEFT JOIN articles_raw ar ON ac.raw_article_id = ar.id
            LEFT JOIN article_embeddings ae ON ac.id = ae.cleaned_article_id
            WHERE ac.id = %s
        """
        results = self._execute_query(query, (article_id,))
        return results[0] if results else None
    
    def cleaned_article_exists(self, url: str, ticker: str) -> bool:
        # Avoid duplicate cleaning
        query = """
            SELECT COUNT(*) as count
            FROM articles_cleaned ac
            INNER JOIN articles_raw ar ON ac.raw_article_id = ar.id
            WHERE ar.url = %s AND ac.ticker = %s
        """
        results = self._execute_query(query, (url, ticker))
        return results[0]["count"] > 0 if results else False
    
    def vector_search(self, query_embedding: List[float], limit: int = 10, ticker: Optional[str] = None) -> List[Dict[str, Any]]:
        # Cosine similarity via pgvector
        conn = self._get_conn()
        try:
            register_vector(conn)
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if ticker:
                    cur.execute(
                        """
                        SELECT ac.*, 1 - (ae.embedding <=> %s::vector) as similarity
                        FROM article_embeddings ae
                        JOIN articles_cleaned ac ON ae.cleaned_article_id = ac.id
                        WHERE ac.ticker = %s AND ac.is_usable = true
                        ORDER BY ae.embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (np.array(query_embedding), ticker, np.array(query_embedding), limit)
                    )
                else:
                    cur.execute(
                        """
                        SELECT ac.*, 1 - (ae.embedding <=> %s::vector) as similarity
                        FROM article_embeddings ae
                        JOIN articles_cleaned ac ON ae.cleaned_article_id = ac.id
                        WHERE ac.is_usable = true
                        ORDER BY ae.embedding <=> %s::vector
                        LIMIT %s
                        """,
                        (np.array(query_embedding), np.array(query_embedding), limit)
                    )
                return cur.fetchall()
        except Exception as e:
            logger.error("Vector search failed", error=str(e))
            raise
        finally:
            self._put_conn(conn)
    
    # Stock snapshot operations
    def save_stock_snapshot(self, snapshot: StockSnapshot) -> int:
        # Log market data sample
        query = """
            INSERT INTO stock_snapshots 
            (ticker, price, volume, high, low, open_price, close_price, market_cap, pe_ratio, dividend_yield, snapshot_time, data_source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        result = self._execute_query(
            query,
            (
                snapshot.ticker,
                float(snapshot.price),
                snapshot.volume,
                float(snapshot.high) if snapshot.high else None,
                float(snapshot.low) if snapshot.low else None,
                float(snapshot.open_price) if snapshot.open_price else None,
                float(snapshot.close_price) if snapshot.close_price else None,
                snapshot.market_cap,
                float(snapshot.pe_ratio) if snapshot.pe_ratio else None,
                float(snapshot.dividend_yield) if snapshot.dividend_yield else None,
                snapshot.snapshot_time or datetime.utcnow(),
                snapshot.data_source,
            )
        )
        return result[0]["id"] if result else None
    
    def get_latest_snapshot(self, ticker: str) -> Optional[Dict[str, Any]]:
        # Most recent price
        query = """
            SELECT * FROM stock_snapshots
            WHERE ticker = %s
            ORDER BY snapshot_time DESC
            LIMIT 1
        """
        result = self._execute_query(query, (ticker,))
        return result[0] if result else None
    
    def get_recent_snapshots(self, ticker: str, hours: int = 24) -> List[Dict[str, Any]]:
        """Get recent stock snapshots."""
        since = datetime.utcnow() - timedelta(hours=hours)
        query = """
            SELECT * FROM stock_snapshots
            WHERE ticker = %s AND snapshot_time >= %s
            ORDER BY snapshot_time DESC
        """
        return self._execute_query(query, (ticker, since))
    
    # Analysis event operations
    def save_analysis_event(self, event: AnalysisEvent) -> Optional[int]:
        # Log agent reasoning
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    INSERT INTO analysis_events (ticker, event_type, reasoning, input_data, output_data, agent_name)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """
                cur.execute(
                    query,
                    (
                        event.ticker,
                        event.event_type,
                        event.reasoning,
                        json.dumps(event.input_data) if event.input_data else None,
                        json.dumps(event.output_data) if event.output_data else None,
                        event.agent_name,
                    )
                )
                result = cur.fetchone()
                if not result:
                    logger.error("No ID returned from analysis event INSERT", ticker=event.ticker)
                    conn.rollback()
                    return None
                event_id = result["id"]
                conn.commit()
                return event_id
        except Exception as e:
            conn.rollback()
            logger.error("Failed to save analysis event", error=str(e), ticker=event.ticker)
            raise
        finally:
            self._put_conn(conn)
    
    # Debate operations
    def save_debate(self, debate: Debate) -> int:
        # Save analyst transcript
        query = """
            INSERT INTO debates (ticker, debate_type, transcript, bull_argument, bear_argument, final_consensus, trader_agent_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        result = self._execute_query(
            query,
            (
                debate.ticker,
                debate.debate_type,
                json.dumps(debate.transcript),
                debate.bull_argument,
                debate.bear_argument,
                debate.final_consensus,
                debate.trader_agent_id,
            )
        )
        return result[0]["id"] if result else None
    
    # Trade proposal operations
    def save_trade_proposal(self, proposal: TradeProposal) -> Optional[int]:
        # Pending buy/sell orders
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    INSERT INTO trade_proposals 
                    (ticker, action, quantity, proposed_price, reasoning, confidence_score, analysis_event_id, debate_id, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """
                cur.execute(
                    query,
                    (
                        proposal.ticker,
                        proposal.action,
                        proposal.quantity,
                        float(proposal.proposed_price) if proposal.proposed_price else None,
                        proposal.reasoning,
                        proposal.confidence_score,
                        proposal.analysis_event_id,
                        proposal.debate_id,
                        proposal.status,
                    )
                )
                result = cur.fetchone()
                if not result:
                    logger.error("No ID returned from trade proposal INSERT", ticker=proposal.ticker, analysis_event_id=proposal.analysis_event_id)
                    conn.rollback()
                    return None
                proposal_id = result["id"]
                conn.commit()
                return proposal_id
        except Exception as e:
            conn.rollback()
            logger.error("Failed to save trade proposal", error=str(e), ticker=proposal.ticker, analysis_event_id=proposal.analysis_event_id)
            raise
        finally:
            self._put_conn(conn)
    
    def get_pending_proposals(self) -> List[Dict[str, Any]]:
        # Unprocessed orders
        query = """
            SELECT * FROM trade_proposals
            WHERE status = 'PENDING'
            ORDER BY created_at DESC
        """
        return self._execute_query(query)
    
    def update_proposal_status(self, proposal_id: int, status: str):
        # Transitions pending -> executed/rejected
        query = "UPDATE trade_proposals SET status = %s WHERE id = %s"
        self._execute_query(query, (status, proposal_id), fetch=False)
    
    # Executed trade operations
    def save_executed_trade(self, trade: ExecutedTrade) -> int:
        # Record final Alpaca order
        query = """
            INSERT INTO executed_trades 
            (trade_proposal_id, ticker, action, quantity, execution_price, alpaca_order_id, portfolio_manager_reasoning, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        result = self._execute_query(
            query,
            (
                trade.trade_proposal_id,
                trade.ticker,
                trade.action,
                trade.quantity,
                float(trade.execution_price),
                trade.alpaca_order_id,
                trade.portfolio_manager_reasoning,
                trade.status,
            )
        )
        return result[0]["id"] if result else None
    
    def get_recent_trades(self, ticker: Optional[str] = None, days: int = 30) -> List[Dict[str, Any]]:
        # Done trades history
        since = datetime.utcnow() - timedelta(days=days)
        if ticker:
            query = """
                SELECT * FROM executed_trades
                WHERE ticker = %s AND executed_at >= %s
                ORDER BY executed_at DESC
            """
            params = (ticker, since)
        else:
            query = """
                SELECT * FROM executed_trades
                WHERE executed_at >= %s
                ORDER BY executed_at DESC
            """
            params = (since,)
        return self._execute_query(query, params)
    
    def has_traded_today(self) -> bool:
        # Safety check for single trade per day
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        query = """
            SELECT COUNT(*) as count FROM executed_trades
            WHERE executed_at >= %s
        """
        result = self._execute_query(query, (today_start,))
        count = result[0]["count"] if result else 0
        return count > 0
    
    def close(self):
        # Shutdown pool
        if self.pool:
            self.pool.closeall()
            logger.info("Database connection pool closed")
