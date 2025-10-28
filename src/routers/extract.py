"""
Structured field extraction endpoint (placeholder).
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_db
from src.models.schemas import ExtractionOut
from src.routers.health import increment_metric

router = APIRouter()


@router.post("/extract/{doc_id}", response_model=ExtractionOut)
async def extract_fields(doc_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Extract structured fields from contract.
    
    TODO: Implement LLM-based extraction with regex fallbacks.
    """
    increment_metric("extractions_total")
    
    raise NotImplementedError("Extraction endpoint not yet implemented")
