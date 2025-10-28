"""
RAG Q&A endpoints (placeholder).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse

from src.db.engine import get_db
from src.models.schemas import AskRequest, AskResponse
from src.routers.health import increment_metric

router = APIRouter()


@router.post("/ask", response_model=AskResponse)
async def ask_question(request: AskRequest, db: AsyncSession = Depends(get_db)):
    """
    Answer question using RAG with citations.
    
    TODO: Implement FAISS retrieval + LLM answer generation.
    """
    increment_metric("qa_requests_total")
    
    raise NotImplementedError("Q&A endpoint not yet implemented")


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
