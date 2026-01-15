# Base agent for all system agents
from typing import Optional, Any
import structlog
from backend.clients import LLMClient
from backend.database import DatabaseClient

class BaseAgent:
    # Base class for all agents
    
    def __init__(
        self, 
        llm: LLMClient, 
        db: Optional[DatabaseClient] = None,
        **kwargs: Any
    ):
        # Setup core clients
        self.llm = llm
        self.db = db
        self.logger = structlog.get_logger(self.__class__.__name__)
        
        # Additional attributes can be passed via kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)
            
        self.logger.info("Agent initialized")
