import uuid
from typing import Optional, List
from sqlalchemy import select, desc, func, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.payment_attempt import PaymentAttemptModel, AttemptStatus


class PaymentAttemptRepository:

    @staticmethod
    async def create_attempt(
        session: AsyncSession,
        payment_id: int,
        method: str,
        provider: str,
        status: AttemptStatus = AttemptStatus.PENDING,
        provider_reference: Optional[str] = None,
        request_metadata: Optional[dict] = None,
        response_metadata: Optional[dict] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> PaymentAttemptModel:
        att_id = f"att_{uuid.uuid4().hex[:16]}"
        attempt = PaymentAttemptModel(
            attempt_id=att_id,
            payment_id=payment_id,
            method=method,
            provider=provider,
            status=status,
            provider_reference=provider_reference,
            error_code=error_code,
            error_message=error_message,
        )
        if request_metadata:
            attempt.request_metadata = request_metadata
        if response_metadata:
            attempt.response_metadata = response_metadata

        session.add(attempt)
        await session.flush()
        return attempt

    @staticmethod
    async def get_by_attempt_id(session: AsyncSession, attempt_id: str) -> Optional[PaymentAttemptModel]:
        stmt = (
            select(PaymentAttemptModel)
            .options(selectinload(PaymentAttemptModel.payment))
            .where(PaymentAttemptModel.attempt_id == str(attempt_id))
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def get_attempts_for_payment(session: AsyncSession, payment_id: int) -> List[PaymentAttemptModel]:
        stmt = (
            select(PaymentAttemptModel)
            .where(PaymentAttemptModel.payment_id == payment_id)
            .order_by(desc(PaymentAttemptModel.created_at))
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def get_latest_attempt(session: AsyncSession, payment_id: int) -> Optional[PaymentAttemptModel]:
        stmt = (
            select(PaymentAttemptModel)
            .where(PaymentAttemptModel.payment_id == payment_id)
            .order_by(desc(PaymentAttemptModel.id))
            .limit(1)
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    def _apply_attempt_filters(
        stmt,
        status: Optional[str] = None,
        provider: Optional[str] = None,
        method: Optional[str] = None,
        search: Optional[str] = None,
    ):
        if status:
            stmt = stmt.where(PaymentAttemptModel.status == status)
        if provider:
            stmt = stmt.where(PaymentAttemptModel.provider == provider)
        if method:
            stmt = stmt.where(PaymentAttemptModel.method == method)
        if search:
            term = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    PaymentAttemptModel.attempt_id.ilike(term),
                    PaymentAttemptModel.provider_reference.ilike(term),
                    PaymentAttemptModel.error_code.ilike(term),
                    PaymentAttemptModel.error_message.ilike(term),
                )
            )
        return stmt

    @staticmethod
    async def list_all_attempts(
        session: AsyncSession,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        provider: Optional[str] = None,
        method: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[PaymentAttemptModel]:
        stmt = (
            select(PaymentAttemptModel)
            .options(selectinload(PaymentAttemptModel.payment))
        )
        stmt = PaymentAttemptRepository._apply_attempt_filters(
            stmt, status=status, provider=provider, method=method, search=search
        )
        stmt = stmt.order_by(desc(PaymentAttemptModel.created_at)).offset(offset).limit(limit)
        res = await session.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def count_all_attempts(
        session: AsyncSession,
        status: Optional[str] = None,
        provider: Optional[str] = None,
        method: Optional[str] = None,
        search: Optional[str] = None,
    ) -> int:
        stmt = select(func.count(PaymentAttemptModel.id))
        stmt = PaymentAttemptRepository._apply_attempt_filters(
            stmt, status=status, provider=provider, method=method, search=search
        )
        res = await session.execute(stmt)
        return res.scalar() or 0
