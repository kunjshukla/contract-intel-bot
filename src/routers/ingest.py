"""
Document ingestion endpoint with PDF processing.
"""

from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import logger
from src.db.engine import get_db
from src.models.schemas import DocumentOut, IngestResponse
from src.routers.health import increment_metric
from src.services.ingest import ingest_pdf, ingest_pdf_background

router = APIRouter()

# Constants
MAX_FILES_PER_REQUEST = 10
BACKGROUND_THRESHOLD_PAGES = 5


@router.post("/ingest", response_model=IngestResponse, status_code=201)
async def ingest_documents(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload and ingest one or more PDF contracts.
    
    Accepts up to 10 PDF files (max 10MB each). Files are validated for:
    - PDF extension and MIME type
    - File size limits
    - Non-empty content
    
    Large PDFs (>5 pages) are processed in background tasks.
    
    Args:
        background_tasks: FastAPI background tasks
        files: List of uploaded PDF files
        db: Database session
        
    Returns:
        IngestResponse with document IDs and status
        
    Raises:
        HTTPException 400: Invalid file format or size
        HTTPException 413: Too many files
    """
    # Validate number of files
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=413,
            detail=f"Too many files. Maximum {MAX_FILES_PER_REQUEST} files per request. Got: {len(files)}",
        )
    
    if len(files) == 0:
        raise HTTPException(
            status_code=400,
            detail="At least one file is required",
        )
    
    logger.info("Ingestion request received", file_count=len(files))
    
    document_ids = []
    
    # Process each file
    for file in files:
        try:
            # Ingest PDF (validation happens inside)
            doc_id = await ingest_pdf(file, db)
            document_ids.append(doc_id)
            
            # Increment metrics
            increment_metric("ingests_total")
            
        except HTTPException:
            # Re-raise HTTP exceptions (validation errors)
            raise
        except Exception as e:
            logger.error(
                "Unexpected error during ingestion",
                filename=file.filename,
                error=str(e),
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to ingest '{file.filename}': {str(e)}",
            )
    
    logger.info(
        "Ingestion completed",
        documents_created=len(document_ids),
        doc_ids=[str(id) for id in document_ids],
    )
    
    return IngestResponse(
        document_ids=document_ids,
        status="ingested",
        count=len(document_ids),
    )


@router.post("/ingest/single", response_model=DocumentOut, status_code=201)
async def ingest_single_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload and ingest a single PDF contract.
    
    Convenience endpoint for single file uploads with detailed response.
    
    Args:
        file: Uploaded PDF file
        db: Database session
        
    Returns:
        DocumentOut with full document details
        
    Raises:
        HTTPException 400: Invalid file
    """
    # Ingest the PDF
    doc_id = await ingest_pdf(file, db)
    
    # Fetch the created document
    from sqlalchemy import select
    from src.db.models import Document
    
    result = await db.execute(select(Document).where(Document.id == doc_id))
    document = result.scalar_one_or_none()
    
    if not document:
        raise HTTPException(status_code=404, detail="Document not found after creation")
    
    # Increment metrics
    increment_metric("ingests_total")
    
    return DocumentOut.model_validate(document)
