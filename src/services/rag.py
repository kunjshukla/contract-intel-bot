"""
RAG (Retrieval-Augmented Generation) service for question answering.

Implements semantic search, LLM-based reranking, and grounded answer generation
with precise citations.
"""

import numpy as np
import re
from pathlib import Path
from typing import List, Optional, Tuple
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.logging import logger
from src.core.vector_store import VectorStore
from src.db.models import Chunk, Document
from src.models.schemas import Citation


# Initialize OpenRouter client
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=get_settings().OPENROUTER_API_KEY,
)


async def get_embedding(text: str) -> List[float]:
    """
    Generate embedding for query text using OpenRouter.
    
    Args:
        text: Query text to embed
        
    Returns:
        Embedding vector as list of floats
    """
    try:
        response = await client.embeddings.create(
            model="openai/text-embedding-ada-002",
            input=text
        )
        
        # Handle both dict and object response formats
        if hasattr(response, 'data'):
            return response.data[0].embedding
        else:
            return response['data'][0]['embedding']
            
    except Exception as e:
        logger.error("Embedding generation failed", error=str(e), text_length=len(text))
        raise


async def llm_rerank(
    question: str,
    chunks: List[Chunk],
    top_k: int = 3
) -> List[Tuple[Chunk, float]]:
    """
    Rerank chunks using LLM cross-encoder style scoring.
    
    Args:
        question: User's question
        chunks: Candidate chunks to rerank
        top_k: Number of top chunks to return
        
    Returns:
        List of (chunk, score) tuples, sorted by relevance score descending
    """
    if not chunks:
        return []
    
    scored_chunks = []
    
    for chunk in chunks:
        try:
            # Create reranking prompt
            prompt = f"""Score the relevance of this text chunk to the question on a scale of 0.0 to 1.0.

Question: {question}

Chunk: {chunk.text[:500]}...

Respond with ONLY a number between 0.0 (completely irrelevant) and 1.0 (perfectly relevant).
If the chunk contains specific information that answers the question, score higher.
If the chunk is only tangentially related or doesn't answer the question, score lower."""

            response = await client.chat.completions.create(
                model="anthropic/claude-3.5-sonnet",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.0
            )
            
            score_text = response.choices[0].message.content.strip()
            
            # Extract numeric score
            match = re.search(r'([0-9]*\.?[0-9]+)', score_text)
            if match:
                score = float(match.group(1))
                score = max(0.0, min(1.0, score))  # Clamp to [0, 1]
            else:
                score = 0.5  # Default if parsing fails
            
            scored_chunks.append((chunk, score))
            
            logger.info(
                "Chunk reranked",
                chunk_id=str(chunk.id),
                score=score,
                question_length=len(question)
            )
            
        except Exception as e:
            logger.warning(
                "Reranking failed for chunk",
                chunk_id=str(chunk.id),
                error=str(e)
            )
            scored_chunks.append((chunk, 0.5))  # Default score on error
    
    # Sort by score descending and return top_k
    scored_chunks.sort(key=lambda x: x[1], reverse=True)
    return scored_chunks[:top_k]


async def llm_generate_answer(question: str, contexts: str) -> str:
    """
    Generate answer using LLM with grounded contexts.
    
    Args:
        question: User's question
        contexts: Concatenated context chunks with metadata
        
    Returns:
        Generated answer with inline citations
    """
    # Load RAG prompt template
    prompt_path = Path(__file__).parent.parent.parent / "prompts" / "rag.txt"
    
    if prompt_path.exists():
        prompt_template = prompt_path.read_text()
    else:
        # Fallback prompt if file doesn't exist
        prompt_template = """Answer the following question using ONLY the provided context chunks.

Question: {question}

Context:
{contexts}

Instructions:
1. Answer based ONLY on the provided context
2. Cite sources using the format [doc_id:page:start-end] where start and end are character positions
3. If the context doesn't contain relevant information, say "I cannot answer this question based on the provided documents."
4. Be precise and concise
5. Include multiple citations if using information from different chunks

Answer:"""

    prompt = prompt_template.format(question=question, contexts=contexts)
    
    try:
        response = await client.chat.completions.create(
            model="anthropic/claude-3.5-sonnet",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.3
        )
        
        answer = response.choices[0].message.content.strip()
        
        logger.info(
            "Answer generated",
            question_length=len(question),
            answer_length=len(answer),
            contexts_length=len(contexts)
        )
        
        return answer
        
    except Exception as e:
        logger.error("Answer generation failed", error=str(e), question=question)
        raise


def parse_citations(answer: str, chunks: List[Chunk]) -> List[Citation]:
    """
    Parse citations from answer text and match to chunks.
    
    Expected citation format: [doc_id:page:start-end]
    
    Args:
        answer: Generated answer with inline citations
        chunks: Context chunks that were used
        
    Returns:
        List of parsed Citation objects
    """
    citations = []
    
    # Pattern: [uuid:page:start-end]
    pattern = r'\[([a-f0-9-]{36}):(\d+):(\d+)-(\d+)\]'
    
    for match in re.finditer(pattern, answer):
        try:
            doc_id = UUID(match.group(1))
            page = int(match.group(2))
            start_char = int(match.group(3))
            end_char = int(match.group(4))
            
            # Find the matching chunk to extract text
            chunk_text = ""
            for chunk in chunks:
                if chunk.doc_id == doc_id and chunk.page == page:
                    # Extract the specific range if within bounds
                    if start_char < len(chunk.text) and end_char <= len(chunk.text):
                        chunk_text = chunk.text[start_char:end_char]
                    else:
                        chunk_text = chunk.text[:200]  # Fallback to first 200 chars
                    break
            
            citation = Citation(
                doc_id=doc_id,
                page=page,
                start_char=start_char,
                end_char=end_char,
                text=chunk_text or "[Citation text not found]"
            )
            citations.append(citation)
            
        except (ValueError, IndexError) as e:
            logger.warning("Failed to parse citation", match=match.group(0), error=str(e))
            continue
    
    logger.info("Citations parsed", count=len(citations))
    return citations


async def rag_query(
    question: str,
    db: AsyncSession,
    doc_ids: Optional[List[UUID]] = None,
    top_k: int = 3
) -> Tuple[str, List[Citation], float]:
    """
    Execute RAG query: retrieve, rerank, and generate answer with citations.
    
    Process:
    1. Embed the question
    2. Search vector store for relevant chunks
    3. Filter by doc_ids if provided
    4. Rerank chunks using LLM cross-encoder
    5. Generate grounded answer with citations
    6. Parse and return citations
    
    Args:
        question: User's question
        db: Database session
        doc_ids: Optional list of document IDs to filter search
        top_k: Number of top chunks to use for answer generation
        
    Returns:
        Tuple of (answer, citations, confidence_score)
    """
    logger.info(
        "RAG query started",
        question=question[:100],
        doc_ids=doc_ids,
        top_k=top_k
    )
    
    # Step 1: Generate query embedding
    query_embedding = await get_embedding(question)
    query_embedding_np = np.array(query_embedding, dtype=np.float32)
    
    # Step 2: Search vector store
    vector_store = VectorStore()
    
    # Perform vector search (search more initially, then rerank to top_k)
    search_results = vector_store.search(
        query_embedding=query_embedding_np,
        k=top_k * 3,  # Get 3x candidates for reranking
        doc_id=str(doc_ids[0]) if doc_ids and len(doc_ids) == 1 else None
    )
    
    if not search_results:
        logger.warning("No search results found", question=question[:100])
        return "No relevant documents found to answer this question.", [], 0.0
    
    # Step 3: Fetch chunk objects from database
    chunk_ids = [UUID(result['chunk_id']) for result in search_results]
    
    stmt = select(Chunk).where(Chunk.id.in_(chunk_ids))
    result = await db.execute(stmt)
    chunks = list(result.scalars().all())
    
    # Filter by doc_ids if provided
    if doc_ids:
        chunks = [c for c in chunks if c.doc_id in doc_ids]
    
    if not chunks:
        logger.warning("No chunks found after filtering", doc_ids=doc_ids)
        return "No relevant documents found to answer this question.", [], 0.0
    
    logger.info(
        "Vector search completed",
        results_count=len(chunks),
        filtered_by_docs=bool(doc_ids)
    )
    
    # Step 4: Rerank using LLM
    reranked_chunks = await llm_rerank(question, chunks, top_k=top_k)
    
    if not reranked_chunks:
        return "No relevant information found to answer this question.", [], 0.0
    
    # Extract chunks and compute average confidence
    top_chunks = [chunk for chunk, score in reranked_chunks]
    avg_score = sum(score for _, score in reranked_chunks) / len(reranked_chunks)
    
    logger.info(
        "Reranking completed",
        top_chunks=len(top_chunks),
        avg_relevance_score=avg_score
    )
    
    # Step 5: Build contexts for answer generation
    contexts = []
    for chunk in top_chunks:
        context_text = f"""Document ID: {chunk.doc_id}
Page: {chunk.page}
Text: {chunk.text}
---"""
        contexts.append(context_text)
    
    contexts_str = "\n\n".join(contexts)
    
    # Step 6: Generate answer
    answer = await llm_generate_answer(question, contexts_str)
    
    # Step 7: Parse citations
    citations = parse_citations(answer, top_chunks)
    
    logger.info(
        "RAG query completed",
        answer_length=len(answer),
        citations_count=len(citations),
        confidence=avg_score
    )
    
    return answer, citations, avg_score
