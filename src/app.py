"""
Main FastAPI application with CORS, middleware, and route registration.
"""

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.core.config import get_settings
from src.core.logging import logger
from src.db.engine import init_db
from src.routers import health, ingest, extract, ask, audit, search


# Application lifecycle management
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Initialize resources on startup, cleanup on shutdown."""
    logger.info("Starting Contract Intelligence API...")
    
    # Initialize database
    await init_db()
    logger.info("Database initialized")
    
    yield
    
    logger.info("Shutting down Contract Intelligence API...")


# Create FastAPI app
settings = get_settings()
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description="RAG-based API for contract analysis with extraction, Q&A, and risk auditing",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request timing middleware
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Add X-Process-Time header to all responses."""
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response


# Exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler with PII-redacted logging."""
    logger.error(
        "Unhandled exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(ingest.router, prefix="/api/v1", tags=["Ingestion"])
app.include_router(search.router, prefix="/api/v1", tags=["Search"])
app.include_router(extract.router, prefix="/api/v1", tags=["Extraction"])
app.include_router(ask.router, prefix="/api/v1", tags=["Q&A"])
app.include_router(audit.router, prefix="/api/v1", tags=["Audit"])


# Root endpoint
@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint redirects to docs."""
    return {
        "message": "Contract Intelligence API",
        "version": settings.API_VERSION,
        "docs": "/docs",
    }
