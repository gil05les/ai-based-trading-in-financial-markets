# Config from env
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices


class Settings(BaseSettings):
    # App settings via Pydantic
    
    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore"
    )
    
    finnhub_api_key: str = Field(..., validation_alias=AliasChoices("FINNHUB_API_KEY", "FINNHUB_KEY"))
    alpaca_api_key: str = Field(..., validation_alias=AliasChoices("ALPACA_API_KEY", "ALPACA_KEY"))
    alpaca_api_secret: str = Field(..., validation_alias=AliasChoices("ALPACA_API_SECRET", "ALPACA_SECRET"))
    openai_api_key: str = Field(..., validation_alias=AliasChoices("OPENAI_API_KEY", "OPENAI_KEY"))
    postgres_url: str = Field(..., validation_alias=AliasChoices("POSTGRES_URL", "DATABASE_URL"))
    stock_list: str = Field(..., validation_alias=AliasChoices("STOCK_LIST", "STOCKS"))
    log_level: str = Field(default="INFO", validation_alias=AliasChoices("LOG_LEVEL", "LOGLEVEL"))

    @property
    def finnhub_key(self) -> str:
        return self.finnhub_api_key
    @property
    def stocks(self) -> List[str]:
        # Parse STOCK_LIST string
        return [s.strip().upper() for s in self.stock_list.split(",") if s.strip()]


settings = Settings()
