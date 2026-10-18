from typing import Any, Dict, List


class PaymentFilters:
    """Gestion des filtres d'extension pour les providers et pipelines de paiement."""

    FILTER_PROVIDERS = "payment.providers"
    FILTER_METHODS = "payment.methods"
    FILTER_RESOLVE_PROVIDER = "payment.resolve_provider"
    FILTER_CREATE_DATA = "payment.create.data"
    FILTER_PROCESS_DATA = "payment.process.data"
    FILTER_REFUND_DATA = "payment.refund.data"
    FILTER_RESULT = "payment.result"

    @classmethod
    async def apply_filter(cls, module_instance, filter_name: str, payload: Any = None) -> Any:
        """Exécute un filtre via le module instance si disponible."""
        if module_instance and hasattr(module_instance, "execute_filter"):
            return await module_instance.execute_filter(filter_name, payload)
        return payload
