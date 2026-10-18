from typing import Dict, Any


class PaymentActions:
    """Implémentation des actions publiques exposées par melodi_payment aux autres modules."""

    def __init__(self, module):
        self.module = module

    def register_all(self):
        """Enregistre les actions publiques auprès du HookManager."""
        actions = [
            ("payment.create", self.action_create_payment),
            ("payment.process", self.action_process_payment),
            ("payment.verify", self.action_verify_payment),
            ("payment.cancel", self.action_cancel_payment),
            ("payment.refund", self.action_refund_payment),
            ("payment.get", self.action_get_payment),
            ("payment.get_methods", self.action_get_methods),
            ("payment.list_providers", self.action_list_providers),
            ("payment.register_service", self.action_register_service),
            ("payment.unregister_service", self.action_unregister_service),
            ("payment.list_services", self.action_list_services),
        ]
        for name, handler in actions:
            self.module.add_action(name, handler)
            # Alias sans préfixe pour flexibilité
            short_name = name.split(".")[-1]
            if short_name != name:
                self.module.add_action(short_name, handler)
        # Alias supplémentaires compatibles avec le pattern storage
        self.module.add_action("register_payment_service", self.action_register_service)
        self.module.add_action("unregister_payment_service", self.action_unregister_service)

    async def action_create_payment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Action: payment.create
        Payload: {amount, currency, reference, description, source_type, source_id, payer, metadata, idempotency_key, expiration_minutes}
        """
        from ..services.payment_service import PaymentService
        async with self.module.app.db.get_session() as session:
            res = await PaymentService.create_payment(
                session=session,
                amount=payload.get("amount"),
                currency=payload.get("currency"),
                reference=payload.get("reference"),
                idempotency_key=payload.get("idempotency_key"),
                description=payload.get("description"),
                source_type=payload.get("source_type"),
                source_id=payload.get("source_id"),
                payer=payload.get("payer"),
                metadata=payload.get("metadata"),
                expiration_minutes=payload.get("expiration_minutes"),
                module_instance=self.module,
            )
            await session.commit()
            return res

    async def action_process_payment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Action: payment.process
        Payload: {payment_id, method, context}
        """
        from ..services.payment_service import PaymentService
        payment_id = payload.get("payment_id")
        method = payload.get("method")
        context = payload.get("context") or {}

        if not payment_id or not method:
            raise ValueError("Les paramètres 'payment_id' et 'method' sont obligatoires.")

        async with self.module.app.db.get_session() as session:
            res = await PaymentService.process_payment(
                session=session,
                payment_id=payment_id,
                method=method,
                module_instance=self.module,
                context=context,
            )
            await session.commit()
            return res

    async def action_verify_payment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Action: payment.verify
        Payload: {payment_id}
        """
        from ..services.payment_service import PaymentService
        payment_id = payload.get("payment_id")
        if not payment_id:
            raise ValueError("Le paramètre 'payment_id' est obligatoire.")

        async with self.module.app.db.get_session() as session:
            res = await PaymentService.verify_payment(
                session=session,
                payment_id=payment_id,
                module_instance=self.module,
            )
            await session.commit()
            return res

    async def action_cancel_payment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Action: payment.cancel
        Payload: {payment_id, reason}
        """
        from ..services.payment_service import PaymentService
        payment_id = payload.get("payment_id")
        reason = payload.get("reason")
        if not payment_id:
            raise ValueError("Le paramètre 'payment_id' est obligatoire.")

        async with self.module.app.db.get_session() as session:
            res = await PaymentService.cancel_payment(
                session=session,
                payment_id=payment_id,
                reason=reason,
                module_instance=self.module,
            )
            await session.commit()
            return res

    async def action_refund_payment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Action: payment.refund
        Payload: {payment_id, amount, reason, metadata}
        """
        from ..services.refund_service import RefundService
        payment_id = payload.get("payment_id")
        amount = payload.get("amount")
        reason = payload.get("reason")
        metadata = payload.get("metadata")

        if not payment_id or amount is None:
            raise ValueError("Les paramètres 'payment_id' et 'amount' sont obligatoires.")

        async with self.module.app.db.get_session() as session:
            res = await RefundService.process_refund(
                session=session,
                payment_id=payment_id,
                amount=amount,
                reason=reason,
                module_instance=self.module,
                metadata=metadata,
            )
            await session.commit()
            return res

    async def action_get_payment(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Action: payment.get
        Payload: {payment_id}
        """
        from ..services.payment_service import PaymentService
        payment_id = payload.get("payment_id")
        if not payment_id:
            raise ValueError("Le paramètre 'payment_id' est obligatoire.")

        async with self.module.app.db.get_session() as session:
            res = await PaymentService.get_payment(
                session=session,
                payment_id=payment_id,
                include_attempts=True,
                include_refunds=True,
            )
            if not res:
                raise ValueError(f"Paiement #{payment_id} introuvable.")
            return res

    async def action_get_methods(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Action: payment.get_methods
        Payload: {amount, currency, country, payer}
        """
        from ..services.provider_service import ProviderService
        methods = await ProviderService.get_available_methods(
            module_instance=self.module,
            context=payload or {}
        )
        return {"methods": methods}

    async def action_list_providers(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Action: payment.list_providers
        """
        from ..services.provider_service import ProviderService
        providers = await ProviderService.get_registered_providers(module_instance=self.module)
        return {"providers": providers}

    async def action_register_service(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Action: payment.register_service / register_payment_service
        Permet à un module tiers d'enregistrer un service/passerelle de paiement de manière 100% découplée.
        Payload: {id/provider_id, name, description, icon, config_url, module, capabilities, supported_currencies, supported_methods, ...}
        """
        from ..services.payment_service_registry import PaymentServiceRegistry
        registry = PaymentServiceRegistry.get_instance(getattr(self.module, "app", None))
        try:
            desc = registry.register_service(payload)
            return {
                "success": True,
                "service": desc.to_dict()
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    async def action_unregister_service(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Action: payment.unregister_service / unregister_payment_service
        Payload: {id / service_id / provider_id}
        """
        from ..services.payment_service_registry import PaymentServiceRegistry
        service_id = payload.get("id") or payload.get("service_id") or payload.get("provider_id")
        if not service_id:
            return {"success": False, "error": "Identifiant de service manquant"}
        registry = PaymentServiceRegistry.get_instance(getattr(self.module, "app", None))
        ok = registry.unregister_service(str(service_id))
        return {"success": ok}

    async def action_list_services(self, payload: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Action: payment.list_services
        """
        from ..services.payment_service_registry import PaymentServiceRegistry
        from ..services.provider_service import ProviderService
        repo = ProviderService._get_setting_repo(self.module)
        registry = PaymentServiceRegistry.get_instance(getattr(self.module, "app", None))
        services = await registry.list_services_enriched(repo)
        return {
            "success": True,
            "services": [s.to_dict() for s in services]
        }

