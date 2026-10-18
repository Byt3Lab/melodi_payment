from typing import List, Dict, Any, Optional
from ..hooks.filters import PaymentFilters
from .payment_service_registry import PaymentServiceRegistry, resolve_payment_icon


class ProviderService:
    """
    Service de découverte et de résolution dynamique des providers et moyens de paiement.
    Intégré avec PaymentServiceRegistry pour contrôler l'activation/désactivation.
    """

    @staticmethod
    def _get_setting_repo(module_instance):
        """Récupère en toute sécurité le SettingRepository si disponible."""
        if not module_instance:
            return None
        try:
            from base.repositories.setting_repository import SettingRepository
            return SettingRepository(module_instance)
        except Exception:
            return None

    @classmethod
    async def sync_providers_from_filters(cls, module_instance) -> None:
        """
        Interroge les modules tiers via le filtre 'payment.providers'
        et synchronise automatiquement les descripteurs dans le PaymentServiceRegistry.
        """
        registry = PaymentServiceRegistry.get_instance(getattr(module_instance, "app", None))
        initial_providers: List[Dict[str, Any]] = []
        result = await PaymentFilters.apply_filter(
            module_instance,
            PaymentFilters.FILTER_PROVIDERS,
            initial_providers
        )
        if isinstance(result, list):
            for prov in result:
                if isinstance(prov, dict):
                    p_id = prov.get("provider_id") or prov.get("id")
                    if p_id:
                        registry.register_service({
                            "id": p_id,
                            "name": prov.get("name", p_id),
                            "description": prov.get("description", f"Passerelle {prov.get('name', p_id)}"),
                            "icon": prov.get("icon") or "payments",
                            "module": prov.get("module") or "melodi_payment",
                            "config_url": prov.get("config_url") or "",
                            "capabilities": prov.get("capabilities") or ["pay", "verify"],
                            "supported_currencies": prov.get("supported_currencies") or ["XAF", "EUR", "USD"],
                            "supported_methods": prov.get("supported_methods") or [],
                            "extra": prov.get("extra") or {}
                        })

    @classmethod
    async def get_registered_providers(cls, module_instance) -> List[Dict[str, Any]]:
        """
        Découvre tous les providers tiers enregistrés et retourne leurs descripteurs
        enrichis (avec statuts 'enabled', 'is_default', 'resolved_icon').
        """
        await cls.sync_providers_from_filters(module_instance)
        registry = PaymentServiceRegistry.get_instance(getattr(module_instance, "app", None))
        repo = cls._get_setting_repo(module_instance)
        enriched = await registry.list_services_enriched(repo)
        return [s.to_dict() for s in enriched]

    @classmethod
    async def get_available_methods(
        cls,
        module_instance,
        context: Optional[Dict[str, Any]] = None,
        only_active: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Récupère toutes les méthodes de paiement compatibles avec le contexte fourni
        (montant, devise, pays, payeur).
        Si only_active=True (par défaut), filtre STRICTEMENT pour ne renvoyer que les méthodes
        appartenant à des fournisseurs actuellement activés dans PaymentServiceRegistry.
        """
        context = context or {}
        await cls.sync_providers_from_filters(module_instance)

        registry = PaymentServiceRegistry.get_instance(getattr(module_instance, "app", None))
        repo = cls._get_setting_repo(module_instance)
        active_ids = set(await registry.get_active_service_ids(repo))

        payload = {
            "context": context,
            "methods": []
        }

        # 1. Collecte via le filtre 'payment.methods'
        result = await PaymentFilters.apply_filter(
            module_instance,
            PaymentFilters.FILTER_METHODS,
            payload
        )

        raw_methods = []
        if isinstance(result, dict) and "methods" in result:
            raw_methods = result.get("methods", [])
        elif isinstance(result, list):
            raw_methods = result

        # 2. Ajout des méthodes déclarées directement dans les descripteurs du registre
        for s in registry.list_services():
            if s.supported_methods:
                for sm in s.supported_methods:
                    if isinstance(sm, dict):
                        m_copy = dict(sm)
                        m_copy.setdefault("provider", s.id)
                        raw_methods.append(m_copy)
                    elif isinstance(sm, str):
                        raw_methods.append({
                            "method_id": sm,
                            "name": sm.replace("_", " ").title(),
                            "provider": s.id,
                            "supported_currencies": s.supported_currencies,
                            "capabilities": s.capabilities,
                        })

        # Dédoublonnage et filtrage par devise et par statut actif
        seen = set()
        valid_methods = []
        req_currency = (context.get("currency") or "").upper().strip()

        for m in raw_methods:
            m_id = m.get("method_id") or m.get("id")
            if not m_id or m_id in seen:
                continue

            provider_name = registry.normalize_id(m.get("provider", ""))

            # Si only_active est activé, vérifier que le fournisseur est actif
            if only_active:
                if provider_name and provider_name not in active_ids:
                    # Fournisseur désactivé -> méthode masquée
                    continue

            # Vérification de devise si spécifiée dans la méthode
            supp_currencies = m.get("supported_currencies")
            if req_currency and supp_currencies:
                supp_upper = [c.upper().strip() for c in supp_currencies]
                if req_currency not in supp_upper:
                    continue

            seen.add(m_id)
            icon_val = m.get("icon") or "payments"

            clean_method = {
                "method_id": m_id,
                "name": m.get("name", m_id),
                "description": m.get("description", ""),
                "icon": icon_val,
                "resolved_icon": resolve_payment_icon(icon_val),
                "provider": provider_name or m.get("provider", ""),
                "supported_currencies": m.get("supported_currencies", []),
                "capabilities": m.get("capabilities", ["pay"]),
                "is_active": (provider_name in active_ids),
            }
            valid_methods.append(clean_method)

        return valid_methods

    @classmethod
    async def resolve_provider_for_method(
        cls,
        module_instance,
        method_id: str,
        require_active: bool = True
    ) -> Optional[str]:
        """
        Résout le module provider responsable d'un moyen de paiement.
        Si require_active=True, vérifie également que le fournisseur est actif.
        """
        payload = {
            "method": method_id,
            "provider": None
        }

        result = await PaymentFilters.apply_filter(
            module_instance,
            PaymentFilters.FILTER_RESOLVE_PROVIDER,
            payload
        )

        resolved_prov = None
        if isinstance(result, dict) and result.get("provider"):
            resolved_prov = result.get("provider")

        # Résolution de secours en interrogeant get_available_methods
        if not resolved_prov:
            methods = await cls.get_available_methods(module_instance, {}, only_active=False)
            for m in methods:
                if m.get("method_id") == method_id and m.get("provider"):
                    resolved_prov = m.get("provider")
                    break

        if not resolved_prov:
            return None

        registry = PaymentServiceRegistry.get_instance(getattr(module_instance, "app", None))
        norm_prov = registry.normalize_id(resolved_prov)

        if require_active:
            repo = cls._get_setting_repo(module_instance)
            is_active = await registry.is_service_active(norm_prov, repo)
            if not is_active:
                return None

        return norm_prov
