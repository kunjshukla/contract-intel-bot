"""
LLM-based contract field extraction service using OpenRouter.
"""

import json
import re
from pathlib import Path
from typing import Dict, Optional

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.logging import logger
from src.db.models import Document, Chunk
from src.models.extraction import ExtractionFields


# Load extraction prompt template
PROMPT_FILE = Path(__file__).parent.parent.parent / "prompts" / "extract.txt"
with open(PROMPT_FILE, "r") as f:
    EXTRACTION_PROMPT_TEMPLATE = f.read()


async def get_full_document_text(doc_id, db: AsyncSession) -> str:
    """
    Retrieve full document text by concatenating all chunks in order.
    
    Args:
        doc_id: Document UUID (can be string or UUID object)
        db: Database session
        
    Returns:
        Full document text as string
        
    Raises:
        ValueError: If document not found or has no text
    """
    from uuid import UUID
    
    # Convert to UUID if string
    if isinstance(doc_id, str):
        doc_id = UUID(doc_id)
    
    # Fetch document to verify it exists
    doc_result = await db.execute(
        select(Document).where(Document.id == doc_id)
    )
    document = doc_result.scalar_one_or_none()
    
    if not document:
        raise ValueError(f"Document {doc_id} not found")
    
    # Fetch all chunks ordered by chunk_index
    chunks_result = await db.execute(
        select(Chunk)
        .where(Chunk.doc_id == doc_id)
        .order_by(Chunk.chunk_index)
    )
    chunks = chunks_result.scalars().all()
    
    if not chunks:
        # Fallback: try to get text from document metadata
        if document.doc_metadata and "pages" in document.doc_metadata:
            texts = [page.get("text", "") for page in document.doc_metadata.get("pages", [])]
            full_text = "\n\n".join(texts)
            if full_text.strip():
                return full_text
        raise ValueError(f"Document {doc_id} has no text content (no chunks or metadata)")
    
    # Concatenate chunk texts
    full_text = " ".join(chunk.text for chunk in chunks if chunk.text)
    
    if not full_text.strip():
        raise ValueError(f"Document {doc_id} has empty text content")
    
    logger.info(
        "Retrieved document text",
        doc_id=str(doc_id),
        num_chunks=len(chunks),
        text_length=len(full_text)
    )
    
    return full_text


async def llm_extract(text: str, retry_on_failure: bool = True) -> Dict:
    """
    Extract structured fields from contract text using Claude-3.5-Sonnet via OpenRouter.
    
    Args:
        text: Full contract text
        retry_on_failure: Whether to retry once if JSON parsing fails
        
    Returns:
        Dictionary of extracted fields validated against ExtractionFields schema
        
    Raises:
        ValueError: If extraction fails after retry
    """
    # Initialize OpenAI client for OpenRouter
    settings = get_settings()
    client = AsyncOpenAI(
        api_key=settings.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1"
    )
    
    # Format prompt with contract text
    # Extract just the user prompt portion (after SYSTEM PROMPT section)
    prompt_lines = EXTRACTION_PROMPT_TEMPLATE.split("\n")
    user_prompt_start = None
    for i, line in enumerate(prompt_lines):
        if "USER PROMPT:" in line:
            user_prompt_start = i + 1
            break
    
    if user_prompt_start:
        user_prompt = "\n".join(prompt_lines[user_prompt_start:50])  # Get relevant section
        prompt = user_prompt.replace("{full_text}", text[:15000])  # Limit to ~15k chars to avoid token limits
    else:
        # Fallback simple prompt
        prompt = f"""Extract the following fields from the contract text below. Return ONLY valid JSON.

Required Fields: parties, effective_date, term, governing_law, payment_terms, termination, auto_renewal, confidentiality, indemnity, liability_cap, signatories.

Contract Text:
\"\"\"
{text[:15000]}
\"\"\"

OUTPUT (JSON only):"""
    
    logger.info(
        "Calling LLM for extraction",
        model="anthropic/claude-3.5-sonnet",
        text_length=len(text),
        prompt_length=len(prompt)
    )
    
    try:
        # Call Claude via OpenRouter
        response = await client.chat.completions.create(
            model="anthropic/claude-3.5-sonnet",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.0,  # Deterministic for extraction
            max_tokens=2000,
        )
        
        # Extract response content
        content = response.choices[0].message.content
        
        logger.info(
            "LLM response received",
            response_length=len(content)
        )
        
        # Parse and validate JSON
        try:
            # Strip markdown code blocks if present
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            # Parse JSON
            extracted_data = json.loads(content)
            
            # Validate against schema
            validated_fields = ExtractionFields(**extracted_data)
            
            logger.info(
                "Extraction successful",
                num_parties=len(validated_fields.parties),
                has_date=validated_fields.effective_date is not None,
                has_signatories=len(validated_fields.signatories)
            )
            
            return validated_fields.model_dump()
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(
                "Failed to parse LLM response as JSON",
                error=str(e),
                response_preview=content[:200]
            )
            
            # Retry with stricter prompt if enabled
            if retry_on_failure:
                logger.info("Retrying with strict JSON prompt")
                
                strict_prompt = f"""{prompt}

CRITICAL: Output MUST be valid JSON. Do not include any explanatory text, markdown formatting, or code blocks. Output the raw JSON object only."""
                
                response = await client.chat.completions.create(
                    model="anthropic/claude-3.5-sonnet",
                    messages=[
                        {
                            "role": "user",
                            "content": strict_prompt
                        }
                    ],
                    temperature=0.0,
                    max_tokens=2000,
                )
                
                content = response.choices[0].message.content.strip()
                
                # Clean again
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
                
                try:
                    extracted_data = json.loads(content)
                    validated_fields = ExtractionFields(**extracted_data)
                    return validated_fields.model_dump()
                except (json.JSONDecodeError, ValueError) as retry_error:
                    logger.error(
                        "Retry failed to parse JSON",
                        error=str(retry_error),
                        response=content[:500]
                    )
                    raise ValueError(f"Failed to extract valid JSON after retry: {retry_error}")
            else:
                raise ValueError(f"Failed to parse extraction response: {e}")
    
    except Exception as e:
        logger.error(
            "LLM extraction failed",
            error=str(e),
            error_type=type(e).__name__
        )
        raise


def apply_regex_fallbacks(text: str, fields: Dict) -> Dict:
    """
    Apply regex-based fallback extraction for missing fields.
    
    Useful when LLM fails to extract structured patterns like dates or monetary values.
    
    Args:
        text: Contract text
        fields: Existing extracted fields
        
    Returns:
        Fields dictionary with fallback values added where applicable
    """
    # Date pattern fallback (YYYY-MM-DD, MM/DD/YYYY, Month DD, YYYY)
    if not fields.get("effective_date"):
        date_patterns = [
            r'\b(\d{4})-(\d{2})-(\d{2})\b',  # ISO format
            r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b',  # US format
            r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b'
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                logger.info("Applied regex fallback for effective_date", pattern=pattern)
                # Note: Would need proper date parsing here for production
                fields["effective_date"] = match.group(0)
                break
    
    # Liability cap pattern fallback ($X, $X.XX, USD X)
    if not fields.get("liability_cap") or not fields["liability_cap"].get("amount"):
        money_pattern = r'\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)'
        match = re.search(money_pattern, text)
        if match:
            amount_str = match.group(1).replace(",", "")
            try:
                amount = float(amount_str)
                fields["liability_cap"] = {"amount": amount, "currency": "USD"}
                logger.info("Applied regex fallback for liability_cap", amount=amount)
            except ValueError:
                pass
    
    # Payment terms pattern (Net X days)
    if not fields.get("payment_terms"):
        payment_pattern = r'Net\s+(\d+)\s+days'
        match = re.search(payment_pattern, text, re.IGNORECASE)
        if match:
            fields["payment_terms"] = match.group(0)
            logger.info("Applied regex fallback for payment_terms")
    
    return fields
