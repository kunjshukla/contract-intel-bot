"""
Structured field extraction endpoint using LLM and regex fallbacks.
"""

import uuid
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import logger
from src.db.engine import get_db
from src.db.models import Extraction
from src.models.extraction import ExtractionOut, ExtractionFields
from src.routers.health import increment_metric
from src.services.extract import get_full_document_text, llm_extract, apply_regex_fallbacks

router = APIRouter()


@router.post("/extract/{doc_id}", response_model=ExtractionOut, status_code=200)
async def extract_fields(doc_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Extract structured fields from a contract document using LLM.
    
    Process:
    1. Retrieve full document text from chunks
    2. Call Claude-3.5-Sonnet via OpenRouter for field extraction
    3. Parse and validate JSON response
    4. Apply regex fallbacks if needed
    5. Store extraction in database
    
    Args:
        doc_id: UUID of the document to extract from
        db: Database session
        
    Returns:
        ExtractionOut with structured fields
        
    Raises:
        HTTPException 404: Document not found
        HTTPException 422: Document has no text content
        HTTPException 500: Extraction failed
    """
    logger.info("Extraction request received", doc_id=str(doc_id))
    
    try:
        # Step 1: Get full document text
        try:
            full_text = await get_full_document_text(doc_id, db)
        except ValueError as e:
            logger.error("Failed to retrieve document text", doc_id=str(doc_id), error=str(e))
            if "not found" in str(e):
                raise HTTPException(status_code=404, detail=str(e))
            else:
                raise HTTPException(status_code=422, detail=str(e))
        
        logger.info(
            "Retrieved document text for extraction",
            doc_id=str(doc_id),
            text_length=len(full_text),
            word_count=len(full_text.split())
        )
        
        # Step 2: Extract fields using LLM
        try:
            extracted_fields = await llm_extract(full_text, retry_on_failure=True)
        except Exception as e:
            logger.error(
                "LLM extraction failed",
                doc_id=str(doc_id),
                error=str(e)
            )
            raise HTTPException(
                status_code=500,
                detail=f"Field extraction failed: {str(e)}"
            )
        
        # Step 3: Apply regex fallbacks for missing fields
        extracted_fields = apply_regex_fallbacks(full_text, extracted_fields)
        
        # Step 4: Store extraction in database
        extraction = Extraction(
            id=uuid.uuid4(),
            doc_id=doc_id,
            fields=extracted_fields,
            extracted_at=datetime.utcnow(),
            extraction_method="llm"
        )
        
        db.add(extraction)
        await db.commit()
        await db.refresh(extraction)
        
        logger.info(
            "Extraction completed and stored",
            doc_id=str(doc_id),
            extraction_id=str(extraction.id),
            num_parties=len(extracted_fields.get("parties", [])),
            has_effective_date=extracted_fields.get("effective_date") is not None
        )
        
        # Increment metrics
        increment_metric("extractions_total")
        
        # Return formatted response
        return ExtractionOut(
            id=extraction.id,
            doc_id=extraction.doc_id,
            fields=ExtractionFields(**extraction.fields),
            extracted_at=extraction.extracted_at,
            extraction_method=extraction.extraction_method
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Unexpected error during extraction",
            doc_id=str(doc_id),
            error=str(e),
            error_type=type(e).__name__
        )
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during extraction: {str(e)}"
        )


@router.get("/extract/{doc_id}", response_model=ExtractionOut)
async def get_extraction(doc_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Retrieve existing extraction for a document.
    
    Args:
        doc_id: UUID of the document
        db: Database session
        
    Returns:
        ExtractionOut with previously extracted fields
        
    Raises:
        HTTPException 404: No extraction found for document
    """
    result = await db.execute(
        select(Extraction)
        .where(Extraction.doc_id == doc_id)
        .order_by(Extraction.extracted_at.desc())
    )
    extraction = result.scalar_one_or_none()
    
    if not extraction:
        raise HTTPException(
            status_code=404,
            detail=f"No extraction found for document {doc_id}"
        )
    
    return ExtractionOut(
        id=extraction.id,
        doc_id=extraction.doc_id,
        fields=ExtractionFields(**extraction.fields),
        extracted_at=extraction.extracted_at,
        extraction_method=extraction.extraction_method
    )

