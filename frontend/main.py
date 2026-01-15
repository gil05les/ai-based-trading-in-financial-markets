# Frontend startup
import uvicorn
import structlog

from frontend.api import app


if __name__ == "__main__":
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer()
        ]
    )
    
    uvicorn.run(
        "frontend.api:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )

