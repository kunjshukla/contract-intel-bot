"""
Contract audit service for risk detection using hybrid rule-based + LLM analysis.

Detects risky clauses such as:
- Auto-renewal with short notice periods (<30 days)
- Unlimited liability (no cap)
- Broad indemnity clauses
"""

import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from uuid import UUID

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.logging import logger
from src.db.models import Document, Chunk
from src.models.schemas import Finding


# Initialize OpenRouter client
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=get_settings().OPENROUTER_API_KEY,
)


# Rule-based patterns for quick detection
RISK_PATTERNS = {
    'auto_renew_short': {
        'pattern': re.compile(
            r'(?:auto[- ]?(?:matically\s+)?renew|automatic[- ]?renewal).*?'
            r'(?:notice|notification|termination|prior).*?'
            r'(\d+)\s*(?:day|calendar day)s?',
            re.IGNORECASE | re.DOTALL
        ),
        'severity_func': lambda days: 'high' if int(days) < 30 else 'medium' if int(days) < 60 else 'low',
        'type': 'auto_renewal_short_notice',
        'description': 'Auto-renewal with short notice period'
    },
    'unlimited_liability': {
        'pattern': re.compile(
            r'(?:unlimited|uncapped|no cap|without limit).*?(?:liability|damages|indemnif)',
            re.IGNORECASE | re.DOTALL
        ),
        'severity': 'high',
        'type': 'unlimited_liability',
        'description': 'Unlimited liability exposure'
    },
    'no_liability_cap': {
        'pattern': re.compile(
            r'(?:liability|damages).*?(?:shall not be limited|without limitation|no maximum)',
            re.IGNORECASE | re.DOTALL
        ),
        'severity': 'high',
        'type': 'unlimited_liability',
        'description': 'No liability cap specified'
    },
    'broad_indemnity': {
        'pattern': re.compile(
            r'(?:indemnif|hold harmless).*?(?:all claims|any and all|whatsoever|without exception)',
            re.IGNORECASE | re.DOTALL
        ),
        'severity': 'medium',
        'type': 'broad_indemnity',
        'description': 'Broad indemnification scope'
    },
    'evergreen_clause': {
        'pattern': re.compile(
            r'(?:perpetuity|perpetual|indefinite|evergreen)(?:\s+\w+){0,10}?(?:term|unless|continue)',
            re.IGNORECASE | re.DOTALL
        ),
        'severity': 'medium',
        'type': 'evergreen_clause',
        'description': 'Evergreen/perpetual term clause'
    }
}


def run_rules(full_text: str, page_breaks: Dict[int, int]) -> List[Dict[str, Any]]:
    """
    Run rule-based pattern matching for quick risk detection.
    
    Args:
        full_text: Complete document text
        page_breaks: Dict mapping page numbers to character offsets
        
    Returns:
        List of finding dictionaries
    """
    findings = []
    
    for rule_name, rule_config in RISK_PATTERNS.items():
        pattern = rule_config['pattern']
        
        for match in pattern.finditer(full_text):
            start_char = match.start()
            end_char = match.end()
            matched_text = match.group(0)
            
            # Determine severity
            if 'severity_func' in rule_config:
                # Extract numeric value for dynamic severity
                days_match = re.search(r'(\d+)', matched_text)
                if days_match:
                    days = days_match.group(1)
                    severity = rule_config['severity_func'](days)
                else:
                    severity = 'medium'
            else:
                severity = rule_config['severity']
            
            # Determine page number
            page = 1
            for pg, offset in sorted(page_breaks.items()):
                if start_char >= offset:
                    page = pg
                else:
                    break
            
            finding = {
                'risk_type': rule_config['type'],
                'severity': severity,
                'description': rule_config['description'],
                'evidence': {
                    'page': page,
                    'start_char': start_char,
                    'end_char': end_char,
                    'text': matched_text[:200]  # Limit to 200 chars
                },
                'recommendation': _get_recommendation(rule_config['type'], severity),
                'source': 'rule-based'
            }
            
            findings.append(finding)
            
            logger.info(
                "Rule-based finding detected",
                rule=rule_name,
                severity=severity,
                page=page
            )
    
    return findings


def _get_recommendation(risk_type: str, severity: str) -> str:
    """Generate recommendation based on risk type and severity."""
    recommendations = {
        'auto_renewal_short_notice': {
            'high': 'Negotiate for at least 60-90 days notice period before auto-renewal.',
            'medium': 'Consider extending notice period to 60+ days.',
            'low': 'Notice period is acceptable but document renewal dates carefully.'
        },
        'unlimited_liability': {
            'high': 'CRITICAL: Negotiate a liability cap (e.g., 12 months fees or $X amount).',
            'medium': 'Request limitation of liability to direct damages only.',
            'low': 'Review liability provisions with legal counsel.'
        },
        'broad_indemnity': {
            'high': 'Narrow indemnification to claims arising from specific breaches only.',
            'medium': 'Request mutual indemnification and exclude third-party claims.',
            'low': 'Review indemnity scope with legal counsel.'
        },
        'evergreen_clause': {
            'high': 'Replace with fixed term and explicit renewal option.',
            'medium': 'Add termination for convenience clause with reasonable notice.',
            'low': 'Ensure clear termination rights are documented.'
        }
    }
    
    return recommendations.get(risk_type, {}).get(severity, 'Review with legal counsel.')


async def llm_audit(full_text: str, page_breaks: Dict[int, int]) -> List[Dict[str, Any]]:
    """
    Use LLM to detect nuanced risks that rules might miss.
    
    Args:
        full_text: Complete document text
        page_breaks: Dict mapping page numbers to character offsets
        
    Returns:
        List of finding dictionaries from LLM analysis
    """
    # Load audit prompt template
    prompt_path = Path(__file__).parent.parent.parent / "prompts" / "audit.txt"
    
    if prompt_path.exists():
        prompt_template = prompt_path.read_text()
    else:
        # Fallback prompt
        prompt_template = """Scan the following contract text for compliance risks.

Focus on:
1. Auto-renewal clauses with notice periods less than 30 days
2. Unlimited liability (no cap, uncapped damages)
3. Broad indemnity clauses (all claims, any and all, without exception)
4. Evergreen/perpetual terms without clear termination rights
5. One-sided termination rights
6. Unreasonable confidentiality obligations

Contract Text:
{full_text}

Output ONLY valid JSON array of findings:
[
  {{
    "type": "auto_renewal_short_notice",
    "severity": "high",
    "evidence": {{
      "page": 1,
      "span": "150-200",
      "text": "exact clause text"
    }},
    "description": "Brief description of the risk"
  }}
]

Severity levels: low, medium, high, critical
Risk types: auto_renewal_short_notice, unlimited_liability, broad_indemnity, evergreen_clause, one_sided_terms, unreasonable_confidentiality

If no risks found, return empty array: []"""

    prompt = prompt_template.format(full_text=full_text[:8000])  # Limit context
    
    try:
        response = await client.chat.completions.create(
            model="anthropic/claude-3.5-sonnet",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.1
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Try to parse JSON
        import json
        
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try direct parse
            json_str = response_text
        
        llm_findings_raw = json.loads(json_str)
        
        # Convert to our format
        findings = []
        for finding in llm_findings_raw:
            # Parse span if provided
            span = finding.get('evidence', {}).get('span', '0-0')
            if '-' in str(span):
                start, end = map(int, span.split('-'))
            else:
                start, end = 0, 0
            
            formatted_finding = {
                'risk_type': finding.get('type', 'unknown'),
                'severity': finding.get('severity', 'medium'),
                'description': finding.get('description', ''),
                'evidence': {
                    'page': finding.get('evidence', {}).get('page', 1),
                    'start_char': start,
                    'end_char': end,
                    'text': finding.get('evidence', {}).get('text', '')[:200]
                },
                'recommendation': _get_recommendation(
                    finding.get('type', 'unknown'),
                    finding.get('severity', 'medium')
                ),
                'source': 'llm'
            }
            findings.append(formatted_finding)
        
        logger.info(
            "LLM audit completed",
            findings_count=len(findings),
            text_length=len(full_text)
        )
        
        return findings
        
    except Exception as e:
        logger.error("LLM audit failed", error=str(e))
        return []  # Return empty list on failure (fallback to rules only)


def merge_findings(
    rule_findings: List[Dict[str, Any]],
    llm_findings: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Merge findings from rules and LLM, removing duplicates.
    
    Duplicates are detected by:
    - Same risk_type
    - Overlapping text spans (within 50 chars)
    
    Args:
        rule_findings: Findings from rule-based analysis
        llm_findings: Findings from LLM analysis
        
    Returns:
        Merged and deduplicated findings
    """
    merged = []
    seen = set()
    
    # Add all rule findings first (they're faster/cheaper)
    for finding in rule_findings:
        key = (
            finding['risk_type'],
            finding['evidence']['page'],
            finding['evidence']['start_char'] // 50  # Bucket by ~50 char ranges
        )
        if key not in seen:
            merged.append(finding)
            seen.add(key)
    
    # Add LLM findings if not duplicate
    for finding in llm_findings:
        key = (
            finding['risk_type'],
            finding['evidence']['page'],
            finding['evidence']['start_char'] // 50
        )
        if key not in seen:
            merged.append(finding)
            seen.add(key)
        else:
            logger.debug(
                "Skipping duplicate LLM finding",
                risk_type=finding['risk_type'],
                page=finding['evidence']['page']
            )
    
    return merged


async def get_full_document_text(db: AsyncSession, doc_id: UUID) -> tuple[str, Dict[int, int]]:
    """
    Retrieve full document text and page break offsets.
    
    Args:
        db: Database session
        doc_id: Document UUID
        
    Returns:
        Tuple of (full_text, page_breaks_dict)
    """
    stmt = select(Chunk).where(Chunk.doc_id == doc_id).order_by(Chunk.page, Chunk.chunk_index)
    result = await db.execute(stmt)
    chunks = result.scalars().all()
    
    if not chunks:
        raise ValueError(f"No chunks found for document {doc_id}")
    
    # Concatenate text and track page offsets
    full_text = ""
    page_breaks = {}
    current_page = 1
    
    for chunk in chunks:
        if chunk.page != current_page:
            page_breaks[chunk.page] = len(full_text)
            current_page = chunk.page
        
        full_text += chunk.text + "\n\n"
    
    return full_text, page_breaks


async def audit_document(
    db: AsyncSession,
    doc_id: UUID,
    mode: str = "hybrid"
) -> List[Finding]:
    """
    Audit document for compliance risks using hybrid approach.
    
    Process:
    1. Retrieve full document text
    2. Run rule-based detection (fast, deterministic)
    3. Run LLM analysis (nuanced, context-aware)
    4. Merge findings and deduplicate
    5. Sort by severity
    
    Args:
        db: Database session
        doc_id: Document UUID
        mode: "hybrid" (default), "rules", or "llm"
        
    Returns:
        List of Finding objects sorted by severity
    """
    logger.info(
        "Starting document audit",
        doc_id=str(doc_id),
        mode=mode
    )
    
    # Get document text
    full_text, page_breaks = await get_full_document_text(db, doc_id)
    
    logger.info(
        "Document text retrieved",
        doc_id=str(doc_id),
        text_length=len(full_text),
        pages=len(page_breaks)
    )
    
    # Run rule-based detection
    rule_findings = []
    if mode in ("hybrid", "rules"):
        rule_findings = run_rules(full_text, page_breaks)
        logger.info(
            "Rule-based audit completed",
            findings_count=len(rule_findings)
        )
    
    # Run LLM analysis
    llm_findings = []
    if mode in ("hybrid", "llm"):
        llm_findings = await llm_audit(full_text, page_breaks)
        logger.info(
            "LLM audit completed",
            findings_count=len(llm_findings)
        )
    
    # Merge findings
    all_findings = merge_findings(rule_findings, llm_findings)
    
    # Sort by severity (critical > high > medium > low)
    severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    sorted_findings = sorted(
        all_findings,
        key=lambda f: severity_order.get(f['severity'], 4)
    )
    
    # Convert to Finding objects
    findings = [
        Finding(
            risk_type=f['risk_type'],
            severity=f['severity'],
            description=f['description'],
            evidence=f['evidence'],
            recommendation=f['recommendation']
        )
        for f in sorted_findings
    ]
    
    logger.info(
        "Audit completed",
        doc_id=str(doc_id),
        total_findings=len(findings),
        high_severity=sum(1 for f in findings if f.severity in ('high', 'critical'))
    )
    
    return findings
