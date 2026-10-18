import uuid
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Optional, List, Dict, Any
from sqlalchemy import select, func, desc, asc, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.payment import PaymentModel, PaymentStatus
from ..models.refund import RefundModel, RefundStatus


class PaymentRepository:

    @staticmethod
    async def get_by_id(session: AsyncSession, payment_db_id: int, lock: bool = False) -> Optional[PaymentModel]:
        stmt = select(PaymentModel).where(PaymentModel.id == payment_db_id)
        if lock:
            stmt = stmt.with_for_update()
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def get_by_payment_id(session: AsyncSession, payment_id: str, lock: bool = False) -> Optional[PaymentModel]:
        stmt = select(PaymentModel).where(PaymentModel.payment_id == str(payment_id))
        if lock:
            stmt = stmt.with_for_update()
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def get_by_reference(session: AsyncSession, reference: str, lock: bool = False) -> Optional[PaymentModel]:
        stmt = select(PaymentModel).where(PaymentModel.reference == str(reference))
        if lock:
            stmt = stmt.with_for_update()
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def get_by_idempotency_key(session: AsyncSession, idempotency_key: str) -> Optional[PaymentModel]:
        if not idempotency_key:
            return None
        stmt = select(PaymentModel).where(PaymentModel.idempotency_key == str(idempotency_key))
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def create_payment(
        session: AsyncSession,
        amount: Decimal,
        currency: str,
        reference: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        method: Optional[str] = None,
        provider: Optional[str] = None,
        description: Optional[str] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        payer: Optional[dict] = None,
        metadata: Optional[dict] = None,
        expires_at: Optional[datetime] = None,
    ) -> PaymentModel:
        p_id = f"pay_{uuid.uuid4().hex[:16]}"
        now = datetime.utcnow()
        ref = reference or f"PAY-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        payment = PaymentModel(
            payment_id=p_id,
            reference=ref,
            idempotency_key=idempotency_key,
            amount=amount,
            currency=currency.upper().strip(),
            status=PaymentStatus.PENDING,
            method=method,
            provider=provider,
            description=description,
            source_type=source_type,
            source_id=str(source_id) if source_id is not None else None,
            expires_at=expires_at,
        )
        if payer:
            payment.payer = payer
        if metadata:
            payment.metadata_dict = metadata

        session.add(payment)
        await session.flush()
        return payment

    @staticmethod
    def _apply_filters(
        stmt,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        method: Optional[str] = None,
        provider: Optional[str] = None,
        currency: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        search: Optional[str] = None,
    ):
        if status:
            stmt = stmt.where(PaymentModel.status == status)
        if source_type:
            stmt = stmt.where(PaymentModel.source_type == source_type)
        if source_id:
            stmt = stmt.where(PaymentModel.source_id == str(source_id))
        if method:
            stmt = stmt.where(PaymentModel.method == method)
        if provider:
            stmt = stmt.where(PaymentModel.provider == provider)
        if currency:
            stmt = stmt.where(PaymentModel.currency == currency.upper().strip())
        if date_from:
            stmt = stmt.where(PaymentModel.created_at >= date_from)
        if date_to:
            stmt = stmt.where(PaymentModel.created_at <= date_to)
        if search:
            term = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    PaymentModel.reference.ilike(term),
                    PaymentModel.payment_id.ilike(term),
                    PaymentModel.description.ilike(term),
                    PaymentModel.source_id.ilike(term),
                    PaymentModel.payer_raw.ilike(term),
                )
            )
        return stmt

    @staticmethod
    async def list_payments(
        session: AsyncSession,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        method: Optional[str] = None,
        provider: Optional[str] = None,
        currency: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        search: Optional[str] = None,
        order_by: str = "created_at",
        order_dir: str = "desc",
    ) -> List[PaymentModel]:
        stmt = select(PaymentModel)
        stmt = PaymentRepository._apply_filters(
            stmt,
            status=status,
            source_type=source_type,
            source_id=source_id,
            method=method,
            provider=provider,
            currency=currency,
            date_from=date_from,
            date_to=date_to,
            search=search,
        )

        col = getattr(PaymentModel, order_by, PaymentModel.created_at)
        sort_fn = desc if order_dir.lower() == "desc" else asc
        stmt = stmt.order_by(sort_fn(col)).offset(offset).limit(limit)

        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def count_payments(
        session: AsyncSession,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        method: Optional[str] = None,
        provider: Optional[str] = None,
        currency: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        search: Optional[str] = None,
    ) -> int:
        stmt = select(func.count(PaymentModel.id))
        stmt = PaymentRepository._apply_filters(
            stmt,
            status=status,
            source_type=source_type,
            source_id=source_id,
            method=method,
            provider=provider,
            currency=currency,
            date_from=date_from,
            date_to=date_to,
            search=search,
        )

        res = await session.execute(stmt)
        return res.scalar() or 0

    @staticmethod
    async def get_dashboard_stats(session: AsyncSession) -> Dict[str, Any]:
        """Calcule des statistiques réelles et agrégées pour le tableau de bord des paiements."""
        now = datetime.utcnow()
        start_of_today = datetime(now.year, now.month, now.day)

        # 1. Tous les paiements récents pour agrégations
        stmt_all = select(PaymentModel)
        res_all = await session.execute(stmt_all)
        payments: List[PaymentModel] = list(res_all.scalars().all())

        total_count = len(payments)
        total_volume = Decimal("0.0000")
        succeeded_volume = Decimal("0.0000")

        today_count = 0
        today_volume = Decimal("0.0000")

        by_status: Dict[str, int] = {}
        by_method: Dict[str, int] = {}
        by_provider: Dict[str, int] = {}
        by_currency: Dict[str, Decimal] = {}

        for p in payments:
            st = p.status.value if hasattr(p.status, "value") else str(p.status)
            by_status[st] = by_status.get(st, 0) + 1

            amt = p.amount or Decimal("0.0000")
            total_volume += amt

            if st == "succeeded":
                succeeded_volume += amt

            if p.created_at and p.created_at >= start_of_today:
                today_count += 1
                today_volume += amt

            if p.method:
                by_method[p.method] = by_method.get(p.method, 0) + 1
            if p.provider:
                by_provider[p.provider] = by_provider.get(p.provider, 0) + 1
            if p.currency:
                by_currency[p.currency] = by_currency.get(p.currency, Decimal("0.0000")) + amt

        # 2. Total des remboursements
        stmt_ref = select(func.coalesce(func.sum(RefundModel.amount), 0)).where(
            RefundModel.status == RefundStatus.SUCCEEDED
        )
        res_ref = await session.execute(stmt_ref)
        total_refunded = Decimal(str(res_ref.scalar() or 0))

        # 3. Évolution sur les 7 derniers jours (données réelles)
        recent_days = []
        for i in range(6, -1, -1):
            day_date = (now - timedelta(days=i)).date()
            day_count = sum(1 for p in payments if p.created_at and p.created_at.date() == day_date)
            day_volume = sum(
                float(p.amount) for p in payments
                if p.created_at and p.created_at.date() == day_date and (p.status.value if hasattr(p.status, "value") else str(p.status)) == "succeeded"
            )
            recent_days.append({
                "date": day_date.strftime("%d/%m"),
                "count": day_count,
                "volume": day_volume,
            })

        return {
            "total_count": total_count,
            "total_volume": float(total_volume),
            "succeeded_count": by_status.get("succeeded", 0),
            "succeeded_volume": float(succeeded_volume),
            "pending_count": by_status.get("pending", 0) + by_status.get("processing", 0),
            "failed_count": by_status.get("failed", 0) + by_status.get("cancelled", 0) + by_status.get("expired", 0),
            "refunded_count": by_status.get("refunded", 0) + by_status.get("partially_refunded", 0),
            "total_refunded_volume": float(total_refunded),
            "today_count": today_count,
            "today_volume": float(today_volume),
            "by_status": by_status,
            "by_method": by_method,
            "by_provider": by_provider,
            "by_currency": {k: float(v) for k, v in by_currency.items()},
            "recent_days": recent_days,
        }
