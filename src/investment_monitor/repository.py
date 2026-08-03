"""Storage contract for standardized information items."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, List, Optional, Protocol, runtime_checkable

from .models import InformationItem


@dataclass(frozen=True)
class SaveResult:
    """Counts describing one repository save operation."""

    inserted: int = 0
    updated: int = 0

    def __add__(self, other: "SaveResult") -> "SaveResult":
        return SaveResult(
            inserted=self.inserted + other.inserted,
            updated=self.updated + other.updated,
        )


@runtime_checkable
class InformationRepository(Protocol):
    """Database-independent storage operations used by the pipeline."""

    def save(self, items: Iterable[InformationItem]) -> SaveResult:
        """Insert new items and update records with the same identity."""
        ...

    def query(
        self,
        *,
        ticker: Optional[str] = None,
        source: Optional[str] = None,
        source_type: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[InformationItem]:
        """Find stored items using optional inclusive filters."""
        ...

