"""
Tests for RAG Q&A endpoint with citations.
"""

import io
from unittest.mock import patch, AsyncMock
from uuid import UUID

import pytest
from httpx import AsyncClient


# Mock LLM responses
MOCK_RERANK_SCORE = "0.95"

MOCK_ANSWER = """The contract term is 12 months [550e8400-e29b-41d4-a716-446655440000:1:150-170]. 
The payment terms require Net 30 days from invoice [550e8400-e29b-41d4-a716-446655440000:1:200-235]."""

MOCK_NO_ANSWER = "I cannot answer this question based on the provided documents."


async def mock_embedding(text: str):
    """Mock embedding generation."""
    # Return a dummy embedding vector
    return [0.1] * 1536


async def mock_rerank_response(*args, **kwargs):
    """Mock LLM rerank response."""
    class MockMessage:
        content = MOCK_RERANK_SCORE
    
    class MockChoice:
        message = MockMessage()
    
    class MockResponse:
        choices = [MockChoice()]
    
    return MockResponse()


async def mock_answer_response(*args, **kwargs):
    """Mock LLM answer generation response."""
    class MockMessage:
        content = MOCK_ANSWER
    
    class MockChoice:
        message = MockMessage()
    
    class MockResponse:
        choices = [MockChoice()]
    
    return MockResponse()


async def mock_no_answer_response(*args, **kwargs):
    """Mock LLM response when no relevant docs."""
    class MockMessage:
        content = MOCK_NO_ANSWER
    
    class MockChoice:
        message = MockMessage()
    
    class MockResponse:
        choices = [MockChoice()]
    
    return MockResponse()


@pytest.mark.asyncio
async def test_ask_with_answer_and_citations(client: AsyncClient, db):
    """Test successful Q&A with citations."""
    from uuid import uuid4
    from src.models.schemas import Citation
    
    # Mock the entire RAG query to return a complete response
    mock_doc_id = uuid4()
    mock_citations = [
        Citation(
            doc_id=mock_doc_id,
            page=1,
            start_char=150,
            end_char=170,
            text="term of 12 months"
        ),
        Citation(
            doc_id=mock_doc_id,
            page=1,
            start_char=200,
            end_char=235,
            text="Net 30 days from invoice"
        )
    ]
    
    async def mock_rag_query(question, db, doc_ids=None, top_k=3):
        return (MOCK_ANSWER, mock_citations, 0.95)
    
    with patch('src.routers.ask.rag_query', side_effect=mock_rag_query):
        response = await client.post(
            "/api/v1/ask",
            json={"question": "What is the contract term?"}
        )
    
    assert response.status_code == 200
    data = response.json()
    
    assert "answer" in data
    assert "citations" in data
    assert "confidence" in data
    
    # Check answer contains expected content
    assert "12 months" in data["answer"]
    
    # Check confidence
    assert data["confidence"] == 0.95
    
    # Check citations are present
    assert len(data["citations"]) == 2
    citation = data["citations"][0]
    assert "doc_id" in citation
    assert "page" in citation
    assert citation["page"] == 1
    assert "start_char" in citation
    assert "end_char" in citation
    assert "text" in citation


@pytest.mark.asyncio
async def test_ask_with_doc_filter(client: AsyncClient, db):
    """Test Q&A with document ID filtering."""
    from uuid import uuid4
    from src.models.schemas import Citation
    
    mock_doc_id = uuid4()
    mock_citations = [Citation(
        doc_id=mock_doc_id,
        page=1,
        start_char=0,
        end_char=20,
        text="Document 1 content"
    )]
    
    async def mock_rag_query(question, db, doc_ids=None, top_k=3):
        # Verify doc_ids were passed
        assert doc_ids is not None
        assert len(doc_ids) == 1
        return (MOCK_ANSWER, mock_citations, 0.85)
    
    with patch('src.routers.ask.rag_query', side_effect=mock_rag_query):
        response = await client.post(
            "/api/v1/ask",
            json={
                "question": "What is in this document?",
                "doc_ids": [str(mock_doc_id)]
            }
        )
    
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert len(data["citations"]) > 0


@pytest.mark.asyncio
async def test_ask_no_relevant_docs(client: AsyncClient, db):
    """Test Q&A when no relevant documents found."""
    
    async def mock_rag_query(question, db, doc_ids=None, top_k=3):
        return (MOCK_NO_ANSWER, [], 0.0)
    
    with patch('src.routers.ask.rag_query', side_effect=mock_rag_query):
        response = await client.post(
            "/api/v1/ask",
            json={"question": "What is the contract term?"}
        )
    
    assert response.status_code == 200
    data = response.json()
    
    assert "answer" in data
    assert "no relevant" in data["answer"].lower() or "cannot answer" in data["answer"].lower()
    assert len(data["citations"]) == 0
    assert data["confidence"] == 0.0


@pytest.mark.asyncio
async def test_ask_invalid_question(client: AsyncClient, db):
    """Test Q&A with invalid input."""
    # Empty question
    response = await client.post(
        "/api/v1/ask",
        json={"question": ""}
    )
    assert response.status_code == 422  # Validation error
    
    # Question too long
    long_question = "x" * 1001
    response = await client.post(
        "/api/v1/ask",
        json={"question": long_question}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ask_multiple_citations(client: AsyncClient, db):
    """Test answer with multiple citations from different chunks."""
    from uuid import uuid4
    from src.models.schemas import Citation
    
    mock_doc_id = uuid4()
    mock_citations = [
        Citation(doc_id=mock_doc_id, page=1, start_char=0, end_char=20, text="Term: 12 months"),
        Citation(doc_id=mock_doc_id, page=2, start_char=0, end_char=21, text="Payment: Net 30 days")
    ]
    
    async def mock_rag_query(question, db, doc_ids=None, top_k=3):
        return (MOCK_ANSWER, mock_citations, 0.90)
    
    with patch('src.routers.ask.rag_query', side_effect=mock_rag_query):
        response = await client.post(
            "/api/v1/ask",
            json={"question": "What are the key terms?"}
        )
    
    assert response.status_code == 200
    data = response.json()
    
    # Should have multiple citations
    assert len(data["citations"]) >= 2


@pytest.mark.asyncio
async def test_ask_confidence_score(client: AsyncClient, db):
    """Test that confidence score is returned."""
    from uuid import uuid4
    from src.models.schemas import Citation
    
    mock_citations = [Citation(
        doc_id=uuid4(), page=1, start_char=0, end_char=10, text="Contract"
    )]
    
    async def mock_rag_query(question, db, doc_ids=None, top_k=3):
        return ("Contract details are...", mock_citations, 0.87)
    
    with patch('src.routers.ask.rag_query', side_effect=mock_rag_query):
        response = await client.post(
            "/api/v1/ask",
            json={"question": "What are the details?"}
        )
    
    assert response.status_code == 200
    data = response.json()
    
    assert "confidence" in data
    assert data["confidence"] == 0.87
    assert 0.0 <= data["confidence"] <= 1.0


@pytest.mark.asyncio
async def test_ask_metrics_incremented(client: AsyncClient, db):
    """Test that Q&A metrics are incremented."""
    from uuid import uuid4
    from src.models.schemas import Citation
    
    # Get initial metrics
    metrics_before = await client.get("/metrics")
    initial_count = metrics_before.json().get("qa_requests_total", 0)
    
    mock_citations = [Citation(
        doc_id=uuid4(), page=1, start_char=0, end_char=10, text="Test"
    )]
    
    async def mock_rag_query(question, db, doc_ids=None, top_k=3):
        return ("Test answer", mock_citations, 0.85)
    
    with patch('src.routers.ask.rag_query', side_effect=mock_rag_query):
        await client.post(
            "/api/v1/ask",
            json={"question": "Test question?"}
        )
    
    # Check metrics increased
    metrics_after = await client.get("/metrics")
    final_count = metrics_after.json().get("qa_requests_total", 0)
    
    assert final_count == initial_count + 1
