"""Create documents table with metadata

Revision ID: 001_create_documents
Revises: 
Create Date: 2025-10-28 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
import uuid


# revision identifiers, used by Alembic.
revision = '001_create_documents'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create documents, chunks, extractions, and audits tables."""
    
    # Documents table
    op.create_table(
        'documents',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('upload_date', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('num_pages', sa.Integer(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True, default=dict),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    
    # Create index on filename for faster lookups
    op.create_index('ix_documents_filename', 'documents', ['filename'])
    op.create_index('ix_documents_upload_date', 'documents', ['upload_date'])
    
    # Chunks table
    op.create_table(
        'chunks',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('doc_id', UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('page_num', sa.Integer(), nullable=True),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('char_start', sa.Integer(), nullable=True),
        sa.Column('char_end', sa.Integer(), nullable=True),
        sa.Column('embedding_vector', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    op.create_index('ix_chunks_doc_id', 'chunks', ['doc_id'])
    op.create_index('ix_chunks_chunk_index', 'chunks', ['chunk_index'])
    
    # Extractions table
    op.create_table(
        'extractions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('doc_id', UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('fields', sa.JSON(), nullable=False),
        sa.Column('extraction_method', sa.String(50), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    op.create_index('ix_extractions_doc_id', 'extractions', ['doc_id'])
    
    # Audits table
    op.create_table(
        'audits',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('doc_id', UUID(as_uuid=True), sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('findings', sa.JSON(), nullable=False),
        sa.Column('risk_score', sa.Float(), nullable=True),
        sa.Column('audit_date', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    
    op.create_index('ix_audits_doc_id', 'audits', ['doc_id'])


def downgrade() -> None:
    """Drop all tables."""
    op.drop_index('ix_audits_doc_id', table_name='audits')
    op.drop_table('audits')
    
    op.drop_index('ix_extractions_doc_id', table_name='extractions')
    op.drop_table('extractions')
    
    op.drop_index('ix_chunks_chunk_index', table_name='chunks')
    op.drop_index('ix_chunks_doc_id', table_name='chunks')
    op.drop_table('chunks')
    
    op.drop_index('ix_documents_upload_date', table_name='documents')
    op.drop_index('ix_documents_filename', table_name='documents')
    op.drop_table('documents')
