"""
Structured logging with PII redaction using structlog.
"""

import logging
import re
import sys
from typing import Any

import structlog


def redact_pii(event_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Redact PII from log messages.
    
    Patterns redacted:
    - Names: Capitalized two-word patterns
    - Emails: Standard email format
    - Phone numbers: Various formats
    """
    message = event_dict.get("event", "")
    
    if isinstance(message, str):
        # Redact names (simple heuristic)
        message = re.sub(r'\b[A-Z][a-z]+ [A-Z][a-z]+\b', '[REDACTED_NAME]', message)
        
        # Redact emails
        message = re.sub(
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            '[REDACTED_EMAIL]',
            message,
        )
        
        # Redact phone numbers
        message = re.sub(
            r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[REDACTED_PHONE]', message
        )
        
        event_dict["event"] = message
    
    return event_dict


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structlog with PII redaction."""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            redact_pii,  # Custom PII redaction
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer()
            if log_level == "DEBUG"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure root logger
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )


# Initialize logging
from src.core.config import get_settings

setup_logging(get_settings().LOG_LEVEL)
logger = structlog.get_logger()
