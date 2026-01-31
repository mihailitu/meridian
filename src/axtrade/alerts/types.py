"""Alert types and data structures."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def _utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


class AlertSeverity(Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertCategory(Enum):
    """Alert categories for grouping and filtering."""

    SYSTEM = "system"  # Infrastructure health
    TRADING = "trading"  # Order/position events
    RISK = "risk"  # Risk limit breaches
    DATA = "data"  # Data feed issues


@dataclass
class Alert:
    """Represents a system alert or notification."""

    severity: AlertSeverity
    category: AlertCategory
    title: str
    message: str
    source: str
    id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=_utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None

    def acknowledge(self, by: str = "user") -> None:
        """Mark alert as acknowledged."""
        self.acknowledged = True
        self.acknowledged_at = datetime.now(timezone.utc)
        self.acknowledged_by = by

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "severity": self.severity.value,
            "category": self.category.value,
            "title": self.title,
            "message": self.message,
            "source": self.source,
            "metadata": self.metadata,
            "acknowledged": self.acknowledged,
            "acknowledged_at": (
                self.acknowledged_at.isoformat() if self.acknowledged_at else None
            ),
            "acknowledged_by": self.acknowledged_by,
        }
