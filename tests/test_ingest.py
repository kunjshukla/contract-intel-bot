"""
Tests for PDF ingestion endpoint.
"""

import io
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.db.models import Document


@pytest.mark.asyncio
async def test_ingest_single_pdf_success(client: AsyncClient, db):
    """Test successful ingestion of a single PDF."""
    # Create a minimal valid PDF
    pdf_content = b"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj
2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj
3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
/Resources <<
/Font <<
/F1 <<
/Type /Font
/Subtype /Type1
/BaseFont /Helvetica
>>
>>
>>
>>
endobj
4 0 obj
<<
/Length 44
>>
stream
BT
/F1 12 Tf
100 700 Td
(Test PDF) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000317 00000 n 
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
409
%%EOF
"""
    
    # Create file upload
    files = {"files": ("test_contract.pdf", io.BytesIO(pdf_content), "application/pdf")}
    
    response = await client.post("/api/v1/ingest", files=files)
    
    assert response.status_code == 201
    data = response.json()
    
    assert data["status"] == "ingested"
    assert data["count"] == 1
    assert len(data["document_ids"]) == 1
    assert UUID(data["document_ids"][0])  # Valid UUID
    
    # Verify database record
    result = await db.execute(
        select(Document).where(Document.id == UUID(data["document_ids"][0]))
    )
    document = result.scalar_one_or_none()
    
    assert document is not None
    assert document.filename == "test_contract.pdf"
    assert document.num_pages == 1
    assert document.file_size > 0
    assert "pages" in document.metadata


@pytest.mark.asyncio
async def test_ingest_multiple_pdfs(client: AsyncClient, db):
    """Test ingestion of multiple PDFs in one request."""
    pdf_content = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000052 00000 n 
0000000101 00000 n 
trailer<</Size 4/Root 1 0 R>>
startxref
160
%%EOF
"""
    
    files = [
        ("files", ("nda.pdf", io.BytesIO(pdf_content), "application/pdf")),
        ("files", ("msa.pdf", io.BytesIO(pdf_content), "application/pdf")),
    ]
    
    response = await client.post("/api/v1/ingest", files=files)
    
    assert response.status_code == 201
    data = response.json()
    
    assert data["count"] == 2
    assert len(data["document_ids"]) == 2
    
    # Verify both documents exist in DB
    for doc_id in data["document_ids"]:
        result = await db.execute(select(Document).where(Document.id == UUID(doc_id)))
        document = result.scalar_one_or_none()
        assert document is not None


@pytest.mark.asyncio
async def test_ingest_invalid_file_extension(client: AsyncClient):
    """Test rejection of non-PDF files."""
    txt_content = b"This is not a PDF"
    files = {"files": ("document.txt", io.BytesIO(txt_content), "text/plain")}
    
    response = await client.post("/api/v1/ingest", files=files)
    
    assert response.status_code == 400
    assert "Only PDF files are allowed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_invalid_mime_type(client: AsyncClient):
    """Test rejection of files with wrong MIME type."""
    files = {"files": ("fake.pdf", io.BytesIO(b"not a pdf"), "text/plain")}
    
    response = await client.post("/api/v1/ingest", files=files)
    
    assert response.status_code == 400
    assert "Invalid MIME type" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_empty_file(client: AsyncClient):
    """Test rejection of empty files."""
    files = {"files": ("empty.pdf", io.BytesIO(b""), "application/pdf")}
    
    response = await client.post("/api/v1/ingest", files=files)
    
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_ingest_corrupted_pdf(client: AsyncClient):
    """Test handling of corrupted PDF files."""
    corrupted = b"%PDF-1.4\nThis is not valid PDF content"
    files = {"files": ("corrupted.pdf", io.BytesIO(corrupted), "application/pdf")}
    
    response = await client.post("/api/v1/ingest", files=files)
    
    assert response.status_code == 400
    assert "Corrupted" in response.json()["detail"] or "invalid" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_ingest_too_many_files(client: AsyncClient):
    """Test rejection when too many files uploaded."""
    pdf_content = b"%PDF-1.4\n%%EOF"
    
    # Create 11 files (max is 10)
    files = [
        ("files", (f"doc{i}.pdf", io.BytesIO(pdf_content), "application/pdf"))
        for i in range(11)
    ]
    
    response = await client.post("/api/v1/ingest", files=files)
    
    assert response.status_code == 413
    assert "Too many files" in response.json()["detail"]


@pytest.mark.asyncio
async def test_ingest_no_files(client: AsyncClient):
    """Test rejection when no files provided."""
    response = await client.post("/api/v1/ingest", files={})
    
    assert response.status_code == 422  # FastAPI validation error


@pytest.mark.asyncio
async def test_ingest_duplicate_filename(client: AsyncClient, db):
    """Test that duplicate filenames are allowed (use UUID for uniqueness)."""
    pdf_content = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
xref
0 4
trailer<</Size 4/Root 1 0 R>>
%%EOF
"""
    
    # Upload same filename twice
    files1 = {"files": ("contract.pdf", io.BytesIO(pdf_content), "application/pdf")}
    files2 = {"files": ("contract.pdf", io.BytesIO(pdf_content), "application/pdf")}
    
    response1 = await client.post("/api/v1/ingest", files=files1)
    response2 = await client.post("/api/v1/ingest", files=files2)
    
    assert response1.status_code == 201
    assert response2.status_code == 201
    
    # Different UUIDs
    id1 = response1.json()["document_ids"][0]
    id2 = response2.json()["document_ids"][0]
    assert id1 != id2
    
    # Both exist in DB
    result = await db.execute(select(Document))
    documents = result.scalars().all()
    assert len([d for d in documents if d.filename == "contract.pdf"]) == 2


@pytest.mark.asyncio
async def test_ingest_single_endpoint(client: AsyncClient, db):
    """Test the /ingest/single convenience endpoint."""
    pdf_content = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
xref
0 4
trailer<</Size 4/Root 1 0 R>>
%%EOF
"""
    
    files = {"file": ("single.pdf", io.BytesIO(pdf_content), "application/pdf")}
    
    response = await client.post("/api/v1/ingest/single", files=files)
    
    assert response.status_code == 201
    data = response.json()
    
    assert "id" in data
    assert data["filename"] == "single.pdf"
    assert data["num_pages"] >= 0
    assert "upload_date" in data


@pytest.mark.asyncio
async def test_ingest_pdf_with_text_extraction(client: AsyncClient, db):
    """Test that PDF text is properly extracted and stored in metadata."""
    # This uses the first test's PDF which has "Test PDF" text
    pdf_content = b"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj
2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj
3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
/Resources <<
/Font <<
/F1 <<
/Type /Font
/Subtype /Type1
/BaseFont /Helvetica
>>
>>
>>
>>
endobj
4 0 obj
<<
/Length 44
>>
stream
BT
/F1 12 Tf
100 700 Td
(Test PDF) Tj
ET
endstream
endobj
xref
0 5
trailer
<<
/Size 5
/Root 1 0 R
>>
%%EOF
"""
    
    files = {"files": ("text_test.pdf", io.BytesIO(pdf_content), "application/pdf")}
    
    response = await client.post("/api/v1/ingest", files=files)
    assert response.status_code == 201
    
    doc_id = UUID(response.json()["document_ids"][0])
    
    # Check database
    result = await db.execute(select(Document).where(Document.id == doc_id))
    document = result.scalar_one()
    
    assert "pages" in document.metadata
    assert len(document.metadata["pages"]) == 1
    assert "text" in document.metadata["pages"][0]
    assert "page_num" in document.metadata["pages"][0]


@pytest.mark.asyncio
async def test_metrics_incremented_on_ingest(client: AsyncClient):
    """Test that metrics counter is incremented after successful ingestion."""
    # Get initial metrics
    metrics_before = await client.get("/metrics")
    initial_count = metrics_before.json()["ingests_total"]
    
    # Ingest a PDF
    pdf_content = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\nxref\n0 2\ntrailer<</Size 2/Root 1 0 R>>\n%%EOF"
    files = {"files": ("metric_test.pdf", io.BytesIO(pdf_content), "application/pdf")}
    
    await client.post("/api/v1/ingest", files=files)
    
    # Check metrics increased
    metrics_after = await client.get("/metrics")
    final_count = metrics_after.json()["ingests_total"]
    
    assert final_count == initial_count + 1
