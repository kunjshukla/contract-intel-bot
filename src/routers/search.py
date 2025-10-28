"""
Vector search endpoint for testing RAG pipeline.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import logger
from src.core.vector_store import get_vector_store
from src.db.engine import get_db
from src.services.chunking import search_similar_chunks

router = APIRouter()


class SearchRequest(BaseModel):
    """Search request for vector similarity."""

    query: str = Field(..., min_length=1, max_length=1000, description="Search query")
    k: int = Field(default=5, ge=1, le=20, description="Number of results")
    doc_id: Optional[UUID] = Field(None, description="Filter by document ID")


class ChunkResult(BaseModel):
    """Search result chunk."""

    chunk_id: str
    doc_id: str
    page: int
    text: str
    score: float
    start_char: int
    end_char: int


class SearchResponse(BaseModel):
    """Search response with results."""

    query: str
    results: List[ChunkResult]
    count: int


@router.post("/search", response_model=SearchResponse)
async def search_chunks(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Search for similar chunks using vector similarity.
    
    Uses FAISS for fast approximate nearest neighbor search on embeddings.
    
    Args:
        request: Search parameters (query, k, optional doc_id filter)
        db: Database session (for future use)
        
    Returns:
        SearchResponse with ranked results
        
    Example:
        POST /api/v1/search
        {
            "query": "payment terms",
            "k": 5,
            "doc_id": "optional-uuid"
        }
    """
    logger.info(
        "Vector search request",
        query_length=len(request.query),
        k=request.k,
        doc_id=str(request.doc_id) if request.doc_id else None,
    )
    
    # Search using FAISS
    results = await search_similar_chunks(
        query=request.query,
        k=request.k,
        doc_id=request.doc_id,
    )
    
    # Convert to response format
    chunk_results = [
        ChunkResult(
            chunk_id=result["chunk_id"],
            doc_id=result["doc_id"],
            page=result["page"],
            text=result["text"],
            score=result["score"],
            start_char=result["start_char"],
            end_char=result["end_char"],
        )
        for result in results
    ]
    
    return SearchResponse(
        query=request.query,
        results=chunk_results,
        count=len(chunk_results),
    )


@router.get("/search/simple", response_model=SearchResponse)
async def search_simple(
    q: str = Query(..., min_length=1, description="Search query"),
    k: int = Query(5, ge=1, le=20, description="Number of results"),
    doc_id: Optional[UUID] = Query(None, description="Filter by document ID"),
):
    """
    Simple GET-based search endpoint.
    
    Example:
        GET /api/v1/search/simple?q=payment+terms&k=3
    """
    request = SearchRequest(query=q, k=k, doc_id=doc_id)
    
    results = await search_similar_chunks(
        query=request.query,
        k=request.k,
        doc_id=request.doc_id,
    )
    
    chunk_results = [
        ChunkResult(
            chunk_id=result["chunk_id"],
            doc_id=result["doc_id"],
            page=result["page"],
            text=result["text"],
            score=result["score"],
            start_char=result["start_char"],
            end_char=result["end_char"],
        )
        for result in results
    ]
    
    return SearchResponse(
        query=request.query,
        results=chunk_results,
        count=len(chunk_results),
    )


@router.get("/vector-stats")
async def get_vector_stats():
    """
    Get FAISS index statistics.
    
    Returns info about the vector store: total vectors, dimension, etc.
    """
    vector_store = get_vector_store()
    stats = vector_store.get_stats()
    
    logger.info("Vector stats requested", **stats)
    
    return stats
