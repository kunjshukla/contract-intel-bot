"""
Pytest configuration and fixtures.
"""

import os
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# Set up test environment variables before importing app
os.environ.setdefault("OPENROUTER_API_KEY", "test-key-for-testing")
os.environ.setdefault("FAISS_INDEX_PATH", ":memory:")

from src.app import app
from src.db.engine import Base, get_db


# Test database setup
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


async def override_get_db():
    """Override database dependency for testing."""
    async with TestSessionLocal() as session:
        yield session


@pytest.fixture(scope="function")
async def db_session():
    """Create test database tables."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async with TestSessionLocal() as session:
        yield session
    
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="function")
async def db(db_session):
    """Alias for db_session to match test expectations."""
    return db_session


@pytest.fixture(scope="function")
async def client(db_session):
    """Create test client with database override."""
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
async def async_client(client):
    """Alias for client to support both naming conventions."""
    return client
