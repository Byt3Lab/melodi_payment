from decimal import Decimal
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.payment import PaymentModel, PaymentStatus
from ..models.refund import RefundModel, RefundStatus
from ..repositories.payment_repository import PaymentRepository
from ..repositories.refund_repository import RefundRepository
from ..hooks.events import PaymentEventPublisher
from ..hooks.filters import PaymentFilters


class RefundService:
    """Service de gestion des remboursements (complets et partiels) avec intégrité financière stricte."""

    @staticmethod
    async def process_refund(
        session: AsyncSession,
        payment_id: str | int,
        amount: Decimal | float | str,
        reason: Optional[str] = None,
        module_instance=None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Exécute un remboursement pour un paiement donné.
        Verrouille la ligne de paiement pour empêcher les opérations concurrentes.
        """
        # 1. Normalisation du montant demandé
        try:
            req_amount = Decimal(str(amount))
        except Exception:
            raise ValueError(f"Montant de remboursement invalide : {amount}")

        if req_amount <= Decimal("0"):
            raise ValueError("Le montant à rembourser doit être strictement supérieur à zéro.")

        # 2. Récupération avec verrouillage pessimiste
        if isinstance(payment_id, int):
            payment = await PaymentRepository.get_by_id(session, payment_id, lock=True)
        else:
            payment = await PaymentRepository.get_by_payment_id(session, str(payment_id), lock=True)

        if not payment:
            raise ValueError(f"Paiement #{payment_id} introuvable.")

        # 3. Vérification de l'état du paiement
        if payment.status not in (PaymentStatus.SUCCEEDED, PaymentStatus.PARTIALLY_REFUNDED):
            raise ValueError(
                f"Remboursement impossible : le paiement a le statut '{payment.status.value}', "
                f"seuls les paiements avec statut 'succeeded' ou 'partially_refunded' peuvent être remboursés."
            )

        # 4. Calcul du cumul des remboursements déjà validés
        total_already_refunded = await RefundRepository.get_total_refunded(session, payment.id)
        available_to_refund = payment.amount - total_already_refunded

        if req_amount > available_to_refund:
            raise ValueError(
                f"Montant de remboursement trop élevé : {req_amount} {payment.currency} demandé, "
                f"mais seulement {available_to_refund} {payment.currency} restant disponible pour ce paiement."
            )

        # 5. Application des filtres pré-remboursement
        refund_data = {
            "payment_id": payment.payment_id,
            "amount": str(req_amount),
            "currency": payment.currency,
            "reason": reason,
            "metadata": metadata or {},
        }
        filtered_data = await PaymentFilters.apply_filter(
            module_instance,
            PaymentFilters.FILTER_REFUND_DATA,
            refund_data
        )

        # 6. Appel éventuel du provider externe si configuré et disponible
        provider_reference = None
        if payment.provider and module_instance and hasattr(module_instance, "execute_action"):
            try:
                prov_res = await module_instance.execute_action(
                    payment.provider,
                    "refund_payment",
                    {
                        "payment_id": payment.payment_id,
                        "amount": str(req_amount),
                        "currency": payment.currency,
                        "provider_reference": payment.reference,
                        "reason": reason,
                        "metadata": metadata or {},
                    }
                )
                if isinstance(prov_res, dict):
                    if prov_res.get("status") == "failed":
                        err_msg = prov_res.get("error_message") or "Échec du remboursement chez le fournisseur."
                        raise ValueError(err_msg)
                    provider_reference = prov_res.get("provider_reference") or prov_res.get("reference")
            except Exception as e:
                # Si le module provider n'expose pas l'action ou si une erreur métier survient
                # On relance si c'est une erreur explicite de rejet
                if "non trouvée" not in str(e).lower():
                    raise e

        # 7. Création de l'enregistrement de remboursement en statut SUCCEEDED
        refund = await RefundRepository.create_refund(
            session=session,
            payment_id=payment.id,
            amount=req_amount,
            currency=payment.currency,
            status=RefundStatus.SUCCEEDED,
            provider_reference=provider_reference,
            reason=reason,
            metadata=metadata,
        )

        # 8. Mise à jour de l'état du paiement
        new_total_refunded = total_already_refunded + req_amount
        if new_total_refunded >= payment.amount:
            payment.status = PaymentStatus.REFUNDED
            event_to_publish = PaymentEventPublisher.EVENT_REFUNDED
        else:
            payment.status = PaymentStatus.PARTIALLY_REFUNDED
            event_to_publish = PaymentEventPublisher.EVENT_PARTIALLY_REFUNDED

        await session.flush()

        # 9. Émission des événements
        refund_dict = refund.to_dict()
        if module_instance:
            await PaymentEventPublisher.publish(
                module_instance,
                PaymentEventPublisher.EVENT_REFUND_CREATED,
                refund_dict
            )
            await PaymentEventPublisher.publish(
                module_instance,
                event_to_publish,
                {
                    "payment": payment.to_dict(),
                    "refund": refund_dict,
                    "total_refunded": str(new_total_refunded),
                    "remaining_balance": str(payment.amount - new_total_refunded),
                }
            )

        return {
            "status": "success",
            "payment_id": payment.payment_id,
            "payment_status": payment.status.value,
            "refund": refund_dict,
            "total_refunded": str(new_total_refunded),
            "remaining_balance": str(payment.amount - new_total_refunded),
        }
