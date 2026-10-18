import enum
import json
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, TYPE_CHECKING

from sqlalchemy import (
    DateTime as SADateTime,
    Text as SAText,
)
from core.orm.model import (
    BaseModel,
    Mapped,
    mapped_column,
    relationship,
    Integer,
    String,
    Numeric,
    Enum,
    ForeignKey,
)

from ..config import PaymentTables

if TYPE_CHECKING:
    from .payment import PaymentModel


class RefundStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RefundModel(BaseModel):
    __tablename__ = PaymentTables.REFUNDS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    refund_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    payment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{PaymentTables.PAYMENTS}.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, index=True)

    status: Mapped[RefundStatus] = mapped_column(
        Enum(RefundStatus, native_enum=False),
        default=RefundStatus.PENDING,
        nullable=False,
        index=True
    )

    provider_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    reason: Mapped[Optional[str]] = mapped_column(SAText, nullable=True)
    metadata_raw: Mapped[Optional[str]] = mapped_column(SAText, nullable=True)

    created_at: Mapped[datetime] = mapped_column(SADateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(SADateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    payment: Mapped["PaymentModel"] = relationship(
        "PaymentModel",
        back_populates="refunds"
    )

    @property
    def metadata_dict(self) -> Dict[str, Any]:
        if not self.metadata_raw:
            return {}
        try:
            return json.loads(self.metadata_raw)
        except Exception:
            return {}

    @metadata_dict.setter
    def metadata_dict(self, val: Dict[str, Any] | None):
        if val is None:
            self.metadata_raw = None
        else:
            self.metadata_raw = json.dumps(val, default=str)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "refund_id": self.refund_id,
            "payment_id": self.payment_id,
            "amount": f"{self.amount:.4f}" if self.amount is not None else "0.0000",
            "amount_float": float(self.amount) if self.amount is not None else 0.0,
            "currency": self.currency,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "provider_reference": self.provider_reference,
            "reason": self.reason,
            "metadata": self.metadata_dict,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
