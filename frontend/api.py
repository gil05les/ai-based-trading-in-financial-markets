# Dashboard API
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Dict, Any
import asyncio
import json
import structlog
import os
from pathlib import Path
from datetime import datetime, timedelta

from backend.database import DatabaseClient
from backend.clients import AlpacaClient
from backend.config import settings


logger = structlog.get_logger(__name__)

app = FastAPI(title="Trading System Dashboard")

db = DatabaseClient()
alpaca = AlpacaClient(paper=True)

FRONTEND_DIR = Path(__file__).parent


class ConnectionManager:
    # WS client tracker
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    
    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass


manager = ConnectionManager()


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    # Return index.html
    html_path = FRONTEND_DIR / "index.html"
    if html_path.exists():
        return FileResponse(html_path)
    else:
        return HTMLResponse(content="<h1>Dashboard not found</h1>", status_code=404)


@app.get("/api/status")
async def get_status():
    # Account and systems health
    try:
        account = alpaca.get_account()
        positions = alpaca.get_positions()
        
        return {
            "status": "running",
            "account": account,
            "positions_count": len(positions),
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error("Failed to get status", error=str(e))
        return {"status": "error", "error": str(e)}


@app.get("/api/positions")
async def get_positions():
    # Current portfolio
    try:
        positions = alpaca.get_positions()
        return {"positions": positions}
    except Exception as e:
        logger.error("Failed to get positions", error=str(e))
        return {"positions": [], "error": str(e)}


@app.get("/api/trades")
async def get_trades(limit: int = 50):
    # Past week's orders
    try:
        trades = db.get_recent_trades(days=7)
        return {"trades": trades[:limit]}
    except Exception as e:
        logger.error("Failed to get trades", error=str(e))
        return {"trades": [], "error": str(e)}


@app.get("/api/proposals")
async def get_proposals(limit: int = 20):
    # What the system wants to do
    try:
        recent = db._execute_query(
            "SELECT * FROM trade_proposals ORDER BY created_at DESC LIMIT %s",
            (limit,)
        )
        return {"proposals": recent}
    except Exception as e:
        logger.error("Failed to get proposals", error=str(e))
        return {"proposals": [], "error": str(e)}


@app.get("/api/articles")
async def get_articles(ticker: str = None, limit: int = 20):
    # Scraped news
    try:
        articles = db.get_recent_articles(ticker=ticker, hours=24)
        return {"articles": articles[:limit]}
    except Exception as e:
        logger.error("Failed to get articles", error=str(e))
        return {"articles": [], "error": str(e)}


@app.get("/api/articles/{article_id}")
async def get_article(article_id: int):
    # Full article with trace
    try:
        article = db.get_article_by_id(article_id)
        if not article:
            return {"error": "Article not found"}, 404
        
        # Get related analysis events
        analysis_events = db._execute_query(
            "SELECT * FROM analysis_events WHERE ticker = %s ORDER BY created_at DESC LIMIT 5",
            (article.get('ticker'),)
        ) if article.get('ticker') else []
        
        # Get related debates
        debates = db._execute_query(
            "SELECT * FROM debates WHERE ticker = %s ORDER BY created_at DESC LIMIT 3",
            (article.get('ticker'),)
        ) if article.get('ticker') else []
        
        # Get related trade proposals
        proposals = db._execute_query(
            "SELECT * FROM trade_proposals WHERE ticker = %s ORDER BY created_at DESC LIMIT 5",
            (article.get('ticker'),)
        ) if article.get('ticker') else []
        
        return {
            "article": article,
            "related_analysis": analysis_events,
            "related_debates": debates,
            "related_proposals": proposals
        }
    except Exception as e:
        logger.error("Failed to get article", article_id=article_id, error=str(e))
        return {"error": str(e)}, 500


@app.get("/api/snapshots")
async def get_snapshots(ticker: str = None):
    # Price data
    try:
        if ticker:
            snapshots = db.get_recent_snapshots(ticker, hours=24)
        else:
            snapshots = []
            for t in settings.stocks:
                latest = db.get_latest_snapshot(t)
                if latest:
                    snapshots.append(latest)
        return {"snapshots": snapshots}
    except Exception as e:
        logger.error("Failed to get snapshots", error=str(e))
        return {"snapshots": [], "error": str(e)}


@app.get("/api/analysis")
async def get_analysis(limit: int = 20):
    # LLM logs
    try:
        events = db._execute_query(
            "SELECT * FROM analysis_events ORDER BY created_at DESC LIMIT %s",
            (limit,)
        )
        return {"events": events}
    except Exception as e:
        logger.error("Failed to get analysis", error=str(e))
        return {"events": [], "error": str(e)}


@app.get("/api/trader-interest")
async def get_trader_interest(limit: int = 20):
    # Hot tickers
    try:
        # Get recent ticker analysis events
        events = db._execute_query(
            """
            SELECT 
                ticker,
                output_data->>'is_interesting' as is_interesting,
                output_data->>'needs_debate' as needs_debate,
                output_data->>'confidence' as confidence,
                output_data->>'reasoning' as reasoning,
                reasoning as full_reasoning,
                created_at,
                id
            FROM analysis_events 
            WHERE event_type = 'ticker_analysis'
            ORDER BY created_at DESC 
            LIMIT %s
            """,
            (limit,)
        )
        
        # Separate interesting vs not interesting
        interesting = [e for e in events if e.get('is_interesting') == 'true' or e.get('is_interesting') == True]
        not_interesting = [e for e in events if e.get('is_interesting') != 'true' and e.get('is_interesting') != True]
        
        return {
            "interesting": interesting,
            "not_interesting": not_interesting[:10],  # Limit not interesting to avoid clutter
            "total_analyzed": len(events)
        }
    except Exception as e:
        logger.error("Failed to get trader interest", error=str(e))
        return {"interesting": [], "not_interesting": [], "total_analyzed": 0, "error": str(e)}


@app.get("/api/debates")
async def get_debates(limit: int = 10):
    # Bull/Bear transcripts
    try:
        debates = db._execute_query(
            "SELECT * FROM debates ORDER BY created_at DESC LIMIT %s",
            (limit,)
        )
        return {"debates": debates}
    except Exception as e:
        logger.error("Failed to get debates", error=str(e))
        return {"debates": [], "error": str(e)}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # UI updates
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(5)
            status = await get_status()
            positions = await get_positions()
            trades = await get_trades(limit=10)
            
            await websocket.send_json({
                "type": "update",
                "data": {
                    "status": status,
                    "positions": positions.get("positions", []),
                    "recent_trades": trades.get("trades", [])[:5]
                },
                "timestamp": datetime.utcnow().isoformat()
            })
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.on_event("startup")
async def startup_event():
    # Boots up
    logger.info("Frontend API started")


@app.on_event("shutdown")
async def shutdown_event():
    # Cleanup on exit
    db.close()
    logger.info("Frontend API stopped")

