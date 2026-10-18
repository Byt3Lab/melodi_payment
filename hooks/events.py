from typing import Any, Dict


class PaymentEventPublisher:
    """Publication des événements métier standardisés du module de paiement."""

    # Événements Paiement
    EVENT_PAYMENT_CREATED = "payment.created"
    EVENT_PAYMENT_PROCESSING = "payment.processing"
    EVENT_PAYMENT_SUCCEEDED = "payment.succeeded"
    EVENT_PAYMENT_FAILED = "payment.failed"
    EVENT_PAYMENT_CANCELLED = "payment.cancelled"
    EVENT_PAYMENT_EXPIRED = "payment.expired"

    # Événements Remboursement
    EVENT_REFUND_CREATED = "payment.refund.created"
    EVENT_REFUNDED = "payment.refunded"
    EVENT_PARTIALLY_REFUNDED = "payment.partially_refunded"

    @classmethod
    async def publish(cls, module_instance, event_name: str, payload: Dict[str, Any]):
        """Publie un événement de manière non-bloquante via le bus HookManager du Core."""
        if module_instance and hasattr(module_instance, "notify_event_listener"):
            await module_instance.notify_event_listener(event_name, payload)
