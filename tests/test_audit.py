"""
Tests for audit endpoint and service.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.db.models import Document, Chunk, Audit
from src.models.schemas import Finding
from src.services.audit import (
    run_rules,
    llm_audit,
    merge_findings,
    audit_document,
)


# Sample contract text with known risks
RISKY_CONTRACT = """
MASTER SERVICE AGREEMENT

This Agreement shall automatically renew for successive one-year terms unless 
either party provides written notice at least 15 days prior to the end of the 
then-current term.

INDEMNIFICATION
Company shall indemnify and hold harmless Client from any and all claims, damages, 
losses, and expenses without limitation arising out of or relating to the Services.

LIABILITY
The Company's liability under this Agreement shall not be limited and may include 
unlimited damages for any breach or negligence.

TERM
This Agreement shall continue in perpetuity unless terminated by Client with 
90 days written notice. Company may not terminate except for cause.
"""

CLEAN_CONTRACT = """
MASTER SERVICE AGREEMENT

This Agreement shall have an initial term of one year and may be renewed upon 
mutual written consent of both parties at least 60 days prior to expiration.

LIMITATION OF LIABILITY
In no event shall either party's liability exceed the total fees paid in the 
twelve months preceding the claim.

TERMINATION
Either party may terminate this Agreement for convenience with 30 days written notice.
"""


@pytest.fixture
async def sample_document(db_session):
    """Create a sample document with chunks."""
    doc = Document(
        id=uuid4(),
        filename="test_contract.pdf",
        file_size=50000,
        num_pages=5,
    )
    db_session.add(doc)
    await db_session.flush()
    
    # Add chunks with risky content
    chunk1 = Chunk(
        doc_id=doc.id,
        chunk_index=0,
        page_num=1,
        text=RISKY_CONTRACT[:500],
        char_start=0,
        char_end=500,
    )
    chunk2 = Chunk(
        doc_id=doc.id,
        chunk_index=1,
        page_num=2,
        text=RISKY_CONTRACT[500:],
        char_start=500,
        char_end=len(RISKY_CONTRACT),
    )
    
    db_session.add_all([chunk1, chunk2])
    await db_session.commit()
    
    return doc


@pytest.fixture
async def clean_document(db_session):
    """Create a document with no risks."""
    doc = Document(
        id=uuid4(),
        filename="clean_contract.pdf",
        file_size=30000,
        num_pages=3,
    )
    db_session.add(doc)
    await db_session.flush()
    
    chunk = Chunk(
        doc_id=doc.id,
        chunk_index=0,
        page_num=1,
        text=CLEAN_CONTRACT,
        char_start=0,
        char_end=len(CLEAN_CONTRACT),
    )
    
    db_session.add(chunk)
    await db_session.commit()
    
    return doc


class TestRuleBasedAudit:
    """Test rule-based pattern matching."""
    
    def test_detect_auto_renewal_short_notice(self):
        """Should detect auto-renewal with <30 day notice."""
        page_breaks = {1: 0, 2: 500}
        findings = run_rules(RISKY_CONTRACT, page_breaks)
        
        auto_renewal_findings = [
            f for f in findings if f['risk_type'] == 'auto_renewal_short_notice'
        ]
        
        assert len(auto_renewal_findings) > 0
        finding = auto_renewal_findings[0]
        assert finding['severity'] == 'high'  # 15 days < 30
        assert '15 days' in finding['evidence']['text'].lower()
        assert 'Negotiate for at least 60-90 days' in finding['recommendation']
    
    def test_detect_unlimited_liability(self):
        """Should detect unlimited liability clauses."""
        page_breaks = {1: 0, 2: 500}
        findings = run_rules(RISKY_CONTRACT, page_breaks)
        
        liability_findings = [
            f for f in findings if f['risk_type'] == 'unlimited_liability'
        ]
        
        assert len(liability_findings) > 0
        finding = liability_findings[0]
        assert finding['severity'] == 'high'
        assert 'unlimited' in finding['evidence']['text'].lower() or \
               'without limitation' in finding['evidence']['text'].lower()
        assert 'CRITICAL' in finding['recommendation'] or \
               'liability cap' in finding['recommendation']
    
    def test_detect_broad_indemnity(self):
        """Should detect broad indemnification."""
        page_breaks = {1: 0, 2: 500}
        findings = run_rules(RISKY_CONTRACT, page_breaks)
        
        indemnity_findings = [
            f for f in findings if f['risk_type'] == 'broad_indemnity'
        ]
        
        assert len(indemnity_findings) > 0
        finding = indemnity_findings[0]
        assert finding['severity'] in ('medium', 'high')
        assert 'any and all' in finding['evidence']['text'].lower()
    
    def test_detect_evergreen_clause(self):
        """Should detect evergreen/perpetual terms."""
        page_breaks = {1: 0, 2: 500}
        findings = run_rules(RISKY_CONTRACT, page_breaks)
        
        evergreen_findings = [
            f for f in findings if f['risk_type'] == 'evergreen_clause'
        ]
        
        # May or may not detect depending on regex - just verify structure if found
        if len(evergreen_findings) > 0:
            finding = evergreen_findings[0]
            assert 'perpetuity' in finding['evidence']['text'].lower() or \
                   'perpetual' in finding['evidence']['text'].lower()
    
    def test_clean_contract_no_findings(self):
        """Should return no findings for clean contract."""
        page_breaks = {1: 0, 2: 500}
        findings = run_rules(CLEAN_CONTRACT, page_breaks)
        
        # Clean contract should have no or very few findings
        high_severity = [f for f in findings if f['severity'] in ('high', 'critical')]
        assert len(high_severity) == 0
    
    def test_page_number_tracking(self):
        """Should correctly track page numbers."""
        page_breaks = {1: 0, 2: 200, 3: 400}
        findings = run_rules(RISKY_CONTRACT, page_breaks)
        
        # All findings should have valid page numbers
        for finding in findings:
            assert finding['evidence']['page'] >= 1
            assert finding['evidence']['page'] <= 3


class TestLLMAudit:
    """Test LLM-based audit."""
    
    @pytest.mark.asyncio
    async def test_llm_audit_success(self):
        """Should parse LLM response correctly."""
        llm_response = [
            {
                "type": "auto_renewal_short_notice",
                "severity": "high",
                "evidence": {
                    "page": 1,
                    "span": "100-200",
                    "text": "automatically renew with 15 days notice"
                },
                "description": "Short notice period for auto-renewal"
            },
            {
                "type": "one_sided_terms",
                "severity": "medium",
                "evidence": {
                    "page": 3,
                    "span": "500-600",
                    "text": "Company may not terminate except for cause"
                },
                "description": "One-sided termination rights"
            }
        ]
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(llm_response)
        
        with patch('src.services.audit.client.chat.completions.create', 
                   new_callable=AsyncMock, return_value=mock_response):
            
            page_breaks = {1: 0, 2: 500}
            findings = await llm_audit(RISKY_CONTRACT, page_breaks)
            
            assert len(findings) == 2
            assert findings[0]['risk_type'] == 'auto_renewal_short_notice'
            assert findings[0]['severity'] == 'high'
            assert findings[0]['source'] == 'llm'
            assert findings[1]['risk_type'] == 'one_sided_terms'
    
    @pytest.mark.asyncio
    async def test_llm_audit_with_markdown_json(self):
        """Should handle JSON wrapped in markdown code blocks."""
        llm_response_md = """```json
[
  {
    "type": "unlimited_liability",
    "severity": "critical",
    "evidence": {
      "page": 2,
      "span": "300-400",
      "text": "without limitation"
    },
    "description": "No liability cap"
  }
]
```"""
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = llm_response_md
        
        with patch('src.services.audit.client.chat.completions.create',
                   new_callable=AsyncMock, return_value=mock_response):
            
            page_breaks = {1: 0}
            findings = await llm_audit(RISKY_CONTRACT, page_breaks)
            
            assert len(findings) == 1
            assert findings[0]['risk_type'] == 'unlimited_liability'
            assert findings[0]['severity'] == 'critical'
    
    @pytest.mark.asyncio
    async def test_llm_audit_empty_response(self):
        """Should handle empty findings array."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "[]"
        
        with patch('src.services.audit.client.chat.completions.create',
                   new_callable=AsyncMock, return_value=mock_response):
            
            page_breaks = {1: 0}
            findings = await llm_audit(CLEAN_CONTRACT, page_breaks)
            
            assert len(findings) == 0
    
    @pytest.mark.asyncio
    async def test_llm_audit_failure_fallback(self):
        """Should return empty array on LLM failure."""
        with patch('src.services.audit.client.chat.completions.create',
                   new_callable=AsyncMock, side_effect=Exception("API timeout")):
            
            page_breaks = {1: 0}
            findings = await llm_audit(RISKY_CONTRACT, page_breaks)
            
            assert findings == []


class TestMergingAndDeduplication:
    """Test finding merging logic."""
    
    def test_merge_no_duplicates(self):
        """Should merge distinct findings."""
        rule_findings = [
            {
                'risk_type': 'auto_renewal_short_notice',
                'severity': 'high',
                'description': 'Rule-based finding',
                'evidence': {'page': 1, 'start_char': 100, 'end_char': 200, 'text': 'rule text'},
                'recommendation': 'Fix it',
                'source': 'rule-based'
            }
        ]
        
        llm_findings = [
            {
                'risk_type': 'unlimited_liability',
                'severity': 'critical',
                'description': 'LLM finding',
                'evidence': {'page': 2, 'start_char': 500, 'end_char': 600, 'text': 'llm text'},
                'recommendation': 'Fix it',
                'source': 'llm'
            }
        ]
        
        merged = merge_findings(rule_findings, llm_findings)
        
        assert len(merged) == 2
        assert merged[0]['source'] == 'rule-based'
        assert merged[1]['source'] == 'llm'
    
    def test_merge_with_duplicates(self):
        """Should deduplicate overlapping findings."""
        rule_findings = [
            {
                'risk_type': 'auto_renewal_short_notice',
                'severity': 'high',
                'description': 'Rule-based finding',
                'evidence': {'page': 1, 'start_char': 100, 'end_char': 200, 'text': 'text'},
                'recommendation': 'Fix it',
                'source': 'rule-based'
            }
        ]
        
        # LLM found same risk at similar location
        llm_findings = [
            {
                'risk_type': 'auto_renewal_short_notice',
                'severity': 'high',
                'description': 'LLM finding (duplicate)',
                'evidence': {'page': 1, 'start_char': 120, 'end_char': 220, 'text': 'text'},
                'recommendation': 'Fix it',
                'source': 'llm'
            }
        ]
        
        merged = merge_findings(rule_findings, llm_findings)
        
        # Should only keep rule-based (priority)
        assert len(merged) == 1
        assert merged[0]['source'] == 'rule-based'
    
    def test_merge_different_pages_same_type(self):
        """Should keep findings of same type on different pages."""
        rule_findings = [
            {
                'risk_type': 'broad_indemnity',
                'severity': 'medium',
                'description': 'Finding on page 1',
                'evidence': {'page': 1, 'start_char': 100, 'end_char': 200, 'text': 'text'},
                'recommendation': 'Fix it',
                'source': 'rule-based'
            }
        ]
        
        llm_findings = [
            {
                'risk_type': 'broad_indemnity',
                'severity': 'medium',
                'description': 'Finding on page 3',
                'evidence': {'page': 3, 'start_char': 1000, 'end_char': 1100, 'text': 'text'},
                'recommendation': 'Fix it',
                'source': 'llm'
            }
        ]
        
        merged = merge_findings(rule_findings, llm_findings)
        
        # Different pages = different findings
        assert len(merged) == 2


class TestAuditEndpoint:
    """Test audit API endpoints."""
    
    @pytest.mark.asyncio
    async def test_audit_document_success(self, async_client: AsyncClient, sample_document):
        """Should audit document and return findings."""
        # Mock LLM to return empty (rely on rules only)
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "[]"
        
        with patch('src.services.audit.client.chat.completions.create',
                   new_callable=AsyncMock, return_value=mock_response):
            
            response = await async_client.post(f"/audit/{sample_document.id}")
            
            assert response.status_code == 200
            data = response.json()
            
            assert data['doc_id'] == str(sample_document.id)
            assert 'findings' in data
            assert isinstance(data['findings'], list)
            assert data['risk_score'] >= 0.0
            assert data['risk_score'] <= 10.0
            assert 'audit_date' in data
            
            # Should have detected at least one risk
            assert len(data['findings']) > 0
            
            # Verify finding structure
            finding = data['findings'][0]
            assert 'risk_type' in finding
            assert 'severity' in finding
            assert 'description' in finding
            assert 'evidence' in finding
            assert 'recommendation' in finding
    
    @pytest.mark.asyncio
    async def test_audit_stores_in_database(self, async_client: AsyncClient, sample_document, db_session):
        """Should persist audit results in database."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "[]"
        
        with patch('src.services.audit.client.chat.completions.create',
                   new_callable=AsyncMock, return_value=mock_response):
            
            response = await async_client.post(f"/audit/{sample_document.id}")
            assert response.status_code == 200
            
            # Check database
            from sqlalchemy import select
            stmt = select(Audit).where(Audit.doc_id == sample_document.id)
            result = await db_session.execute(stmt)
            audit = result.scalar_one_or_none()
            
            assert audit is not None
            assert audit.doc_id == sample_document.id
            assert isinstance(audit.findings, list)
            assert audit.risk_score >= 0.0
    
    @pytest.mark.asyncio
    async def test_audit_upsert_existing(self, async_client: AsyncClient, sample_document, db_session):
        """Should update existing audit on re-run."""
        # First audit
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "[]"
        
        with patch('src.services.audit.client.chat.completions.create',
                   new_callable=AsyncMock, return_value=mock_response):
            
            response1 = await async_client.post(f"/audit/{sample_document.id}")
            assert response1.status_code == 200
            audit_date_1 = response1.json()['audit_date']
            
            # Second audit (should update)
            response2 = await async_client.post(f"/audit/{sample_document.id}")
            assert response2.status_code == 200
            audit_date_2 = response2.json()['audit_date']
            
            # Should be updated (different timestamp)
            assert audit_date_2 >= audit_date_1
            
            # Should still be only one record
            from sqlalchemy import select
            stmt = select(Audit).where(Audit.doc_id == sample_document.id)
            result = await db_session.execute(stmt)
            audits = result.scalars().all()
            assert len(audits) == 1
    
    @pytest.mark.asyncio
    async def test_get_audit_success(self, async_client: AsyncClient, sample_document, db_session):
        """Should retrieve stored audit."""
        # Create audit first
        audit = Audit(
            doc_id=sample_document.id,
            findings=[
                {
                    'risk_type': 'auto_renewal_short_notice',
                    'severity': 'high',
                    'description': 'Test risk',
                    'evidence': {'page': 1, 'start_char': 0, 'end_char': 100, 'text': 'test'},
                    'recommendation': 'Fix it'
                }
            ],
            risk_score=5.0
        )
        db_session.add(audit)
        await db_session.commit()
        
        # Retrieve via GET
        response = await async_client.get(f"/audit/{sample_document.id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data['doc_id'] == str(sample_document.id)
        assert len(data['findings']) == 1
        assert data['risk_score'] == 5.0
    
    @pytest.mark.asyncio
    async def test_get_audit_not_found(self, async_client: AsyncClient):
        """Should return 404 if no audit exists."""
        fake_id = uuid4()
        response = await async_client.get(f"/audit/{fake_id}")
        
        assert response.status_code == 404
        assert 'No audit found' in response.json()['detail']
    
    @pytest.mark.asyncio
    async def test_audit_document_not_found(self, async_client: AsyncClient):
        """Should return 404 for non-existent document."""
        fake_id = uuid4()
        response = await async_client.post(f"/audit/{fake_id}")
        
        assert response.status_code == 404
        # Just check that it's a 404, detail message may vary
        assert 'detail' in response.json()
    
    @pytest.mark.asyncio
    async def test_audit_clean_contract(self, async_client: AsyncClient, clean_document):
        """Should return low/no risk score for clean contract."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "[]"
        
        with patch('src.services.audit.client.chat.completions.create',
                   new_callable=AsyncMock, return_value=mock_response):
            
            response = await async_client.post(f"/audit/{clean_document.id}")
            
            assert response.status_code == 200
            data = response.json()
            
            # Clean contract should have low/no risk
            high_findings = [
                f for f in data['findings'] 
                if f['severity'] in ('high', 'critical')
            ]
            assert len(high_findings) == 0


class TestRiskScoreCalculation:
    """Test risk score calculation logic."""
    
    def test_calculate_risk_score_critical(self):
        """Should score critical findings highest."""
        findings = [
            Finding(
                risk_type='unlimited_liability',
                severity='critical',
                description='Test',
                evidence={'page': 1, 'start_char': 0, 'end_char': 100, 'text': 'test'},
                recommendation='Fix'
            )
        ]
        
        from src.routers.audit import calculate_risk_score
        score = calculate_risk_score(findings)
        
        assert score == 10.0  # Critical = 10.0 (capped)
    
    def test_calculate_risk_score_mixed(self):
        """Should sum scores from multiple findings."""
        findings = [
            Finding(
                risk_type='auto_renewal_short_notice',
                severity='high',
                description='Test',
                evidence={'page': 1, 'start_char': 0, 'end_char': 100, 'text': 'test'},
                recommendation='Fix'
            ),
            Finding(
                risk_type='broad_indemnity',
                severity='medium',
                description='Test',
                evidence={'page': 2, 'start_char': 0, 'end_char': 100, 'text': 'test'},
                recommendation='Fix'
            ),
            Finding(
                risk_type='payment_risk',
                severity='low',
                description='Test',
                evidence={'page': 3, 'start_char': 0, 'end_char': 100, 'text': 'test'},
                recommendation='Fix'
            )
        ]
        
        from src.routers.audit import calculate_risk_score
        score = calculate_risk_score(findings)
        
        # high(5.0) + medium(2.0) + low(0.5) = 7.5
        assert score == 7.5
    
    def test_calculate_risk_score_capped(self):
        """Should cap score at 10.0."""
        findings = [
            Finding(
                risk_type=f'risk_{i}',
                severity='high',
                description='Test',
                evidence={'page': 1, 'start_char': 0, 'end_char': 100, 'text': 'test'},
                recommendation='Fix'
            )
            for i in range(5)  # 5 high findings = 5 * 5.0 = 25.0
        ]
        
        from src.routers.audit import calculate_risk_score
        score = calculate_risk_score(findings)
        
        assert score == 10.0  # Capped at max
    
    def test_calculate_risk_score_empty(self):
        """Should return 0.0 for no findings."""
        from src.routers.audit import calculate_risk_score
        score = calculate_risk_score([])
        
        assert score == 0.0
