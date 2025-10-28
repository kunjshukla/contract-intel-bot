"""
PDF ingestion service with PyMuPDF extraction.
"""

import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import fitz  # PyMuPDF
from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import logger
from src.db.models import Document


# Constants
MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_MIME_TYPES = ["application/pdf"]
ALLOWED_EXTENSIONS = [".pdf"]


async def validate_pdf_file(file: UploadFile) -> None:
    """
    Validate uploaded file is a PDF and within size limits.
    
    Args:
        file: Uploaded file from FastAPI
        
    Raises:
        HTTPException: If validation fails
    """
    # Check file extension
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    
    file_path = Path(file.filename)
    if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Only PDF files are allowed. Got: {file_path.suffix}",
        )
    
    # Check MIME type if provided
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid MIME type. Expected application/pdf, got: {file.content_type}",
        )


async def extract_pdf_content(file_bytes: bytes, filename: str) -> Dict:
    """
    Extract text and metadata from PDF using PyMuPDF.
    
    Args:
        file_bytes: Raw PDF file bytes
        filename: Original filename for logging
        
    Returns:
        Dict with extracted data: {
            'page_count': int,
            'file_size': int,
            'pages': List[Dict],  # [{'page_num': 1, 'text': '...', 'char_count': 123}]
            'metadata': Dict  # PDF metadata (author, title, etc.)
        }
        
    Raises:
        HTTPException: If PDF is corrupted or empty
    """
    try:
        # Open PDF from bytes
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        
        # Check if PDF is empty
        if doc.page_count == 0:
            raise HTTPException(
                status_code=400,
                detail=f"PDF '{filename}' is empty (0 pages)",
            )
        
        # Extract text from each page
        pages_data = []
        total_chars = 0
        
        for page_num in range(doc.page_count):
            page = doc[page_num]
            text = page.get_text()
            char_count = len(text)
            total_chars += char_count
            
            pages_data.append({
                "page_num": page_num + 1,  # 1-indexed
                "text": text,
                "char_count": char_count,
            })
        
        # Extract PDF metadata
        pdf_metadata = doc.metadata or {}
        
        # Close document
        doc.close()
        
        # Check if PDF has any extractable text
        if total_chars == 0:
            logger.warning(
                "PDF has no extractable text",
                filename=filename,
                pages=doc.page_count,
            )
        
        return {
            "page_count": len(pages_data),
            "file_size": len(file_bytes),
            "pages": pages_data,
            "metadata": {
                "pdf_author": pdf_metadata.get("author"),
                "pdf_title": pdf_metadata.get("title"),
                "pdf_subject": pdf_metadata.get("subject"),
                "pdf_creator": pdf_metadata.get("creator"),
                "total_chars": total_chars,
            },
        }
        
    except fitz.FileDataError as e:
        logger.error("Corrupted PDF file", filename=filename, error=str(e))
        raise HTTPException(
            status_code=400,
            detail=f"Corrupted or invalid PDF file: {filename}",
        )
    except Exception as e:
        logger.error("PDF extraction failed", filename=filename, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process PDF: {str(e)}",
        )


async def ingest_pdf(
    file: UploadFile,
    db: AsyncSession,
) -> uuid.UUID:
    """
    Ingest a single PDF file: validate, extract, and store in database.
    
    Args:
        file: Uploaded PDF file
        db: Database session
        
    Returns:
        UUID of created Document record
        
    Raises:
        HTTPException: If validation or processing fails
    """
    # Validate file
    await validate_pdf_file(file)
    
    # Read file content
    file_bytes = await file.read()
    file_size = len(file_bytes)
    
    # Check file size
    if file_size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds {MAX_FILE_SIZE_MB}MB limit. Got: {file_size / 1024 / 1024:.2f}MB",
        )
    
    if file_size == 0:
        raise HTTPException(
            status_code=400,
            detail=f"File '{file.filename}' is empty (0 bytes)",
        )
    
    logger.info(
        "Processing PDF upload",
        filename=file.filename,
        size_mb=f"{file_size / 1024 / 1024:.2f}",
    )
    
    # Extract PDF content
    extracted = await extract_pdf_content(file_bytes, file.filename)
    
    # Create Document record
    document = Document(
        id=uuid.uuid4(),
        filename=file.filename,
        upload_date=datetime.utcnow(),
        file_size=extracted["file_size"],
        num_pages=extracted["page_count"],
        metadata={
            "pages": extracted["pages"],
            **extracted["metadata"],
        },
    )
    
    # Save to database
    db.add(document)
    await db.commit()
    await db.refresh(document)
    
    logger.info(
        "PDF ingested successfully",
        doc_id=str(document.id),
        filename=file.filename,
        pages=document.num_pages,
        size_kb=file_size // 1024,
    )
    
    return document.id


async def ingest_pdf_background(
    file_bytes: bytes,
    filename: str,
    db: AsyncSession,
) -> uuid.UUID:
    """
    Background task for ingesting large PDFs (>5 pages).
    
    Args:
        file_bytes: Raw PDF bytes
        filename: Original filename
        db: Database session
        
    Returns:
        UUID of created Document
    """
    logger.info("Starting background PDF ingestion", filename=filename)
    
    # Extract content
    extracted = await extract_pdf_content(file_bytes, filename)
    
    # Create Document
    document = Document(
        id=uuid.uuid4(),
        filename=filename,
        upload_date=datetime.utcnow(),
        file_size=extracted["file_size"],
        num_pages=extracted["page_count"],
        metadata={
            "pages": extracted["pages"],
            **extracted["metadata"],
            "processed_in_background": True,
        },
    )
    
    db.add(document)
    await db.commit()
    await db.refresh(document)
    
    logger.info(
        "Background PDF ingestion completed",
        doc_id=str(document.id),
        filename=filename,
    )
    
    return document.id
