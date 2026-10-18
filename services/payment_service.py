from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import DEFAULT_EXPIRATION_MINUTES, DEFAULT_CURRENCY
from ..models.payment import PaymentModel, PaymentStatus
from ..models.payment_attempt import PaymentAttemptModel, AttemptStatus
from ..repositories.payment_repository import PaymentRepository
from ..repositories.payment_attempt_repository import PaymentAttemptRepository
from ..services.provider_service import ProviderService
from ..hooks.events import PaymentEventPublisher
from ..hooks.filters import PaymentFilters


class PaymentService:
    """Service central orchestrant le cycle de vie des paiements et la machine d'états finis."""

    @staticmethod
    async def create_payment(
        session: AsyncSession,
        amount: Decimal | float | str,
        currency: Optional[str] = None,
        reference: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        description: Optional[str] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        payer: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        expiration_minutes: Optional[int] = None,
        module_instance=None,
    ) -> Dict[str, Any]:
        """
        Crée une nouvelle demande de paiement avec vérification d'idempotence
        et initialisation au statut 'pending'.
        """
        # 1. Vérification d'idempotence
        if idempotency_key:
            existing = await PaymentRepository.get_by_idempotency_key(session, idempotency_key)
            if existing:
                return {
                    "is_idempotent": True,
                    "payment": existing.to_dict(include_attempts=True, include_refunds=True)
                }

        # 2. Validation du montant et de la devise
        try:
            dec_amount = Decimal(str(amount))
        except Exception:
            raise ValueError(f"Montant invalide : {amount}")

        if dec_amount <= Decimal("0"):
            raise ValueError("Le montant du paiement doit être strictement supérieur à zéro.")

        curr = (currency or DEFAULT_CURRENCY).upper().strip()

        # 3. Calcul de la date d'expiration
        exp_min = expiration_minutes if expiration_minutes is not None else DEFAULT_EXPIRATION_MINUTES
        expires_at = datetime.utcnow() + timedelta(minutes=exp_min) if exp_min > 0 else None

        # 4. Filtre d'enrichissement des données avant création
        create_payload = {
            "amount": str(dec_amount),
            "currency": curr,
            "reference": reference,
            "idempotency_key": idempotency_key,
            "description": description,
            "source_type": source_type,
            "source_id": source_id,
            "payer": payer or {},
            "metadata": metadata or {},
            "expires_at": expires_at.isoformat() if expires_at else None,
        }
        filtered_payload = await PaymentFilters.apply_filter(
            module_instance,
            PaymentFilters.FILTER_CREATE_DATA,
            create_payload
        )

        # 5. Création en base
        payment = await PaymentRepository.create_payment(
            session=session,
            amount=dec_amount,
            currency=curr,
            reference=filtered_payload.get("reference") or reference,
            idempotency_key=idempotency_key,
            description=filtered_payload.get("description") or description,
            source_type=source_type,
            source_id=source_id,
            payer=filtered_payload.get("payer") or payer,
            metadata=filtered_payload.get("metadata") or metadata,
            expires_at=expires_at,
        )

        await session.flush()
        payment_dict = payment.to_dict()

        # 6. Émission de l'événement
        if module_instance:
            await PaymentEventPublisher.publish(
                module_instance,
                PaymentEventPublisher.EVENT_PAYMENT_CREATED,
                payment_dict
            )

        return {
            "is_idempotent": False,
            "payment": payment_dict
        }

    @staticmethod
    async def process_payment(
        session: AsyncSession,
        payment_id: str | int,
        method: str,
        module_instance=None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Déclenche l'exécution d'une tentative de paiement via le moyen spécifié.
        Verrouille la ligne de paiement (`lock=True`) pour garantir la cohérence d'état.
        """
        context = context or {}

        # 1. Verrouillage pessimiste de la ressource
        if isinstance(payment_id, int):
            payment = await PaymentRepository.get_by_id(session, payment_id, lock=True)
        else:
            payment = await PaymentRepository.get_by_payment_id(session, str(payment_id), lock=True)

        if not payment:
            raise ValueError(f"Paiement #{payment_id} introuvable.")

        # 2. Vérification de l'expiration
        if payment.expires_at and payment.expires_at < datetime.utcnow():
            payment.status = PaymentStatus.EXPIRED
            await session.flush()
            if module_instance:
                await PaymentEventPublisher.publish(
                    module_instance,
                    PaymentEventPublisher.EVENT_PAYMENT_EXPIRED,
                    payment.to_dict()
                )
            raise ValueError(f"Le paiement #{payment.payment_id} a expiré.")

        # 3. Validation de la machine d'état
        # On autorise le processing depuis 'pending' ou 'failed' (nouvelle tentative autorisée)
        if payment.status not in (PaymentStatus.PENDING, PaymentStatus.FAILED):
            raise ValueError(
                f"Action impossible : le paiement a déjà le statut '{payment.status.value}'."
            )

        # 4. Résolution dynamique du provider pour cette méthode et contrôle d'activation
        raw_provider = await ProviderService.resolve_provider_for_method(module_instance, method, require_active=False)
        if not raw_provider:
            raise ValueError(
                f"Aucun fournisseur actif n'est capable de traiter le moyen de paiement '{method}'."
            )

        provider = await ProviderService.resolve_provider_for_method(module_instance, method, require_active=True)
        if not provider:
            raise ValueError(
                f"Le fournisseur de paiement '{raw_provider}' associé à la méthode '{method}' est actuellement désactivé par l'administrateur."
            )

        # 5. Transition vers 'processing'
        payment.status = PaymentStatus.PROCESSING
        payment.method = method
        payment.provider = provider
        await session.flush()

        if module_instance:
            await PaymentEventPublisher.publish(
                module_instance,
                PaymentEventPublisher.EVENT_PAYMENT_PROCESSING,
                payment.to_dict()
            )

        # 6. Création de la tentative de paiement
        attempt = await PaymentAttemptRepository.create_attempt(
            session=session,
            payment_id=payment.id,
            method=method,
            provider=provider,
            status=AttemptStatus.PROCESSING,
            request_metadata={
                "payer": payment.payer,
                "context": context,
            }
        )

        # 7. Préparation du payload et application des filtres de processing
        attempt_payload = {
            "payment_id": payment.payment_id,
            "attempt_id": attempt.attempt_id,
            "reference": payment.reference,
            "amount": str(payment.amount),
            "currency": payment.currency,
            "method": method,
            "payer": payment.payer,
            "description": payment.description,
            "metadata": payment.metadata_dict,
            "context": context,
        }
        filtered_payload = await PaymentFilters.apply_filter(
            module_instance,
            PaymentFilters.FILTER_PROCESS_DATA,
            attempt_payload
        )

        # 8. Appel de l'action du provider tiers via le HookManager
        provider_res = {}
        try:
            if module_instance and hasattr(module_instance, "execute_action"):
                provider_res = await module_instance.execute_action(
                    provider,
                    "process_payment",
                    filtered_payload
                )
            else:
                raise ValueError("Instance du module indisponible pour exécuter l'action provider.")
        except Exception as e:
            # Échec lors de la communication avec le provider
            attempt.status = AttemptStatus.FAILED
            attempt.error_code = "PROVIDER_INVOCATION_ERROR"
            attempt.error_message = str(e)
            payment.status = PaymentStatus.FAILED
            await session.flush()

            if module_instance:
                await PaymentEventPublisher.publish(
                    module_instance,
                    PaymentEventPublisher.EVENT_PAYMENT_FAILED,
                    payment.to_dict()
                )
            return {
                "status": "failed",
                "payment_id": payment.payment_id,
                "attempt_id": attempt.attempt_id,
                "error": str(e),
                "payment": payment.to_dict(),
            }

        # 9. Traitement du résultat retourné par le provider
        prov_status = (provider_res.get("status") or "failed").lower()
        attempt.provider_reference = provider_res.get("provider_reference")
        attempt.response_metadata = provider_res.get("response_metadata") or provider_res

        if prov_status == "succeeded":
            attempt.status = AttemptStatus.SUCCEEDED
            payment.status = PaymentStatus.SUCCEEDED
            await session.flush()

            if module_instance:
                await PaymentEventPublisher.publish(
                    module_instance,
                    PaymentEventPublisher.EVENT_PAYMENT_SUCCEEDED,
                    payment.to_dict()
                )
        elif prov_status == "processing":
            attempt.status = AttemptStatus.PROCESSING
            payment.status = PaymentStatus.PROCESSING
            await session.flush()
        else:
            attempt.status = AttemptStatus.FAILED
            attempt.error_code = provider_res.get("error_code") or "PROVIDER_ERROR"
            attempt.error_message = provider_res.get("error_message") or "Échec de la transaction."
            payment.status = PaymentStatus.FAILED
            await session.flush()

            if module_instance:
                await PaymentEventPublisher.publish(
                    module_instance,
                    PaymentEventPublisher.EVENT_PAYMENT_FAILED,
                    payment.to_dict()
                )

        return {
            "status": payment.status.value,
            "payment_id": payment.payment_id,
            "attempt_id": attempt.attempt_id,
            "provider_reference": attempt.provider_reference,
            "payment": payment.to_dict(include_attempts=True),
        }

    @staticmethod
    async def verify_payment(
        session: AsyncSession,
        payment_id: str | int,
        module_instance=None,
    ) -> Dict[str, Any]:
        """
        Vérifie le statut d'un paiement en cours auprès de son fournisseur.
        """
        if isinstance(payment_id, int):
            payment = await PaymentRepository.get_by_id(session, payment_id, lock=True)
        else:
            payment = await PaymentRepository.get_by_payment_id(session, str(payment_id), lock=True)

        if not payment:
            raise ValueError(f"Paiement #{payment_id} introuvable.")

        # Si le paiement est déjà dans un état terminal (succeeded, refunded, cancelled)
        if payment.status in (PaymentStatus.SUCCEEDED, PaymentStatus.REFUNDED, PaymentStatus.CANCELLED):
            return {
                "payment_id": payment.payment_id,
                "status": payment.status.value,
                "verified": True,
                "payment": payment.to_dict(include_attempts=True),
            }

        latest_attempt = await PaymentAttemptRepository.get_latest_attempt(session, payment.id)
        if not latest_attempt or not latest_attempt.provider:
            return {
                "payment_id": payment.payment_id,
                "status": payment.status.value,
                "verified": False,
                "message": "Aucune tentative de paiement à vérifier.",
                "payment": payment.to_dict(include_attempts=True),
            }

        # Interrogation du provider
        verify_payload = {
            "payment_id": payment.payment_id,
            "attempt_id": latest_attempt.attempt_id,
            "provider_reference": latest_attempt.provider_reference,
            "reference": payment.reference,
        }

        try:
            res = await module_instance.execute_action(
                latest_attempt.provider,
                "verify_payment",
                verify_payload
            )
            v_status = (res.get("status") or "").lower()

            if v_status == "succeeded" and payment.status != PaymentStatus.SUCCEEDED:
                latest_attempt.status = AttemptStatus.SUCCEEDED
                payment.status = PaymentStatus.SUCCEEDED
                await session.flush()
                await PaymentEventPublisher.publish(
                    module_instance,
                    PaymentEventPublisher.EVENT_PAYMENT_SUCCEEDED,
                    payment.to_dict()
                )
            elif v_status == "failed" and payment.status != PaymentStatus.FAILED:
                latest_attempt.status = AttemptStatus.FAILED
                latest_attempt.error_message = res.get("error_message")
                payment.status = PaymentStatus.FAILED
                await session.flush()
                await PaymentEventPublisher.publish(
                    module_instance,
                    PaymentEventPublisher.EVENT_PAYMENT_FAILED,
                    payment.to_dict()
                )
        except Exception as e:
            return {
                "payment_id": payment.payment_id,
                "status": payment.status.value,
                "verified": False,
                "error": str(e),
                "payment": payment.to_dict(include_attempts=True),
            }

        return {
            "payment_id": payment.payment_id,
            "status": payment.status.value,
            "verified": True,
            "payment": payment.to_dict(include_attempts=True),
        }

    @staticmethod
    async def cancel_payment(
        session: AsyncSession,
        payment_id: str | int,
        reason: Optional[str] = None,
        module_instance=None,
    ) -> Dict[str, Any]:
        """
        Annule une demande de paiement si son état actuel l'autorise (uniquement 'pending').
        """
        if isinstance(payment_id, int):
            payment = await PaymentRepository.get_by_id(session, payment_id, lock=True)
        else:
            payment = await PaymentRepository.get_by_payment_id(session, str(payment_id), lock=True)

        if not payment:
            raise ValueError(f"Paiement #{payment_id} introuvable.")

        if payment.status != PaymentStatus.PENDING:
            raise ValueError(
                f"Impossible d'annuler : le paiement a le statut '{payment.status.value}'. "
                f"Seuls les paiements en attente ('pending') peuvent être annulés."
            )

        payment.status = PaymentStatus.CANCELLED
        await session.flush()

        if module_instance:
            await PaymentEventPublisher.publish(
                module_instance,
                PaymentEventPublisher.EVENT_PAYMENT_CANCELLED,
                payment.to_dict()
            )

        return {
            "status": "success",
            "payment_id": payment.payment_id,
            "payment_status": payment.status.value,
            "reason": reason,
        }

    @staticmethod
    async def get_payment(
        session: AsyncSession,
        payment_id: str | int,
        include_attempts: bool = True,
        include_refunds: bool = True,
    ) -> Optional[Dict[str, Any]]:
        if isinstance(payment_id, int):
            payment = await PaymentRepository.get_by_id(session, payment_id)
        else:
            payment = await PaymentRepository.get_by_payment_id(session, str(payment_id))

        if not payment:
            return None
        return payment.to_dict(include_attempts=include_attempts, include_refunds=include_refunds)

    @staticmethod
    async def list_payments(
        session: AsyncSession,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        items = await PaymentRepository.list_payments(
            session=session,
            limit=limit,
            offset=offset,
            status=status,
            source_type=source_type,
            source_id=source_id,
        )
        total = await PaymentRepository.count_payments(
            session=session,
            status=status,
            source_type=source_type,
            source_id=source_id,
        )
        return {
            "total": total,
            "count": len(items),
            "limit": limit,
            "offset": offset,
            "payments": [p.to_dict() for p in items],
        }
