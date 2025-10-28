"""
Health check and metrics endpoints.
"""

from datetime import datetime

from fastapi import APIRouter

from src.core.config import get_settings
from src.models.schemas import HealthResponse, MetricsResponse

router = APIRouter()

# In-memory metrics counters (use Redis/Prometheus in production)
_metrics = {
    "ingests_total": 0,
    "extractions_total": 0,
    "qa_requests_total": 0,
    "audits_total": 0,
}


@router.get("/healthz", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    settings = get_settings()
    return HealthResponse(
        status="ok", timestamp=datetime.utcnow(), version=settings.API_VERSION
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics():
    """Prometheus-compatible metrics endpoint."""
    return MetricsResponse(**_metrics)


def increment_metric(metric_name: str) -> None:
    """Helper to increment metric counters."""
    if metric_name in _metrics:
        _metrics[metric_name] += 1
