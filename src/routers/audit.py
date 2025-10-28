"""
Risk audit endpoint (placeholder).
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_db
from src.models.schemas import AuditOut
from src.routers.health import increment_metric

router = APIRouter()


@router.get("/audit/{doc_id}", response_model=AuditOut)
async def audit_contract(doc_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Audit contract for risky clauses.
    
    TODO: Implement rule-based + LLM risk detection.
    """
    increment_metric("audits_total")
    
    raise NotImplementedError("Audit endpoint not yet implemented")
