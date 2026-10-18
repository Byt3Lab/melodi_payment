from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core import Application
    from base.repositories.setting_repository import SettingRepository


REQUIRED_PAYMENT_PROVIDER_METHODS = ["process_payment", "verify_payment"]


def validate_payment_provider(provider: Any) -> tuple[bool, List[str]]:
    """
    Vérifie la conformité d'un objet provider direct avec les méthodes attendues.
    Retourne (is_valid, missing_methods).
    """
    if provider is None:
        return False, ["Le provider est None"]

    missing = []
    for method in REQUIRED_PAYMENT_PROVIDER_METHODS:
        attr = getattr(provider, method, None)
        if attr is None or not callable(attr):
            missing.append(method)

    return (len(missing) == 0, missing)


def resolve_payment_icon(icon: str | None) -> str:
    """
    Résout l'icône d'un service de paiement :
    - URL externe (http://, https://) ou chemin absolu/relatif (/static/...) -> conservé tel quel.
    - Nom d'icône système (ex: 'payments', 'credit_card', 'phone_android') -> converti en /static_base_icons?name=<icon>.
    """
    if not icon:
        return "/static_base_icons?name=payments&fill=%230d6efd"
    icon = icon.strip()
    if icon.startswith("http://") or icon.startswith("https://") or icon.startswith("/"):
        return icon
    return f"/static_base_icons?name={icon}"


@dataclass
class PaymentServiceDescriptor:
    id: str
    name: str
    description: str
    icon: str
    config_url: str
    module: str = "melodi_payment"
    enabled: bool = False
    is_default: bool = False
    capabilities: List[str] = field(default_factory=lambda: ["pay", "verify"])
    supported_currencies: List[str] = field(default_factory=lambda: ["XAF", "EUR", "USD"])
    supported_methods: List[Any] = field(default_factory=list)
    backend: Optional[Any] = None
    backend_type: str = "native"  # "native", "custom_instance", "custom_module"
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def resolved_icon(self) -> str:
        return resolve_payment_icon(self.icon)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "provider_id": self.id,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "resolved_icon": self.resolved_icon,
            "config_url": self.config_url,
            "module": self.module,
            "enabled": self.enabled,
            "is_default": self.is_default,
            "capabilities": self.capabilities,
            "supported_currencies": self.supported_currencies,
            "supported_methods": self.supported_methods,
            "backend_type": self.backend_type,
            "extra": self.extra,
        }


class PaymentServiceRegistry:
    """
    Registre central des services et fournisseurs de paiement pour MELODI.
    Inspiré de StorageServiceRegistry. Permet l'enregistrement programmatique dynamique
    de fournisseurs de paiement (Mobile Money, Stripe, PayPal, Wallet, modules tiers)
    via les actions et filtres de hooks, ainsi que l'activation/désactivation contrôlée.
    """

    _instance: Optional[PaymentServiceRegistry] = None

    def __init__(self, app: Application | None = None):
        self.app = app
        self._services: Dict[str, PaymentServiceDescriptor] = {}

    @classmethod
    def get_instance(cls, app: Application | None = None) -> PaymentServiceRegistry:
        if cls._instance is None:
            cls._instance = PaymentServiceRegistry(app)
        elif app and cls._instance.app is None:
            cls._instance.app = app
        return cls._instance

    @staticmethod
    def normalize_id(service_id: Any) -> str:
        if not service_id or not isinstance(service_id, str):
            return ""
        return service_id.strip().lower()

    def register_service(self, data: Dict[str, Any] | PaymentServiceDescriptor) -> PaymentServiceDescriptor:
        """
        Enregistre un nouveau fournisseur/service de paiement dans le registre.
        Accepte un dictionnaire ou un PaymentServiceDescriptor.
        """
        if isinstance(data, PaymentServiceDescriptor):
            norm_id = self.normalize_id(data.id)
            data.id = norm_id
            self._services[norm_id] = data
            return data

        raw_id = data.get("id") or data.get("provider_id") or data.get("code")
        if not raw_id:
            raise ValueError("L'identifiant du service de paiement ('id' ou 'provider_id') est obligatoire.")

        service_id = self.normalize_id(str(raw_id))
        title = data.get("name") or data.get("title") or service_id.replace("_", " ").title()
        desc = data.get("description") or f"Passerelle de paiement {title}"
        icon = data.get("icon") or "payments"
        module_name = data.get("module") or "melodi_payment"
        config_url = data.get("config_url") or f"/admin/{module_name}/settings"
        capabilities = data.get("capabilities") or ["pay", "verify"]
        supported_currencies = data.get("supported_currencies") or ["XAF", "EUR", "USD"]
        supported_methods = data.get("supported_methods") or []
        backend = data.get("backend")
        extra = data.get("extra") or {}

        if backend is not None:
            backend_type = "custom_instance"
            is_valid, missing = validate_payment_provider(backend)
            if not is_valid:
                extra["validation_error"] = f"Backend non conforme : méthodes manquantes : {', '.join(missing)}"
        elif module_name and module_name != "melodi_payment":
            backend_type = "custom_module"
        else:
            backend_type = "native"

        descriptor = PaymentServiceDescriptor(
            id=service_id,
            name=title,
            description=desc,
            icon=icon,
            config_url=config_url,
            module=module_name,
            capabilities=capabilities,
            supported_currencies=supported_currencies,
            supported_methods=supported_methods,
            backend=backend,
            backend_type=backend_type,
            extra=extra
        )

        self._services[service_id] = descriptor
        return descriptor

    def unregister_service(self, service_id: str) -> bool:
        """Désenregistre un service de paiement du registre."""
        norm_id = self.normalize_id(service_id)
        if norm_id in self._services:
            del self._services[norm_id]
            return True
        return False

    def get_service(self, service_id: str) -> Optional[PaymentServiceDescriptor]:
        norm_id = self.normalize_id(service_id)
        return self._services.get(norm_id)

    def list_services(self) -> List[PaymentServiceDescriptor]:
        return list(self._services.values())

    async def get_active_service_ids(self, repo: SettingRepository | None = None) -> List[str]:
        """
        Retourne la liste des identifiants de services de paiement actuellement activés.
        Si aucun paramètre n'a encore été configuré, tous les services enregistrés sont considérés comme actifs.
        """
        if repo:
            try:
                raw_active = await repo.get_setting("active_payment_services")
                if raw_active:
                    parsed = json.loads(raw_active)
                    if isinstance(parsed, list):
                        return [self.normalize_id(s) for s in parsed]
            except Exception:
                pass

        # Si non configuré, tous les services enregistrés sont activés par défaut
        return [s.id for s in self._services.values()]

    async def get_default_service_id(self, repo: SettingRepository | None = None) -> Optional[str]:
        """Retourne l'identifiant du service/fournisseur de paiement par défaut."""
        if repo:
            try:
                default_val = await repo.get_setting("default_payment_provider")
                if default_val:
                    norm = self.normalize_id(default_val)
                    if norm:
                        return norm
            except Exception:
                pass

        # Premier service enregistré par défaut si disponible
        all_services = self.list_services()
        return all_services[0].id if all_services else None

    async def list_services_enriched(self, repo: SettingRepository | None = None) -> List[PaymentServiceDescriptor]:
        """Retourne tous les services enregistrés enrichis de leur statut 'enabled' et 'is_default'."""
        active_ids = await self.get_active_service_ids(repo)
        default_id = await self.get_default_service_id(repo)

        enriched: List[PaymentServiceDescriptor] = []
        for s in self._services.values():
            s_copy = PaymentServiceDescriptor(
                id=s.id,
                name=s.name,
                description=s.description,
                icon=s.icon,
                config_url=s.config_url,
                module=s.module,
                enabled=(s.id in active_ids and not (s.extra and s.extra.get("validation_error"))),
                is_default=(s.id == default_id),
                capabilities=s.capabilities,
                supported_currencies=s.supported_currencies,
                supported_methods=s.supported_methods,
                backend=s.backend,
                backend_type=s.backend_type,
                extra=s.extra
            )
            enriched.append(s_copy)

        return enriched

    async def list_active_services(self, repo: SettingRepository | None = None) -> List[PaymentServiceDescriptor]:
        """Retourne uniquement les services activés et valides."""
        all_services = await self.list_services_enriched(repo)
        return [s for s in all_services if s.enabled]

    async def is_service_active(self, service_id: str, repo: SettingRepository | None = None) -> bool:
        """Vérifie si un service de paiement spécifique est actif."""
        norm_id = self.normalize_id(service_id)
        active_ids = await self.get_active_service_ids(repo)
        if norm_id not in active_ids:
            return False
        svc = self.get_service(norm_id)
        if svc and svc.extra and svc.extra.get("validation_error"):
            return False
        return True

    async def set_active_services(
        self,
        repo: SettingRepository,
        active_ids: List[str],
        default_id: Optional[str] = None
    ) -> None:
        """Enregistre la liste des services actifs et le service par défaut."""
        clean_active = [self.normalize_id(i) for i in active_ids if self.normalize_id(i)]
        if default_id:
            norm_default = self.normalize_id(default_id)
            if norm_default and norm_default not in clean_active:
                clean_active.append(norm_default)
            await repo.set_setting("default_payment_provider", norm_default)

        await repo.set_setting("active_payment_services", json.dumps(clean_active))

    async def toggle_service(self, repo: SettingRepository, service_id: str) -> bool:
        """Bascule l'état d'activation d'un service de paiement."""
        norm_id = self.normalize_id(service_id)
        if not norm_id:
            return False

        active_ids = await self.get_active_service_ids(repo)
        if norm_id in active_ids:
            active_ids.remove(norm_id)
            new_state = False
        else:
            active_ids.append(norm_id)
            new_state = True

        default_id = await self.get_default_service_id(repo)
        if default_id not in active_ids and active_ids:
            default_id = active_ids[0]

        await self.set_active_services(repo, active_ids, default_id)
        return new_state

    async def set_default_service(self, repo: SettingRepository, service_id: str) -> None:
        """Définit le service de paiement par défaut."""
        norm_id = self.normalize_id(service_id)
        if not norm_id:
            return

        active_ids = await self.get_active_service_ids(repo)
        if norm_id not in active_ids:
            active_ids.append(norm_id)

        await self.set_active_services(repo, active_ids, norm_id)
