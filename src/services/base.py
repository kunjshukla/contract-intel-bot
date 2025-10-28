"""
Abstract base service class for dependency injection pattern.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseService(ABC):
    """Abstract base class for all services."""

    @abstractmethod
    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        """Execute service logic."""
        pass
