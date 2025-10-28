"""
Application configuration management using Pydantic Settings.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Settings
    API_TITLE: str = Field(default="Contract Intelligence API")
    API_VERSION: str = Field(default="0.1.0")
    ENVIRONMENT: Literal["development", "staging", "production"] = Field(
        default="development"
    )
    DEBUG: bool = Field(default=False)

    # Server Settings
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)
    WORKERS: int = Field(default=4)

    # Database
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./app.db",
        description="Database connection URL",
    )

    # OpenRouter Configuration
    OPENROUTER_API_KEY: str = Field(
        ..., description="OpenRouter API key for LLM access"
    )

    # LLM Settings
    LLM_MODEL: str = Field(
        default="anthropic/claude-3.5-sonnet",
        description="Model for extraction and Q&A",
    )
    EMBEDDING_MODEL: str = Field(
        default="openai/text-embedding-ada-002", description="Embedding model"
    )
    CHUNK_SIZE_TOKENS: int = Field(default=500)
    CHUNK_OVERLAP_TOKENS: int = Field(default=100)

    # File Upload
    MAX_UPLOAD_SIZE_MB: int = Field(default=50)

    # Vector Store
    FAISS_INDEX_PATH: str = Field(default="./data/faiss_index.bin")

    # Logging
    LOG_LEVEL: str = Field(default="INFO")

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
