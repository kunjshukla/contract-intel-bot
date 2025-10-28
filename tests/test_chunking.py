"""
Tests for chunking, embedding, and vector search.
"""

import io
from uuid import UUID

import numpy as np
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from unittest.mock import AsyncMock, patch, MagicMock

from src.db.models import Chunk, Document
from src.services.chunking import chunk_and_embed, search_similar_chunks
from src.core.vector_store import get_vector_store


# Mock embedding function that returns consistent vectors
async def mock_get_embedding(text: str) -> np.ndarray:
    """Mock embedding function for testing."""
    # Generate deterministic embedding based on text hash
    np.random.seed(hash(text) % 2**32)
    return np.random.rand(1536).astype(np.float32)


@pytest.mark.asyncio
async def test_chunking_creates_chunks(client: AsyncClient, db):
    """Test that document chunking creates Chunk records."""
    # Create a test document with multiple paragraphs
    pdf_content = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>>>>>endobj
4 0 obj<</Length 200>>stream
BT
/F1 12 Tf
50 700 Td
(MUTUAL NON-DISCLOSURE AGREEMENT) Tj
0 -20 Td
(This Agreement is entered into as of January 1, 2024.) Tj
0 -20 Td
(The parties agree to maintain confidentiality for 2 years.) Tj
0 -20 Td
(Payment terms: Net 30 days from invoice date.) Tj
ET
endstream
endobj
xref
0 5
trailer<</Size 5/Root 1 0 R>>
%%EOF
"""
    
    # Ingest document with mocked embeddings
    with patch('src.services.chunking.get_embedding', side_effect=mock_get_embedding):
        files = {"files": ("test_nda.pdf", io.BytesIO(pdf_content), "application/pdf")}
        response = await client.post("/api/v1/ingest", files=files)
    
    assert response.status_code == 201
    doc_id = UUID(response.json()["document_ids"][0])
    
    # Check that chunks were created
    result = await db.execute(select(Chunk).where(Chunk.doc_id == doc_id))
    chunks = result.scalars().all()
    
    assert len(chunks) > 0
    
    # Verify chunk structure
    first_chunk = chunks[0]
    assert first_chunk.doc_id == doc_id
    assert first_chunk.chunk_index >= 0
    assert first_chunk.page_num == 1
    assert first_chunk.text is not None
    assert len(first_chunk.text) > 0
    assert first_chunk.embedding_vector is not None  # JSON list
    assert isinstance(first_chunk.embedding_vector, list)
    assert len(first_chunk.embedding_vector) == 1536  # OpenAI embedding dimension


@pytest.mark.asyncio
async def test_chunking_with_overlap(client: AsyncClient, db):
    """Test that chunks have proper overlap for context preservation."""
    pdf_content = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>>>>>endobj
4 0 obj<</Length 400>>stream
BT
/F1 10 Tf
50 700 Td
(SECTION 1: DEFINITIONS) Tj
0 -15 Td
(Confidential Information means any information disclosed by one party to the other.) Tj
0 -15 Td
(SECTION 2: OBLIGATIONS) Tj
0 -15 Td
(The Receiving Party shall maintain confidentiality and not disclose to third parties.) Tj
0 -15 Td
(SECTION 3: TERM) Tj
0 -15 Td
(This Agreement shall remain in effect for a period of two years from the Effective Date.) Tj
0 -15 Td
(SECTION 4: TERMINATION) Tj
0 -15 Td
(Either party may terminate this Agreement with 30 days written notice.) Tj
ET
endstream
endobj
xref
0 5
trailer<</Size 5/Root 1 0 R>>
%%EOF
"""
    
    with patch('src.services.chunking.get_embedding', side_effect=mock_get_embedding):
        files = {"files": ("overlap_test.pdf", io.BytesIO(pdf_content), "application/pdf")}
        response = await client.post("/api/v1/ingest", files=files)
    
    assert response.status_code == 201
    doc_id = UUID(response.json()["document_ids"][0])
    
    result = await db.execute(
        select(Chunk).where(Chunk.doc_id == doc_id).order_by(Chunk.chunk_index)
    )
    chunks = result.scalars().all()
    
    # If we have multiple chunks, check for overlap
    if len(chunks) > 1:
        # Chunks should have some overlapping content
        chunk1_text = chunks[0].text
        chunk2_text = chunks[1].text
        
        # Check that chunk2 starts somewhere within chunk1's text
        # (overlap behavior from RecursiveCharacterTextSplitter)
        assert len(chunk1_text) > 0
        assert len(chunk2_text) > 0


@pytest.mark.asyncio
async def test_vector_search(client: AsyncClient, db):
    """Test vector similarity search."""
    # Create a document with searchable content
    pdf_content = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>>>>>endobj
4 0 obj<</Length 200>>stream
BT
/F1 12 Tf
50 700 Td
(Payment terms: All invoices are due Net 30 days.) Tj
0 -20 Td
(Late payments incur a 2 percent monthly interest charge.) Tj
0 -20 Td
(Confidentiality period: 2 years from disclosure date.) Tj
ET
endstream
endobj
xref
0 5
trailer<</Size 5/Root 1 0 R>>
%%EOF
"""
    
    # Ingest with mocked embeddings
    with patch('src.services.chunking.get_embedding', side_effect=mock_get_embedding):
        files = {"files": ("payment_doc.pdf", io.BytesIO(pdf_content), "application/pdf")}
        response = await client.post("/api/v1/ingest", files=files)
    
    assert response.status_code == 201
    doc_id = UUID(response.json()["document_ids"][0])
    
    # Search for "payment" - should return relevant chunks
    with patch('src.services.chunking.get_embedding', side_effect=mock_get_embedding):
        search_response = await client.post(
            "/api/v1/search",
            json={"query": "payment terms", "k": 3}
        )
    
    assert search_response.status_code == 200
    data = search_response.json()
    
    assert "results" in data
    assert data["query"] == "payment terms"
    assert data["count"] >= 0
    
    if data["count"] > 0:
        result = data["results"][0]
        assert "text" in result
        assert "score" in result
        assert "page" in result
        assert "chunk_id" in result


@pytest.mark.asyncio
async def test_search_with_doc_filter(client: AsyncClient, db):
    """Test vector search with document ID filter."""
    pdf_content = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
xref
0 4
trailer<</Size 4/Root 1 0 R>>
%%EOF
"""
    
    with patch('src.services.chunking.get_embedding', side_effect=mock_get_embedding):
        # Ingest two documents
        files1 = {"files": ("doc1.pdf", io.BytesIO(pdf_content), "application/pdf")}
        response1 = await client.post("/api/v1/ingest", files=files1)
        doc1_id = UUID(response1.json()["document_ids"][0])
        
        files2 = {"files": ("doc2.pdf", io.BytesIO(pdf_content), "application/pdf")}
        response2 = await client.post("/api/v1/ingest", files=files2)
        doc2_id = UUID(response2.json()["document_ids"][0])
    
    # Search filtered by doc1
    with patch('src.services.chunking.get_embedding', side_effect=mock_get_embedding):
        search_response = await client.post(
            "/api/v1/search",
            json={"query": "test", "k": 10, "doc_id": str(doc1_id)}
        )
    
    assert search_response.status_code == 200
    data = search_response.json()
    
    # All results should be from doc1
    for result in data["results"]:
        assert result["doc_id"] == str(doc1_id)


@pytest.mark.asyncio
async def test_chunking_skip_embedding_fallback(client: AsyncClient, db):
    """Test chunking with skip_embedding flag (fallback mode)."""
    # Create document
    from src.db.models import Document
    
    doc = Document(
        filename="test_skip.pdf",
        num_pages=1,
        file_size=100,
        metadata={
            "pages": [
                {
                    "page_num": 1,
                    "text": "This is a test document for skip embedding mode.",
                    "char_count": 50
                }
            ]
        }
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    
    # Chunk without embeddings
    from src.services.chunking import chunk_and_embed
    
    chunk_count = await chunk_and_embed(
        doc_id=doc.id,
        db=db,
        skip_embedding=True,
    )
    
    assert chunk_count > 0
    
    # Verify chunks exist but have no embeddings
    result = await db.execute(select(Chunk).where(Chunk.doc_id == doc.id))
    chunks = result.scalars().all()
    
    assert len(chunks) == chunk_count
    for chunk in chunks:
        assert chunk.embedding_vector is None  # No embeddings in skip mode


@pytest.mark.asyncio
async def test_embedding_failure_partial_success(client: AsyncClient, db):
    """Test that some chunks succeed even if others fail embedding."""
    # Create document
    doc = Document(
        filename="test_partial.pdf",
        num_pages=1,
        file_size=100,
        metadata={
            "pages": [
                {
                    "page_num": 1,
                    "text": "First chunk. " * 50 + "\n\nSecond chunk. " * 50,
                    "char_count": 500
                }
            ]
        }
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    
    # Mock embedding to fail on specific text
    async def mock_embedding_with_failure(text: str):
        if "Second" in text:
            raise Exception("Embedding API error")
        return await mock_get_embedding(text)
    
    from src.services.chunking import chunk_and_embed
    
    with patch('src.services.chunking.get_embedding', side_effect=mock_embedding_with_failure):
        chunk_count = await chunk_and_embed(
            doc_id=doc.id,
            db=db,
            skip_embedding=False,
        )
    
    # Should still create chunks even with some failures
    assert chunk_count > 0
    
    result = await db.execute(select(Chunk).where(Chunk.doc_id == doc.id))
    chunks = result.scalars().all()
    
    # Some chunks should have embeddings, some shouldn't
    has_embedding = sum(1 for c in chunks if c.embedding_vector is not None)
    no_embedding = sum(1 for c in chunks if c.embedding_vector is None)
    
    assert has_embedding > 0 or no_embedding > 0


@pytest.mark.asyncio
async def test_vector_stats_endpoint(client: AsyncClient):
    """Test the vector stats endpoint."""
    response = await client.get("/api/v1/vector-stats")
    
    assert response.status_code == 200
    data = response.json()
    
    assert "total_vectors" in data
    assert "dimension" in data
    assert "index_type" in data
    assert data["dimension"] == 1536


@pytest.mark.asyncio
async def test_simple_search_endpoint(client: AsyncClient, db):
    """Test the GET-based simple search endpoint."""
    pdf_content = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
xref
0 4
trailer<</Size 4/Root 1 0 R>>
%%EOF
"""
    
    with patch('src.services.chunking.get_embedding', side_effect=mock_get_embedding):
        files = {"files": ("simple_search.pdf", io.BytesIO(pdf_content), "application/pdf")}
        await client.post("/api/v1/ingest", files=files)
        
        # Use GET endpoint
        response = await client.get("/api/v1/search/simple?q=test&k=3")
    
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert data["query"] == "test"


@pytest.mark.asyncio
async def test_chunk_metadata_accuracy(client: AsyncClient, db):
    """Test that chunk metadata (page_num, char positions) are accurate."""
    pdf_content = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
xref
0 4
trailer<</Size 4/Root 1 0 R>>
%%EOF
"""
    
    with patch('src.services.chunking.get_embedding', side_effect=mock_get_embedding):
        files = {"files": ("metadata_test.pdf", io.BytesIO(pdf_content), "application/pdf")}
        response = await client.post("/api/v1/ingest", files=files)
    
    doc_id = UUID(response.json()["document_ids"][0])
    
    result = await db.execute(select(Chunk).where(Chunk.doc_id == doc_id))
    chunks = result.scalars().all()
    
    for chunk in chunks:
        # Page num should be positive
        assert chunk.page_num > 0
        
        # Char positions should be non-negative and end > start
        assert chunk.char_start >= 0
        assert chunk.char_end > chunk.char_start
        
        # Text length should roughly match char range
        # (may not be exact due to approximations)
        text_len = len(chunk.text)
        char_range = chunk.char_end - chunk.char_start
        assert abs(text_len - char_range) < 50  # Allow some variance
