from core.module import ApplicationModule
from .permissions.permissions import get_payment_permissions
from .controllers.api import PaymentAPIController
from .controllers.web import PaymentWebController
from .hooks.actions import PaymentActions


class MelodiPaymentModule(ApplicationModule):
    """Module central d'infrastructure de paiement de MELODI ERP."""

    def __init__(self, name: str = "melodi_payment", router_name: str = "melodi_payment"):
        super().__init__(name=name, router_name=router_name)

    def _get_permissions(self):
        return get_payment_permissions(self)

    async def run_dev_migrations(self):
        """Création automatique des tables du module de paiement."""
        from .models.payment import PaymentModel
        from .models.payment_attempt import PaymentAttemptModel
        from .models.refund import RefundModel

        await self.app.db.create_all([
            PaymentModel,
            PaymentAttemptModel,
            RefundModel,
        ])

    def _register_routes(self):
        """Enregistre les routes Web d'administration et les endpoints API REST."""
        # 1. Routes d'administration Web
        self.admin_router.add_route("", PaymentWebController.admin_dashboard, methods=["GET"])
        self.admin_router.add_route("/", PaymentWebController.admin_dashboard, methods=["GET"])
        self.admin_router.add_route("/dashboard", PaymentWebController.admin_dashboard, methods=["GET"])
        self.admin_router.add_route("/payments", PaymentWebController.admin_payments_list, methods=["GET", "POST"])
        self.admin_router.add_route("/detail", PaymentWebController.admin_payment_detail, methods=["GET", "POST"])
        self.admin_router.add_route("/attempts", PaymentWebController.admin_attempts, methods=["GET"])
        self.admin_router.add_route("/refunds", PaymentWebController.admin_refunds, methods=["GET"])
        self.admin_router.add_route("/methods", PaymentWebController.admin_methods, methods=["GET"])
        self.admin_router.add_route("/providers", PaymentWebController.admin_providers, methods=["GET", "POST"])
        self.admin_router.add_route("/providers/toggle", PaymentWebController.admin_providers_toggle, methods=["POST"])
        self.admin_router.add_route("/providers/set-default", PaymentWebController.admin_providers_set_default, methods=["POST"])
        self.admin_router.add_route("/webhooks", PaymentWebController.admin_webhooks, methods=["GET"])
        self.admin_router.add_route("/reconciliation", PaymentWebController.admin_reconciliation, methods=["GET", "POST"])
        self.admin_router.add_route("/logs", PaymentWebController.admin_logs, methods=["GET"])
        self.admin_router.add_route("/settings", PaymentWebController.admin_settings, methods=["GET"])

        # 2. Routes API REST
        self.api_router.add_route("/payments", PaymentAPIController.create_payment, methods=["POST"])
        self.api_router.add_route("/payments", PaymentAPIController.list_payments, methods=["GET"])
        self.api_router.add_route("/payments/{id}", PaymentAPIController.get_payment, methods=["GET"])
        self.api_router.add_route("/payments/{id}/process", PaymentAPIController.process_payment, methods=["POST"])
        self.api_router.add_route("/payments/{id}/verify", PaymentAPIController.verify_payment, methods=["POST"])
        self.api_router.add_route("/payments/{id}/cancel", PaymentAPIController.cancel_payment, methods=["POST"])
        self.api_router.add_route("/payments/{id}/refund", PaymentAPIController.refund_payment, methods=["POST"])
        self.api_router.add_route("/methods", PaymentAPIController.get_methods, methods=["GET"])
        self.api_router.add_route("/providers", PaymentAPIController.list_providers, methods=["GET"])

    def _register_actions(self):
        """Enregistre les actions publiques exposées aux autres modules."""
        PaymentActions(self).register_all()

    def _register_navigation(self):
        """Enregistre l'arborescence complète dans le menu latéral d'administration."""
        self.register_navigation(
            id="payment_root",
            label="Paiements",
            icon="name=credit_card&fill=white",
            url="/admin/melodi_payment",
            priority=64,
            children=[
                {"label": "Tableau de bord", "icon": "name=dashboard&fill=white", "url": "/admin/melodi_payment"},
                {"label": "Tous les Paiements", "icon": "name=receipt_long&fill=white", "url": "/admin/melodi_payment/payments"},
                {"label": "Tentatives", "icon": "name=history&fill=white", "url": "/admin/melodi_payment/attempts"},
                {"label": "Remboursements", "icon": "name=undo&fill=white", "url": "/admin/melodi_payment/refunds"},
                {"label": "Moyens de Paiement", "icon": "name=payment&fill=white", "url": "/admin/melodi_payment/methods"},
                {"label": "Fournisseurs (Providers)", "icon": "name=hub&fill=white", "url": "/admin/melodi_payment/providers"},
                {"label": "Webhooks & Callbacks", "icon": "name=webhook&fill=white", "url": "/admin/melodi_payment/webhooks"},
                {"label": "Rapprochement", "icon": "name=sync_alt&fill=white", "url": "/admin/melodi_payment/reconciliation"},
                {"label": "Journaux & Audit", "icon": "name=analytics&fill=white", "url": "/admin/melodi_payment/logs"},
                {"label": "Paramètres", "icon": "name=settings&fill=white", "url": "/admin/melodi_payment/settings"},
            ]
        )

    async def load(self):
        """Point d'entrée du cycle de vie du module melodi_payment."""
        # 1. Permissions
        self.permissions = self._get_permissions()

        # 2. Migrations en environnement dev
        if self.app and self.app.server and getattr(self.app.server.app, "debug", False):
            await self.run_dev_migrations()

        # 3. Actions publiques
        self._register_actions()

        # 4. Routes Web et API
        self._register_routes()

        # 5. Navigation
        self._register_navigation()


module = MelodiPaymentModule(
    name="melodi_payment",
    router_name="melodi_payment"
)
