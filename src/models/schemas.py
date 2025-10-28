"""
Pydantic v2 schemas for API validation and serialization.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


# Extraction Schemas
class LiabilityCap(BaseModel):
    """Liability cap details."""

    amount: Optional[float] = None
    currency: str = "USD"


class Signatory(BaseModel):
    """Contract signatory details."""

    name: str
    title: str


class ExtractionFields(BaseModel):
    """Structured fields extracted from contract."""

    parties: List[str] = Field(default_factory=list)
    effective_date: Optional[str] = None  # ISO date string
    term: Optional[str] = None
    governing_law: Optional[str] = None
    payment_terms: Optional[str] = None
    termination: Optional[str] = None
    auto_renewal: Optional[bool] = None
    confidentiality: Optional[bool] = None
    indemnity: Optional[str] = None
    liability_cap: Optional[LiabilityCap] = None
    signatories: List[Signatory] = Field(default_factory=list)


# Document Schemas
class DocumentIn(BaseModel):
    """Document upload request."""

    filename: str = Field(..., min_length=1, max_length=255)


class DocumentOut(BaseModel):
    """Document response."""

    id: UUID
    filename: str
    upload_date: datetime
    file_size: Optional[int] = None
    num_pages: Optional[int] = None
    metadata: dict = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


# Extraction Response
class ExtractionOut(BaseModel):
    """Extraction response with fields and confidence."""

    doc_id: UUID
    fields: ExtractionFields
    extraction_method: str
    confidence: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Q&A Schemas
class Citation(BaseModel):
    """Source citation for RAG answers."""

    doc_id: UUID
    page: int
    start_char: int
    end_char: int
    text: str


class AskRequest(BaseModel):
    """Q&A request."""

    question: str = Field(..., min_length=1, max_length=1000)
    doc_ids: Optional[List[UUID]] = None


class AskResponse(BaseModel):
    """Q&A response with citations."""

    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    citations: List[Citation] = Field(default_factory=list)


# Audit Schemas
class Finding(BaseModel):
    """Risk audit finding."""

    risk_type: str
    severity: str  # "low" | "medium" | "high" | "critical"
    description: str
    evidence: dict  # {page, start_char, end_char, text}
    recommendation: str


class AuditOut(BaseModel):
    """Audit response."""

    doc_id: UUID
    findings: List[Finding]
    risk_score: float
    audit_date: datetime

    model_config = ConfigDict(from_attributes=True)


# Health & Metrics
class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    timestamp: datetime
    version: str


class MetricsResponse(BaseModel):
    """Metrics response."""

    ingests_total: int = 0
    extractions_total: int = 0
    qa_requests_total: int = 0
    audits_total: int = 0
