"""
Vector store management with FAISS for local similarity search.
"""

import os
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import faiss
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.logging import logger
from src.db.models import Chunk


class VectorStore:
    """
    FAISS-based vector store for document embeddings.
    
    Manages a global FAISS index with document metadata for fast similarity search.
    Uses IndexFlatL2 for exact L2 distance search (suitable for <100K vectors).
    """

    def __init__(self, dimension: int = 1536, index_path: Optional[str] = None):
        """
        Initialize vector store.
        
        Args:
            dimension: Embedding dimension (1536 for OpenAI ada-002)
            index_path: Path to persisted FAISS index file
        """
        self.dimension = dimension
        settings = get_settings()
        self.index_path = Path(index_path or settings.FAISS_INDEX_PATH)
        self.metadata_path = self.index_path.with_suffix(".metadata.pkl")
        
        # Create data directory if needed
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load or create index
        if self.index_path.exists():
            self.index = self._load_index()
            self.metadata = self._load_metadata()
            logger.info(
                "FAISS index loaded",
                vectors=self.index.ntotal,
                path=str(self.index_path),
            )
        else:
            self.index = faiss.IndexFlatL2(dimension)
            self.metadata: List[Dict] = []
            logger.info("New FAISS index created", dimension=dimension)

    def _load_index(self) -> faiss.Index:
        """Load FAISS index from disk."""
        try:
            return faiss.read_index(str(self.index_path))
        except Exception as e:
            logger.error("Failed to load FAISS index", error=str(e))
            # Return new index on failure
            return faiss.IndexFlatL2(self.dimension)

    def _load_metadata(self) -> List[Dict]:
        """Load metadata mapping (index position -> chunk metadata)."""
        try:
            if self.metadata_path.exists():
                with open(self.metadata_path, "rb") as f:
                    return pickle.load(f)
        except Exception as e:
            logger.error("Failed to load metadata", error=str(e))
        return []

    def _save(self) -> None:
        """Persist index and metadata to disk."""
        try:
            faiss.write_index(self.index, str(self.index_path))
            with open(self.metadata_path, "wb") as f:
                pickle.dump(self.metadata, f)
            logger.debug(
                "FAISS index saved",
                vectors=self.index.ntotal,
                path=str(self.index_path),
            )
        except Exception as e:
            logger.error("Failed to save FAISS index", error=str(e))
            raise

    def add_documents(
        self,
        embeddings: np.ndarray,
        documents: List[Dict],
    ) -> None:
        """
        Add documents with embeddings to the index.
        
        Args:
            embeddings: Array of shape (n_docs, dimension)
            documents: List of metadata dicts with keys:
                - doc_id: UUID of source document
                - chunk_id: UUID of chunk
                - page: Page number
                - text: Chunk text
                - start_char: Start character offset
                - end_char: End character offset
        """
        if embeddings.shape[0] != len(documents):
            raise ValueError(
                f"Embeddings ({embeddings.shape[0]}) and documents ({len(documents)}) count mismatch"
            )

        if embeddings.shape[1] != self.dimension:
            raise ValueError(
                f"Embedding dimension ({embeddings.shape[1]}) doesn't match index ({self.dimension})"
            )

        # Add to FAISS index
        self.index.add(embeddings.astype(np.float32))
        
        # Store metadata
        self.metadata.extend(documents)
        
        # Persist to disk
        self._save()
        
        logger.info(
            "Documents added to FAISS",
            count=len(documents),
            total_vectors=self.index.ntotal,
        )

    def search(
        self,
        query_embedding: np.ndarray,
        k: int = 5,
        doc_id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Search for similar documents.
        
        Args:
            query_embedding: Query vector of shape (dimension,) or (1, dimension)
            k: Number of results to return
            doc_id: Optional filter by document ID
            
        Returns:
            List of dicts with keys: doc_id, chunk_id, text, page, score, start_char, end_char
        """
        if self.index.ntotal == 0:
            logger.warning("Search called on empty FAISS index")
            return []

        # Reshape query to (1, dimension)
        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)

        # Search FAISS
        distances, indices = self.index.search(
            query_embedding.astype(np.float32), min(k, self.index.ntotal)
        )

        # Retrieve metadata
        results = []
        for distance, idx in zip(distances[0], indices[0]):
            if idx >= len(self.metadata):
                logger.warning("Invalid index in FAISS search", idx=idx)
                continue

            metadata = self.metadata[idx]
            
            # Filter by doc_id if specified
            if doc_id and str(metadata.get("doc_id")) != str(doc_id):
                continue

            results.append({
                **metadata,
                "score": float(distance),  # L2 distance (lower is better)
            })

        # If filtered by doc_id, may have fewer results
        return results[:k]

    async def search_by_text(
        self,
        query_text: str,
        k: int = 5,
        doc_id: Optional[str] = None,
        embedding_func=None,
    ) -> List[Dict]:
        """
        Search by text query (requires embedding function).
        
        Args:
            query_text: Text to search for
            k: Number of results
            doc_id: Optional document filter
            embedding_func: Async function to embed query_text
            
        Returns:
            Search results sorted by similarity
        """
        if embedding_func is None:
            raise ValueError("embedding_func is required for text search")

        # Get query embedding
        query_embedding = await embedding_func(query_text)
        
        # Search
        return self.search(query_embedding, k=k, doc_id=doc_id)

    def delete_by_doc_id(self, doc_id: str) -> int:
        """
        Delete all chunks for a document.
        
        Note: FAISS doesn't support deletion, so we rebuild the index.
        
        Args:
            doc_id: Document UUID to delete
            
        Returns:
            Number of chunks deleted
        """
        # Find indices to keep
        keep_indices = [
            i for i, meta in enumerate(self.metadata)
            if str(meta.get("doc_id")) != str(doc_id)
        ]

        if len(keep_indices) == len(self.metadata):
            logger.warning("No chunks found for doc_id", doc_id=doc_id)
            return 0

        deleted_count = len(self.metadata) - len(keep_indices)

        # Rebuild index with remaining vectors
        if keep_indices:
            # Extract vectors (FAISS doesn't expose this cleanly, so we rebuild)
            new_index = faiss.IndexFlatL2(self.dimension)
            new_metadata = [self.metadata[i] for i in keep_indices]
            
            # Note: This is inefficient for large indices
            # For production, consider soft-deletion via metadata flag
            logger.warning(
                "Rebuilding FAISS index after deletion",
                deleted=deleted_count,
                remaining=len(new_metadata),
            )
            
            self.index = new_index
            self.metadata = new_metadata
        else:
            # All vectors deleted
            self.index = faiss.IndexFlatL2(self.dimension)
            self.metadata = []

        self._save()
        
        logger.info("Deleted chunks from FAISS", doc_id=doc_id, count=deleted_count)
        return deleted_count

    def get_stats(self) -> Dict:
        """Get index statistics."""
        return {
            "total_vectors": self.index.ntotal,
            "dimension": self.dimension,
            "index_type": type(self.index).__name__,
            "index_path": str(self.index_path),
            "metadata_count": len(self.metadata),
        }


# Global vector store instance
_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """Get or create global vector store instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store


async def get_chunk_texts_from_db(
    doc_id: str,
    db: AsyncSession,
) -> List[Tuple[str, Dict]]:
    """
    Retrieve chunk texts and metadata from database.
    
    Args:
        doc_id: Document UUID
        db: Database session
        
    Returns:
        List of (text, metadata) tuples
    """
    result = await db.execute(
        select(Chunk)
        .where(Chunk.doc_id == doc_id)
        .order_by(Chunk.chunk_index)
    )
    chunks = result.scalars().all()
    
    return [
        (
            chunk.text,
            {
                "doc_id": str(chunk.doc_id),
                "chunk_id": str(chunk.id),
                "page": chunk.page_num,
                "start_char": chunk.char_start,
                "end_char": chunk.char_end,
                "chunk_index": chunk.chunk_index,
            },
        )
        for chunk in chunks
    ]
