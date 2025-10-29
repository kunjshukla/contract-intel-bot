"""
Extraction models and schemas for structured contract field extraction.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LiabilityCapField(BaseModel):
    """Liability cap with amount and currency."""
    
    amount: Optional[float] = Field(None, description="Numeric liability cap amount")
    currency: Optional[str] = Field(None, description="Currency code (e.g., USD, EUR)")


class SignatoryField(BaseModel):
    """Contract signatory with name and title."""
    
    name: str = Field(..., description="Signatory name")
    title: Optional[str] = Field(None, description="Signatory title/role")


class ExtractionFields(BaseModel):
    """Structured fields extracted from a contract."""
    
    parties: List[str] = Field(
        default_factory=list,
        description="List of contracting parties (legal entity names)"
    )
    effective_date: Optional[str] = Field(
        None,
        description="Contract effective date in ISO format (YYYY-MM-DD)"
    )
    term: Optional[str] = Field(
        None,
        description="Contract duration/term (e.g., '12 months', '2 years')"
    )
    governing_law: Optional[str] = Field(
        None,
        description="Jurisdiction or governing law (e.g., 'State of California')"
    )
    payment_terms: Optional[str] = Field(
        None,
        description="Payment terms (e.g., 'Net 30 days', 'Due on receipt')"
    )
    termination: Optional[str] = Field(
        None,
        description="Termination conditions summary"
    )
    auto_renewal: Optional[bool] = Field(
        None,
        description="Whether contract auto-renews (true/false/null if unclear)"
    )
    confidentiality: Optional[bool] = Field(
        None,
        description="Whether confidentiality/NDA clause exists"
    )
    indemnity: Optional[str] = Field(
        None,
        description="Indemnification terms (e.g., 'Mutual indemnification')"
    )
    liability_cap: Optional[LiabilityCapField] = Field(
        None,
        description="Liability limitation with amount and currency"
    )
    signatories: List[SignatoryField] = Field(
        default_factory=list,
        description="List of contract signatories"
    )
    
    @field_validator('effective_date')
    @classmethod
    def validate_date_format(cls, v):
        """Validate date is in ISO format or None."""
        if v is None:
            return v
        # Try to parse to ensure valid date format
        try:
            from datetime import datetime
            datetime.fromisoformat(v)
            return v
        except (ValueError, TypeError):
            # If invalid, return None rather than error
            return None


class ExtractionOut(BaseModel):
    """Response schema for extraction endpoint."""
    
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID = Field(..., description="Extraction record ID")
    doc_id: UUID = Field(..., description="Document ID")
    fields: ExtractionFields = Field(..., description="Extracted structured fields")
    extracted_at: datetime = Field(..., description="Extraction timestamp")
    extraction_method: str = Field(default="llm", description="Extraction method used")
