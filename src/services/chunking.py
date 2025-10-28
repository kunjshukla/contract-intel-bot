"""
Text chunking and embedding service for RAG pipeline.
"""

import uuid
from typing import List, Optional

import numpy as np
from langchain.text_splitter import RecursiveCharacterTextSplitter
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.logging import logger
from src.core.vector_store import get_vector_store
from src.db.models import Chunk, Document


# Initialize OpenAI client for OpenRouter
settings = get_settings()
openai_client = AsyncOpenAI(
    api_key=settings.OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)


async def get_embedding(text: str, model: Optional[str] = None) -> np.ndarray:
    """
    Get embedding vector for text using OpenRouter.
    
    Args:
        text: Text to embed
        model: Embedding model (defaults to settings.EMBEDDING_MODEL)
        
    Returns:
        Numpy array of shape (1536,) for ada-002
        
    Raises:
        Exception: If embedding API call fails
    """
    model = model or settings.EMBEDDING_MODEL
    
    try:
        response = await openai_client.embeddings.create(
            model=model,
            input=text,
        )
        
        embedding = response.data[0].embedding
        return np.array(embedding, dtype=np.float32)
        
    except Exception as e:
        logger.error(
            "Embedding generation failed",
            model=model,
            text_length=len(text),
            error=str(e),
        )
        raise


def create_text_splitter(
    chunk_size: int = 500,
    chunk_overlap: int = 100,
) -> RecursiveCharacterTextSplitter:
    """
    Create LangChain text splitter for clause-aware chunking.
    
    Args:
        chunk_size: Target chunk size in characters
        chunk_overlap: Overlap between chunks for context preservation
        
    Returns:
        Configured RecursiveCharacterTextSplitter
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=[
            "\n\n",  # Paragraph breaks (clauses)
            "\n",    # Line breaks
            ". ",    # Sentences
            " ",     # Words
            "",      # Characters
        ],
        keep_separator=True,
    )


async def chunk_and_embed(
    doc_id: uuid.UUID,
    db: AsyncSession,
    skip_embedding: bool = False,
) -> int:
    """
    Chunk document text and generate embeddings for RAG.
    
    Process:
    1. Retrieve document with page texts from metadata
    2. Split text into chunks using RecursiveCharacterTextSplitter
    3. Generate embeddings via OpenRouter
    4. Store chunks in database
    5. Add embeddings to FAISS index
    
    Args:
        doc_id: Document UUID
        db: Database session
        skip_embedding: If True, store chunks without embeddings (fallback mode)
        
    Returns:
        Number of chunks created
        
    Raises:
        ValueError: If document not found or has no text
    """
    # Fetch document
    from sqlalchemy import select
    
    result = await db.execute(select(Document).where(Document.id == doc_id))
    document = result.scalar_one_or_none()
    
    if not document:
        raise ValueError(f"Document {doc_id} not found")
    
    # Extract page texts from metadata
    pages = document.metadata.get("pages", [])
    if not pages:
        logger.warning("Document has no page data", doc_id=str(doc_id))
        return 0
    
    logger.info(
        "Starting chunking and embedding",
        doc_id=str(doc_id),
        pages=len(pages),
        skip_embedding=skip_embedding,
    )
    
    # Create text splitter
    splitter = create_text_splitter(
        chunk_size=settings.CHUNK_SIZE_TOKENS,
        chunk_overlap=settings.CHUNK_OVERLAP_TOKENS,
    )
    
    # Process each page
    all_chunks = []
    chunk_index = 0
    
    for page_data in pages:
        page_num = page_data.get("page_num", 1)
        page_text = page_data.get("text", "")
        
        if not page_text.strip():
            continue
        
        # Split page into chunks
        text_chunks = splitter.split_text(page_text)
        
        # Track character positions (approximate)
        char_offset = 0
        
        for text_chunk in text_chunks:
            chunk_start = page_text.find(text_chunk, char_offset)
            if chunk_start == -1:
                chunk_start = char_offset
            chunk_end = chunk_start + len(text_chunk)
            
            all_chunks.append({
                "id": uuid.uuid4(),
                "doc_id": doc_id,
                "chunk_index": chunk_index,
                "page_num": page_num,
                "text": text_chunk,
                "char_start": chunk_start,
                "char_end": chunk_end,
            })
            
            char_offset = chunk_end
            chunk_index += 1
    
    if not all_chunks:
        logger.warning("No chunks created from document", doc_id=str(doc_id))
        return 0
    
    logger.info(
        "Text chunking completed",
        doc_id=str(doc_id),
        chunks=len(all_chunks),
    )
    
    # Generate embeddings
    embeddings_list = []
    failed_chunks = []
    
    if not skip_embedding:
        for i, chunk_data in enumerate(all_chunks):
            try:
                embedding = await get_embedding(chunk_data["text"])
                embeddings_list.append(embedding)
                
                # Store embedding in chunk data as JSON (for database)
                chunk_data["embedding_vector"] = embedding.tolist()
                
            except Exception as e:
                logger.warning(
                    "Embedding failed for chunk",
                    doc_id=str(doc_id),
                    chunk_index=i,
                    error=str(e),
                )
                failed_chunks.append(i)
                # Store None to maintain index alignment
                embeddings_list.append(None)
                chunk_data["embedding_vector"] = None
        
        # Filter out failed embeddings
        valid_embeddings = [emb for emb in embeddings_list if emb is not None]
        valid_chunks = [
            chunk for i, chunk in enumerate(all_chunks)
            if embeddings_list[i] is not None
        ]
        
        if failed_chunks:
            logger.warning(
                "Some embeddings failed",
                doc_id=str(doc_id),
                failed_count=len(failed_chunks),
                total=len(all_chunks),
            )
    else:
        # Skip embedding mode
        valid_embeddings = []
        valid_chunks = all_chunks
        logger.info("Skipping embeddings (fallback mode)", doc_id=str(doc_id))
    
    # Store chunks in database
    chunk_models = []
    for chunk_data in all_chunks:
        chunk_model = Chunk(
            id=chunk_data["id"],
            doc_id=chunk_data["doc_id"],
            chunk_index=chunk_data["chunk_index"],
            page_num=chunk_data["page_num"],
            text=chunk_data["text"],
            char_start=chunk_data["char_start"],
            char_end=chunk_data["char_end"],
            embedding_vector=chunk_data.get("embedding_vector"),
        )
        chunk_models.append(chunk_model)
        db.add(chunk_model)
    
    await db.commit()
    
    logger.info(
        "Chunks stored in database",
        doc_id=str(doc_id),
        count=len(chunk_models),
    )
    
    # Add to FAISS index (only valid embeddings)
    if valid_embeddings:
        embeddings_array = np.vstack(valid_embeddings)
        
        # Prepare metadata for FAISS
        faiss_metadata = [
            {
                "doc_id": str(chunk["doc_id"]),
                "chunk_id": str(chunk["id"]),
                "page": chunk["page_num"],
                "text": chunk["text"],
                "start_char": chunk["char_start"],
                "end_char": chunk["char_end"],
            }
            for chunk in valid_chunks
        ]
        
        # Add to vector store
        vector_store = get_vector_store()
        vector_store.add_documents(embeddings_array, faiss_metadata)
        
        logger.info(
            "Embeddings added to FAISS",
            doc_id=str(doc_id),
            vectors=len(valid_embeddings),
        )
    
    return len(all_chunks)


async def search_similar_chunks(
    query: str,
    k: int = 5,
    doc_id: Optional[uuid.UUID] = None,
) -> List[dict]:
    """
    Search for similar chunks using FAISS.
    
    Args:
        query: Search query text
        k: Number of results to return
        doc_id: Optional filter by document ID
        
    Returns:
        List of chunk metadata with similarity scores
    """
    # Get query embedding
    try:
        query_embedding = await get_embedding(query)
    except Exception as e:
        logger.error("Failed to embed query", query=query, error=str(e))
        return []
    
    # Search FAISS
    vector_store = get_vector_store()
    results = vector_store.search(
        query_embedding,
        k=k,
        doc_id=str(doc_id) if doc_id else None,
    )
    
    logger.info(
        "FAISS search completed",
        query_length=len(query),
        results=len(results),
        doc_id=str(doc_id) if doc_id else None,
    )
    
    return results


async def re_embed_document(
    doc_id: uuid.UUID,
    db: AsyncSession,
) -> int:
    """
    Re-generate embeddings for existing chunks (e.g., after model change).
    
    Args:
        doc_id: Document UUID
        db: Database session
        
    Returns:
        Number of chunks re-embedded
    """
    from sqlalchemy import select, update
    
    # Fetch all chunks for document
    result = await db.execute(
        select(Chunk).where(Chunk.doc_id == doc_id).order_by(Chunk.chunk_index)
    )
    chunks = result.scalars().all()
    
    if not chunks:
        logger.warning("No chunks found for re-embedding", doc_id=str(doc_id))
        return 0
    
    logger.info("Re-embedding chunks", doc_id=str(doc_id), count=len(chunks))
    
    embeddings_list = []
    chunk_metadata = []
    
    for chunk in chunks:
        try:
            embedding = await get_embedding(chunk.text)
            embeddings_list.append(embedding)
            
            # Update database
            await db.execute(
                update(Chunk)
                .where(Chunk.id == chunk.id)
                .values(embedding_vector=embedding.tolist())
            )
            
            chunk_metadata.append({
                "doc_id": str(chunk.doc_id),
                "chunk_id": str(chunk.id),
                "page": chunk.page_num,
                "text": chunk.text,
                "start_char": chunk.char_start,
                "end_char": chunk.char_end,
            })
            
        except Exception as e:
            logger.error(
                "Re-embedding failed for chunk",
                chunk_id=str(chunk.id),
                error=str(e),
            )
    
    await db.commit()
    
    # Update FAISS (delete old, add new)
    if embeddings_list:
        vector_store = get_vector_store()
        vector_store.delete_by_doc_id(str(doc_id))
        
        embeddings_array = np.vstack(embeddings_list)
        vector_store.add_documents(embeddings_array, chunk_metadata)
        
        logger.info(
            "FAISS index updated",
            doc_id=str(doc_id),
            vectors=len(embeddings_list),
        )
    
    return len(embeddings_list)
