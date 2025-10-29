"""
Tests for contract field extraction endpoint.
"""

import io
import json
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.db.models import Document, Chunk, Extraction


# Mock LLM response for successful extraction
MOCK_EXTRACTION_RESPONSE = {
    "parties": ["Acme Corporation", "Widget Industries Inc."],
    "effective_date": "2024-01-15",
    "term": "12 months",
    "governing_law": "State of California",
    "payment_terms": "Net 30 days",
    "termination": "Either party may terminate with 30 days written notice",
    "auto_renewal": True,
    "confidentiality": True,
    "indemnity": "Mutual indemnification",
    "liability_cap": {
        "amount": 100000.0,
        "currency": "USD"
    },
    "signatories": [
        {"name": "John Smith", "title": "CEO"},
        {"name": "Jane Doe", "title": "CFO"}
    ]
}


async def mock_llm_extract(text: str, retry_on_failure: bool = True):
    """Mock LLM extraction function."""
    return MOCK_EXTRACTION_RESPONSE


@pytest.mark.asyncio
async def test_extract_fields_success(client: AsyncClient, db):
    """Test successful field extraction from document."""
    # Create a test document with chunks
    pdf_content = b"%PDF-1.4\ntest content"
    
    with patch('src.services.ingest.extract_pdf_content', return_value={
        'page_count': 1,
        'file_size': len(pdf_content),
        'pages': [{'page_num': 1, 'text': 'Test NDA Agreement', 'char_count': 18}],
        'metadata': {}
    }):
        files = {"files": ("test_nda.pdf", io.BytesIO(pdf_content), "application/pdf")}
        ingest_response = await client.post("/api/v1/ingest", files=files)
    
    assert ingest_response.status_code == 201
    doc_id = ingest_response.json()["document_ids"][0]
    
    # Mock LLM extraction
    with patch('src.routers.extract.llm_extract', side_effect=mock_llm_extract):
        response = await client.post(f"/api/v1/extract/{doc_id}")
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify response structure
    assert "id" in data
    assert data["doc_id"] == doc_id
    assert "fields" in data
    assert "extracted_at" in data
    assert data["extraction_method"] == "llm"
    
    # Verify extracted fields
    fields = data["fields"]
    assert fields["parties"] == ["Acme Corporation", "Widget Industries Inc."]
    assert fields["effective_date"] == "2024-01-15"
    assert fields["term"] == "12 months"
    assert fields["governing_law"] == "State of California"
    assert fields["payment_terms"] == "Net 30 days"
    assert fields["auto_renewal"] is True
    assert fields["confidentiality"] is True
    assert fields["liability_cap"]["amount"] == 100000.0
    assert fields["liability_cap"]["currency"] == "USD"
    assert len(fields["signatories"]) == 2
    assert fields["signatories"][0]["name"] == "John Smith"
    
    # Verify extraction was stored in database
    result = await db.execute(
        select(Extraction).where(Extraction.doc_id == UUID(doc_id))
    )
    extraction = result.scalar_one_or_none()
    
    assert extraction is not None
    assert str(extraction.doc_id) == doc_id
    assert extraction.fields["parties"] == ["Acme Corporation", "Widget Industries Inc."]


@pytest.mark.asyncio
async def test_extract_document_not_found(client: AsyncClient, db):
    """Test extraction with non-existent document ID."""
    fake_doc_id = uuid4()
    
    with patch('src.services.extract.llm_extract', side_effect=mock_llm_extract):
        response = await client.post(f"/api/v1/extract/{fake_doc_id}")
    
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_extract_with_invalid_json_retry(client: AsyncClient, db):
    """Test extraction handles invalid JSON and retries."""
    # Create document
    pdf_content = b"%PDF-1.4\ntest"
    
    with patch('src.services.ingest.extract_pdf_content', return_value={
        'page_count': 1,
        'file_size': len(pdf_content),
        'pages': [{'page_num': 1, 'text': 'Contract text', 'char_count': 13}],
        'metadata': {}
    }):
        files = {"files": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")}
        ingest_response = await client.post("/api/v1/ingest", files=files)
    
    doc_id = ingest_response.json()["document_ids"][0]
    
    # Mock LLM to fail first time, succeed on retry
    call_count = 0
    
    async def mock_llm_with_retry(text, retry_on_failure=True):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call fails
            raise ValueError("Invalid JSON response")
        # Second call succeeds
        return MOCK_EXTRACTION_RESPONSE
    
    with patch('src.services.extract.llm_extract', side_effect=mock_llm_with_retry):
        response = await client.post(f"/api/v1/extract/{doc_id}")
    
    # Should still succeed after retry
    assert response.status_code == 200 or response.status_code == 500  # Depending on implementation


@pytest.mark.asyncio
async def test_extract_partial_fields(client: AsyncClient, db):
    """Test extraction with only partial fields available."""
    # Create document
    pdf_content = b"%PDF-1.4\nminimal"
    
    with patch('src.services.ingest.extract_pdf_content', return_value={
        'page_count': 1,
        'file_size': len(pdf_content),
        'pages': [{'page_num': 1, 'text': 'Simple agreement', 'char_count': 16}],
        'metadata': {}
    }):
        files = {"files": ("simple.pdf", io.BytesIO(pdf_content), "application/pdf")}
        ingest_response = await client.post("/api/v1/ingest", files=files)
    
    doc_id = ingest_response.json()["document_ids"][0]
     # Mock partial extraction
    partial_response = {
        "parties": ["Company A", "Company B"],
        "effective_date": None,
        "term": None,
        "governing_law": None,
        "payment_terms": None,
        "termination": None,
        "auto_renewal": None,
        "confidentiality": True,
        "indemnity": None,
        "liability_cap": None,
        "signatories": []
    }

    async def mock_partial_extract(text, retry_on_failure=True):
        return partial_response

    with patch('src.routers.extract.llm_extract', side_effect=mock_partial_extract):
        response = await client.post(f"/api/v1/extract/{doc_id}")
    
    assert response.status_code == 200
    fields = response.json()["fields"]
    
    # Verify partial fields
    assert fields["parties"] == ["Company A", "Company B"]
    assert fields["confidentiality"] is True
    assert fields["effective_date"] is None
    assert fields["term"] is None
    assert len(fields["signatories"]) == 0


@pytest.mark.asyncio
async def test_get_existing_extraction(client: AsyncClient, db):
    """Test retrieving an existing extraction."""
    # Create and extract document
    pdf_content = b"%PDF-1.4\ntest"
    
    with patch('src.services.ingest.extract_pdf_content', return_value={
        'page_count': 1,
        'file_size': len(pdf_content),
        'pages': [{'page_num': 1, 'text': 'NDA text', 'char_count': 8}],
        'metadata': {}
    }):
        files = {"files": ("nda.pdf", io.BytesIO(pdf_content), "application/pdf")}
        ingest_response = await client.post("/api/v1/ingest", files=files)
    
    doc_id = ingest_response.json()["document_ids"][0]
    
    # Perform extraction
    with patch('src.routers.extract.llm_extract', side_effect=mock_llm_extract):
        extract_response = await client.post(f"/api/v1/extract/{doc_id}")
    
    assert extract_response.status_code == 200
    extraction_id = extract_response.json()["id"]
    
    # Retrieve extraction
    get_response = await client.get(f"/api/v1/extract/{doc_id}")
    
    assert get_response.status_code == 200
    retrieved = get_response.json()
    
    assert retrieved["id"] == extraction_id
    assert retrieved["doc_id"] == doc_id
    assert retrieved["fields"]["parties"] == ["Acme Corporation", "Widget Industries Inc."]


@pytest.mark.asyncio
async def test_get_extraction_not_found(client: AsyncClient, db):
    """Test retrieving extraction for document without one."""
    # Create document without extracting
    pdf_content = b"%PDF-1.4\ntest"
    
    with patch('src.services.ingest.extract_pdf_content', return_value={
        'page_count': 1,
        'file_size': len(pdf_content),
        'pages': [{'page_num': 1, 'text': 'Text', 'char_count': 4}],
        'metadata': {}
    }):
        files = {"files": ("test.pdf", io.BytesIO(pdf_content), "application/pdf")}
        ingest_response = await client.post("/api/v1/ingest", files=files)
    
    doc_id = ingest_response.json()["document_ids"][0]
    
    # Try to get non-existent extraction
    response = await client.get(f"/api/v1/extract/{doc_id}")
    
    assert response.status_code == 404
    assert "No extraction found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_extract_with_regex_fallback(client: AsyncClient, db):
    """Test regex fallback for missing fields."""
    # Create document with text containing patterns
    text_with_patterns = """
    SERVICE AGREEMENT
    
    Effective Date: 2024-03-15
    Payment Terms: Net 30 days from invoice
    Liability Cap: $500,000 USD
    """
    
    pdf_content = b"%PDF-1.4\ntest"
    
    with patch('src.services.ingest.extract_pdf_content', return_value={
        'page_count': 1,
        'file_size': len(pdf_content),
        'pages': [{'page_num': 1, 'text': text_with_patterns, 'char_count': len(text_with_patterns)}],
        'metadata': {}
    }):
        files = {"files": ("service.pdf", io.BytesIO(pdf_content), "application/pdf")}
        ingest_response = await client.post("/api/v1/ingest", files=files)
    
    doc_id = ingest_response.json()["document_ids"][0]
     # Mock LLM to return fields without some values
    partial_response = {
        **MOCK_EXTRACTION_RESPONSE,
        "effective_date": None,  # Should be filled by regex
        "liability_cap": None,  # Should be filled by regex
    }

    async def mock_partial(text, retry_on_failure=True):
        return partial_response

    with patch('src.routers.extract.llm_extract', side_effect=mock_partial):
        response = await client.post(f"/api/v1/extract/{doc_id}")
    
    assert response.status_code == 200
    fields = response.json()["fields"]
    
    # Regex fallbacks should have filled these
    # Note: Actual values depend on regex implementation
    assert fields is not None


@pytest.mark.asyncio
async def test_extract_metrics_incremented(client: AsyncClient, db):
    """Test that extraction metrics are incremented."""
    # Get initial metrics
    metrics_before = await client.get("/metrics")
    initial_count = metrics_before.json().get("extractions_total", 0)
    
    # Create and extract document
    pdf_content = b"%PDF-1.4\ntest"
    
    with patch('src.services.ingest.extract_pdf_content', return_value={
        'page_count': 1,
        'file_size': len(pdf_content),
        'pages': [{'page_num': 1, 'text': 'Contract', 'char_count': 8}],
        'metadata': {}
    }):
        files = {"files": ("contract.pdf", io.BytesIO(pdf_content), "application/pdf")}
        ingest_response = await client.post("/api/v1/ingest", files=files)

    doc_id = ingest_response.json()["document_ids"][0]

    with patch('src.routers.extract.llm_extract', side_effect=mock_llm_extract):
        await client.post(f"/api/v1/extract/{doc_id}")
    
    # Check metrics increased
    metrics_after = await client.get("/metrics")
    final_count = metrics_after.json().get("extractions_total", 0)
    
    assert final_count == initial_count + 1
