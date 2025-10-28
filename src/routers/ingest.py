"""
Document ingestion endpoint (placeholder).
"""

from fastapi import APIRouter, UploadFile, File, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_db
from src.models.schemas import DocumentOut
from src.routers.health import increment_metric

router = APIRouter()


@router.post("/ingest", response_model=DocumentOut, status_code=201)
async def ingest_document(
    file: UploadFile = File(...), db: AsyncSession = Depends(get_db)
):
    """
    Upload and ingest a PDF contract.
    
    TODO: Implement PDF parsing, chunking, and embedding.
    """
    increment_metric("ingests_total")
    
    # Placeholder response
    raise NotImplementedError("Ingestion endpoint not yet implemented")
