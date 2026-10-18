import enum
import json
from datetime import datetime
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
    Enum,
    ForeignKey,
)

from ..config import PaymentTables

if TYPE_CHECKING:
    from .payment import PaymentModel


class AttemptStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class PaymentAttemptModel(BaseModel):
    __tablename__ = PaymentTables.PAYMENT_ATTEMPTS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    payment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{PaymentTables.PAYMENTS}.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    method: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    status: Mapped[AttemptStatus] = mapped_column(
        Enum(AttemptStatus, native_enum=False),
        default=AttemptStatus.PENDING,
        nullable=False,
        index=True
    )

    provider_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    request_metadata_raw: Mapped[Optional[str]] = mapped_column(SAText, nullable=True)
    response_metadata_raw: Mapped[Optional[str]] = mapped_column(SAText, nullable=True)

    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(SAText, nullable=True)

    created_at: Mapped[datetime] = mapped_column(SADateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(SADateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    payment: Mapped["PaymentModel"] = relationship(
        "PaymentModel",
        back_populates="attempts"
    )

    @property
    def request_metadata(self) -> Dict[str, Any]:
        if not self.request_metadata_raw:
            return {}
        try:
            return json.loads(self.request_metadata_raw)
        except Exception:
            return {}

    @request_metadata.setter
    def request_metadata(self, val: Dict[str, Any] | None):
        if val is None:
            self.request_metadata_raw = None
        else:
            self.request_metadata_raw = json.dumps(val, default=str)

    @property
    def response_metadata(self) -> Dict[str, Any]:
        if not self.response_metadata_raw:
            return {}
        try:
            return json.loads(self.response_metadata_raw)
        except Exception:
            return {}

    @response_metadata.setter
    def response_metadata(self, val: Dict[str, Any] | None):
        if val is None:
            self.response_metadata_raw = None
        else:
            self.response_metadata_raw = json.dumps(val, default=str)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "attempt_id": self.attempt_id,
            "payment_id": self.payment_id,
            "method": self.method,
            "provider": self.provider,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "provider_reference": self.provider_reference,
            "request_metadata": self.request_metadata,
            "response_metadata": self.response_metadata,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
