"""
SQLAlchemy ORM models for documents, chunks, extractions, and audits.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from src.db.engine import Base


class Document(Base):
    """Contract document metadata."""

    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False)
    upload_date = Column(DateTime(timezone=True), server_default=func.now())
    file_size = Column(Integer)  # bytes
    num_pages = Column(Integer)
    doc_metadata = Column(JSON, default=dict, name="metadata")  # {user_id, tags, status, etc.}
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")
    extractions = relationship(
        "Extraction", back_populates="document", cascade="all, delete-orphan"
    )
    audit = relationship(
        "Audit", back_populates="document", uselist=False, cascade="all, delete-orphan"
    )


class Chunk(Base):
    """Document text chunks with embeddings."""

    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"))
    chunk_index = Column(Integer, nullable=False)
    page_num = Column(Integer)
    text = Column(Text, nullable=False)
    char_start = Column(Integer)
    char_end = Column(Integer)
    # Note: Store embedding as JSON for SQLite, use vector type for Postgres with pgvector
    embedding_vector = Column(JSON)  # List[float] with 1536 dimensions
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    document = relationship("Document", back_populates="chunks")


class Extraction(Base):
    """Extracted structured fields from contract."""

    __tablename__ = "extractions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"))
    fields = Column(JSON, nullable=False)  # ExtractionFields as dict
    extraction_method = Column(String(50), default="llm")  # "llm" | "hybrid" | "regex"
    extracted_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    document = relationship("Document", back_populates="extractions")


class Audit(Base):
    """Risk audit findings for contract."""

    __tablename__ = "audits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"))
    findings = Column(JSON, nullable=False)  # List[Finding]
    risk_score = Column(Float)  # 0.0 - 10.0
    audit_date = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    document = relationship("Document", back_populates="audit")
