"""
RAG Q&A endpoints with semantic search and citation support.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse

from src.core.logging import logger
from src.db.engine import get_db
from src.models.schemas import AskRequest, AskResponse
from src.routers.health import increment_metric
from src.services.rag import rag_query

router = APIRouter()


@router.post("/ask", response_model=AskResponse)
async def ask_question(request: AskRequest, db: AsyncSession = Depends(get_db)):
    """
    Answer question using RAG with citations.
    
    Process:
    1. Embed query using OpenRouter
    2. Search FAISS vector store for top-k relevant chunks
    3. Filter by doc_ids if provided
    4. Rerank chunks using LLM cross-encoder scoring
    5. Generate grounded answer from top-3 chunks
    6. Parse and return citations in format [doc_id:page:start-end]
    
    Returns answer with precise character-level citations.
    """
    increment_metric("qa_requests_total")
    
    logger.info(
        "Q&A request received",
        question=request.question[:100],
        doc_ids=request.doc_ids
    )
    
    try:
        answer, citations, confidence = await rag_query(
            question=request.question,
            db=db,
            doc_ids=request.doc_ids,
            top_k=3  # Limit to top-3 to reduce hallucination
        )
        
        logger.info(
            "Q&A completed",
            answer_length=len(answer),
            citations_count=len(citations),
            confidence=confidence
        )
        
        return AskResponse(
            answer=answer,
            confidence=confidence,
            citations=citations
        )
        
    except Exception as e:
        logger.error(
            "Q&A failed",
            question=request.question[:100],
            error=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate answer: {str(e)}"
        )


@router.post("/ask/stream")
async def ask_question_stream(request: AskRequest, db: AsyncSession = Depends(get_db)):
    """
    Streaming Q&A via Server-Sent Events.
    
    TODO: Implement SSE streaming with OpenRouter.
    """
    increment_metric("qa_requests_total")
    
    async def event_generator():
        yield 'data: {"type": "error", "message": "Streaming not yet implemented"}\n\n'
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
