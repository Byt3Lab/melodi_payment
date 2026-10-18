import uuid
from decimal import Decimal
from typing import Optional, List
from sqlalchemy import select, func, desc, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.refund import RefundModel, RefundStatus


class RefundRepository:

    @staticmethod
    async def create_refund(
        session: AsyncSession,
        payment_id: int,
        amount: Decimal,
        currency: str,
        status: RefundStatus = RefundStatus.PENDING,
        provider_reference: Optional[str] = None,
        reason: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> RefundModel:
        ref_id = f"ref_{uuid.uuid4().hex[:16]}"
        refund = RefundModel(
            refund_id=ref_id,
            payment_id=payment_id,
            amount=amount,
            currency=currency.upper().strip(),
            status=status,
            provider_reference=provider_reference,
            reason=reason,
        )
        if metadata:
            refund.metadata_dict = metadata

        session.add(refund)
        await session.flush()
        return refund

    @staticmethod
    async def get_by_refund_id(session: AsyncSession, refund_id: str) -> Optional[RefundModel]:
        stmt = (
            select(RefundModel)
            .options(selectinload(RefundModel.payment))
            .where(RefundModel.refund_id == str(refund_id))
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def get_refunds_for_payment(session: AsyncSession, payment_id: int) -> List[RefundModel]:
        stmt = (
            select(RefundModel)
            .where(RefundModel.payment_id == payment_id)
            .order_by(desc(RefundModel.created_at))
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def get_total_refunded(session: AsyncSession, payment_id: int) -> Decimal:
        stmt = (
            select(func.coalesce(func.sum(RefundModel.amount), 0))
            .where(
                RefundModel.payment_id == payment_id,
                RefundModel.status == RefundStatus.SUCCEEDED
            )
        )
        res = await session.execute(stmt)
        val = res.scalar()
        return Decimal(str(val)) if val is not None else Decimal("0.0000")

    @staticmethod
    def _apply_refund_filters(
        stmt,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ):
        if status:
            stmt = stmt.where(RefundModel.status == status)
        if search:
            term = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    RefundModel.refund_id.ilike(term),
                    RefundModel.provider_reference.ilike(term),
                    RefundModel.reason.ilike(term),
                )
            )
        return stmt

    @staticmethod
    async def list_all_refunds(
        session: AsyncSession,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[RefundModel]:
        stmt = (
            select(RefundModel)
            .options(selectinload(RefundModel.payment))
        )
        stmt = RefundRepository._apply_refund_filters(stmt, status=status, search=search)
        stmt = stmt.order_by(desc(RefundModel.created_at)).offset(offset).limit(limit)
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def count_all_refunds(
        session: AsyncSession,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> int:
        stmt = select(func.count(RefundModel.id))
        stmt = RefundRepository._apply_refund_filters(stmt, status=status, search=search)
        res = await session.execute(stmt)
        return res.scalar() or 0
