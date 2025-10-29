"""
Risk audit endpoint using hybrid rule-based + LLM detection.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import logger
from src.db.engine import get_db
from src.db.models import Audit, Document
from src.models.schemas import AuditOut, Finding
from src.routers.health import increment_metric
from src.services.audit import audit_document

router = APIRouter()


def calculate_risk_score(findings: list[Finding]) -> float:
    """
    Calculate overall risk score (0.0 - 10.0) from findings.
    
    Scoring:
    - critical: 10.0 points
    - high: 5.0 points
    - medium: 2.0 points
    - low: 0.5 points
    
    Capped at 10.0 max.
    """
    severity_scores = {
        'critical': 10.0,
        'high': 5.0,
        'medium': 2.0,
        'low': 0.5
    }
    
    total = sum(severity_scores.get(f.severity, 0) for f in findings)
    return min(total, 10.0)


@router.post("/audit/{doc_id}", response_model=AuditOut, status_code=200)
async def audit_contract(doc_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Audit contract for compliance and business risks using hybrid detection.
    
    Process:
    1. Verify document exists and has chunks
    2. Run rule-based pattern matching (fast, deterministic)
    3. Run LLM analysis for nuanced risks (context-aware)
    4. Merge and deduplicate findings
    5. Calculate risk score
    6. Store audit results in database
    
    Detection Methods:
    - **Rule-Based**: Regex patterns for common risks (auto-renewal, unlimited liability)
    - **LLM-Based**: Claude 3.5 Sonnet for nuanced clause analysis
    
    Risk Categories:
    - Auto-renewal with short notice (<30 days)
    - Unlimited liability (no cap)
    - Broad indemnity clauses
    - Evergreen/perpetual terms
    - One-sided termination rights
    - Unreasonable confidentiality
    - Payment risks (>60 days)
    - IP assignment issues
    - Non-compete/non-solicit
    - Dispute resolution concerns
    
    Args:
        doc_id: UUID of the document to audit
        db: Database session
        
    Returns:
        AuditOut with findings, risk score, and timestamp
        
    Raises:
        HTTPException 404: Document not found
        HTTPException 422: Document has no text content
        HTTPException 500: Audit failed
    """
    logger.info("Audit request received", doc_id=str(doc_id))
    increment_metric("audits_total")
    
    try:
        # Step 1: Verify document exists
        stmt = select(Document).where(Document.id == doc_id)
        result = await db.execute(stmt)
        document = result.scalar_one_or_none()
        
        if not document:
            logger.warning("Document not found", doc_id=str(doc_id))
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
        
        logger.info(
            "Document retrieved",
            doc_id=str(doc_id),
            filename=document.filename
        )
        
        # Step 2-4: Run hybrid audit (rules + LLM)
        findings = await audit_document(db, doc_id, mode="hybrid")
        
        logger.info(
            "Audit analysis completed",
            doc_id=str(doc_id),
            findings_count=len(findings),
            high_severity=sum(1 for f in findings if f.severity in ('high', 'critical'))
        )
        
        # Step 5: Calculate risk score
        risk_score = calculate_risk_score(findings)
        
        logger.info(
            "Risk score calculated",
            doc_id=str(doc_id),
            risk_score=risk_score
        )
        
        # Step 6: Store audit in database
        # Check if audit already exists (upsert)
        stmt = select(Audit).where(Audit.doc_id == doc_id)
        result = await db.execute(stmt)
        existing_audit = result.scalar_one_or_none()
        
        findings_dict = [f.model_dump() for f in findings]
        
        if existing_audit:
            # Update existing audit
            existing_audit.findings = findings_dict
            existing_audit.risk_score = risk_score
            existing_audit.audit_date = datetime.utcnow()
            audit_record = existing_audit
            
            logger.info("Updated existing audit", doc_id=str(doc_id))
        else:
            # Create new audit
            audit_record = Audit(
                doc_id=doc_id,
                findings=findings_dict,
                risk_score=risk_score
            )
            db.add(audit_record)
            
            logger.info("Created new audit", doc_id=str(doc_id))
        
        await db.commit()
        await db.refresh(audit_record)
        
        logger.info(
            "Audit stored in database",
            doc_id=str(doc_id),
            audit_id=str(audit_record.id)
        )
        
        # Return AuditOut response
        return AuditOut(
            doc_id=doc_id,
            findings=findings,
            risk_score=risk_score,
            audit_date=audit_record.audit_date
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        logger.error("Audit validation error", doc_id=str(doc_id), error=str(e))
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error("Audit failed", doc_id=str(doc_id), error=str(e))
        raise HTTPException(status_code=500, detail=f"Audit failed: {str(e)}")


@router.get("/audit/{doc_id}", response_model=AuditOut)
async def get_audit(doc_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Retrieve existing audit results for a document.
    
    Args:
        doc_id: UUID of the document
        db: Database session
        
    Returns:
        AuditOut with stored audit results
        
    Raises:
        HTTPException 404: No audit found for this document
    """
    logger.info("Audit retrieval request", doc_id=str(doc_id))
    
    try:
        stmt = select(Audit).where(Audit.doc_id == doc_id)
        result = await db.execute(stmt)
        audit = result.scalar_one_or_none()
        
        if not audit:
            logger.warning("Audit not found", doc_id=str(doc_id))
            raise HTTPException(
                status_code=404,
                detail=f"No audit found for document {doc_id}. Run POST /audit/{doc_id} first."
            )
        
        # Convert findings dict back to Finding objects
        findings = [Finding(**f) for f in audit.findings]
        
        logger.info(
            "Audit retrieved",
            doc_id=str(doc_id),
            findings_count=len(findings)
        )
        
        return AuditOut(
            doc_id=doc_id,
            findings=findings,
            risk_score=audit.risk_score,
            audit_date=audit.audit_date
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Audit retrieval failed", doc_id=str(doc_id), error=str(e))
        raise HTTPException(status_code=500, detail=f"Audit retrieval failed: {str(e)}")
