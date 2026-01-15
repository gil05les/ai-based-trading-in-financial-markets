-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Raw scraped articles
CREATE TABLE IF NOT EXISTS articles_raw (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    raw_html TEXT NOT NULL,
    scraped_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    ticker VARCHAR(10),
    source_url TEXT
);

-- Cleaned articles with LLM extraction
CREATE TABLE IF NOT EXISTS articles_cleaned (
    id SERIAL PRIMARY KEY,
    raw_article_id INTEGER REFERENCES articles_raw(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    ticker VARCHAR(10),
    content_text TEXT NOT NULL,
    is_usable BOOLEAN NOT NULL,
    reason TEXT,
    timestamp TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    llm_model VARCHAR(100),
    llm_response JSONB
);

-- Article embeddings for vector search
CREATE TABLE IF NOT EXISTS article_embeddings (
    id SERIAL PRIMARY KEY,
    cleaned_article_id INTEGER REFERENCES articles_cleaned(id) ON DELETE CASCADE,
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_article_embeddings_vector ON article_embeddings 
USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_articles_cleaned_ticker ON articles_cleaned(ticker);
CREATE INDEX IF NOT EXISTS idx_articles_cleaned_timestamp ON articles_cleaned(timestamp);
CREATE INDEX IF NOT EXISTS idx_articles_cleaned_usable ON articles_cleaned(is_usable);

-- Stock price snapshots
CREATE TABLE IF NOT EXISTS stock_snapshots (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    price DECIMAL(12, 4) NOT NULL,
    volume BIGINT,
    high DECIMAL(12, 4),
    low DECIMAL(12, 4),
    open_price DECIMAL(12, 4),
    close_price DECIMAL(12, 4),
    market_cap BIGINT,
    pe_ratio DECIMAL(10, 4),
    dividend_yield DECIMAL(8, 4),
    snapshot_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    data_source VARCHAR(50) DEFAULT 'finnhub'
);

CREATE INDEX IF NOT EXISTS idx_stock_snapshots_ticker ON stock_snapshots(ticker);
CREATE INDEX IF NOT EXISTS idx_stock_snapshots_time ON stock_snapshots(snapshot_time);

-- Analysis events (trader agent reasoning)
CREATE TABLE IF NOT EXISTS analysis_events (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    reasoning TEXT NOT NULL,
    input_data JSONB,
    output_data JSONB,
    agent_name VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_analysis_events_ticker ON analysis_events(ticker);
CREATE INDEX IF NOT EXISTS idx_analysis_events_type ON analysis_events(event_type);
CREATE INDEX IF NOT EXISTS idx_analysis_events_created ON analysis_events(created_at);

-- Debate transcripts
CREATE TABLE IF NOT EXISTS debates (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    debate_type VARCHAR(50) DEFAULT 'bull_vs_bear',
    transcript JSONB NOT NULL,
    bull_argument TEXT NOT NULL,
    bear_argument TEXT NOT NULL,
    final_consensus TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    trader_agent_id INTEGER REFERENCES analysis_events(id)
);

CREATE INDEX IF NOT EXISTS idx_debates_ticker ON debates(ticker);
CREATE INDEX IF NOT EXISTS idx_debates_created ON debates(created_at);

-- Trade proposals from trader agent
CREATE TABLE IF NOT EXISTS trade_proposals (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,
    action VARCHAR(10) NOT NULL CHECK (action IN ('BUY', 'SELL', 'HOLD')),
    quantity INTEGER NOT NULL,
    proposed_price DECIMAL(12, 4),
    reasoning TEXT NOT NULL,
    confidence_score DECIMAL(5, 2) CHECK (confidence_score >= 0 AND confidence_score <= 100),
    analysis_event_id INTEGER REFERENCES analysis_events(id),
    debate_id INTEGER REFERENCES debates(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXECUTED'))
);

CREATE INDEX IF NOT EXISTS idx_trade_proposals_ticker ON trade_proposals(ticker);
CREATE INDEX IF NOT EXISTS idx_trade_proposals_status ON trade_proposals(status);
CREATE INDEX IF NOT EXISTS idx_trade_proposals_created ON trade_proposals(created_at);

-- Executed trades
CREATE TABLE IF NOT EXISTS executed_trades (
    id SERIAL PRIMARY KEY,
    trade_proposal_id INTEGER REFERENCES trade_proposals(id),
    ticker VARCHAR(10) NOT NULL,
    action VARCHAR(10) NOT NULL CHECK (action IN ('BUY', 'SELL')),
    quantity INTEGER NOT NULL,
    execution_price DECIMAL(12, 4) NOT NULL,
    alpaca_order_id VARCHAR(100),
    portfolio_manager_reasoning TEXT,
    executed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) DEFAULT 'FILLED' CHECK (status IN ('FILLED', 'PARTIAL', 'CANCELLED', 'REJECTED'))
);

CREATE INDEX IF NOT EXISTS idx_executed_trades_ticker ON executed_trades(ticker);
CREATE INDEX IF NOT EXISTS idx_executed_trades_executed ON executed_trades(executed_at);
CREATE INDEX IF NOT EXISTS idx_executed_trades_status ON executed_trades(status);

