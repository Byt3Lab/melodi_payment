import enum
import json
from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Index,
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


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class PaymentModel(BaseModel):
    __tablename__ = PaymentTables.PAYMENTS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payment_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    reference: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), unique=True, nullable=True, index=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, index=True)

    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False),
        default=PaymentStatus.PENDING,
        nullable=False,
        index=True
    )

    method: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    provider: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(SAText, nullable=True)

    # Référence logique vers le demandeur (commerce, retail, saas, etc.) sans Foreign Key physique
    source_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # Métadonnées et payeur stockés en JSON texte
    payer_raw: Mapped[Optional[str]] = mapped_column(SAText, nullable=True)
    metadata_raw: Mapped[Optional[str]] = mapped_column(SAText, nullable=True)

    created_at: Mapped[datetime] = mapped_column(SADateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(SADateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(SADateTime, nullable=True, index=True)

    # Relations au sein du même module
    attempts: Mapped[List["PaymentAttemptModel"]] = relationship(
        "PaymentAttemptModel",
        back_populates="payment",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="PaymentAttemptModel.id.asc()"
    )

    refunds: Mapped[List["RefundModel"]] = relationship(
        "RefundModel",
        back_populates="payment",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RefundModel.id.asc()"
    )

    @property
    def payer(self) -> Dict[str, Any]:
        if not self.payer_raw:
            return {}
        try:
            return json.loads(self.payer_raw)
        except Exception:
            return {}

    @payer.setter
    def payer(self, val: Dict[str, Any] | None):
        if val is None:
            self.payer_raw = None
        else:
            self.payer_raw = json.dumps(val, default=str)

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

    def to_dict(self, include_attempts: bool = False, include_refunds: bool = False) -> Dict[str, Any]:
        res = {
            "id": self.id,
            "payment_id": self.payment_id,
            "reference": self.reference,
            "idempotency_key": self.idempotency_key,
            "amount": f"{self.amount:.4f}" if self.amount is not None else "0.0000",
            "amount_float": float(self.amount) if self.amount is not None else 0.0,
            "currency": self.currency,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "method": self.method,
            "provider": self.provider,
            "description": self.description,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "payer": self.payer,
            "metadata": self.metadata_dict,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
        if include_attempts and self.attempts:
            res["attempts"] = [a.to_dict() for a in self.attempts]
        if include_refunds and self.refunds:
            res["refunds"] = [r.to_dict() for r in self.refunds]
        return res
