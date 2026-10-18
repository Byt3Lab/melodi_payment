import json
from decimal import Decimal
from datetime import datetime
from core.routing import Request, Response
from core.page_builder import Page, Component
from base.components import admin_layout

from ..services.payment_service import PaymentService
from ..services.provider_service import ProviderService
from ..services.refund_service import RefundService
from ..repositories.payment_repository import PaymentRepository
from ..repositories.payment_attempt_repository import PaymentAttemptRepository
from ..repositories.refund_repository import RefundRepository
from ..config import DEFAULT_CURRENCY, DEFAULT_EXPIRATION_MINUTES, PaymentTables, MODULE_NAME


class PaymentWebController:
    """Contrôleur d'administration Web complet pour melodi_payment."""

    @staticmethod
    async def admin_dashboard(request: Request, response: Response):
        """1. Tableau de bord : KPIs, statistiques réelles et graphiques de distribution."""
        async with request.module.app.db.get_session() as session:
            stats = await PaymentRepository.get_dashboard_stats(session)
            providers = await ProviderService.get_registered_providers(request.module)
            methods = await ProviderService.get_available_methods(request.module)
            recent_payments = await PaymentRepository.list_payments(session, limit=8, offset=0)

        content = Component(module_name="melodi_payment", name="admin_dashboard", context={
            "stats": stats,
            "providers": providers,
            "methods": methods,
            "recent_payments": [p.to_dict() for p in recent_payments],
        })
        page = Page("Tableau de bord — Paiements", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_payments_list(request: Request, response: Response):
        """2. Liste des paiements : recherche, multi-filtres et pagination côté serveur."""
        query = request.query or {}
        search = query.get("q") or None
        status = query.get("status") or None
        method = query.get("method") or None
        provider = query.get("provider") or None
        currency = query.get("currency") or None
        date_from_str = query.get("date_from") or None
        date_to_str = query.get("date_to") or None
        sort_by = query.get("sort") or "created_at"
        sort_dir = query.get("dir") or "desc"

        page_num = max(1, int(query.get("page") or 1))
        limit = max(10, min(100, int(query.get("limit") or 25)))
        offset = (page_num - 1) * limit

        date_from = None
        date_to = None
        if date_from_str:
            try:
                date_from = datetime.fromisoformat(date_from_str)
            except Exception:
                pass
        if date_to_str:
            try:
                date_to = datetime.fromisoformat(date_to_str)
            except Exception:
                pass

        # Traitement d'action rapide POST
        if request.method == "POST":
            form = request.form
            action_type = form.get("action_type")
            async with request.module.app.db.get_session() as session:
                try:
                    if action_type == "create_payment":
                        await PaymentService.create_payment(
                            session=session,
                            amount=Decimal(form.get("amount", "0")),
                            currency=form.get("currency", DEFAULT_CURRENCY),
                            reference=form.get("reference") or None,
                            description=form.get("description"),
                            source_type=form.get("source_type") or "admin.manual",
                            source_id=form.get("source_id"),
                            module_instance=request.module,
                        )
                        await session.commit()
                except Exception as e:
                    print("Payment create action error:", e)
            return response.redirect("/admin/melodi_payment/payments")

        async with request.module.app.db.get_session() as session:
            payments = await PaymentRepository.list_payments(
                session=session,
                limit=limit,
                offset=offset,
                status=status,
                method=method,
                provider=provider,
                currency=currency,
                date_from=date_from,
                date_to=date_to,
                search=search,
                order_by=sort_by,
                order_dir=sort_dir,
            )
            total = await PaymentRepository.count_payments(
                session=session,
                status=status,
                method=method,
                provider=provider,
                currency=currency,
                date_from=date_from,
                date_to=date_to,
                search=search,
            )
            providers = await ProviderService.get_registered_providers(request.module)
            methods = await ProviderService.get_available_methods(request.module)

        total_pages = max(1, (total + limit - 1) // limit)

        content = Component(module_name="melodi_payment", name="admin_payments", context={
            "payments": [p.to_dict() for p in payments],
            "total": total,
            "page": page_num,
            "total_pages": total_pages,
            "limit": limit,
            "filter_search": search or "",
            "filter_status": status or "",
            "filter_method": method or "",
            "filter_provider": provider or "",
            "filter_currency": currency or "",
            "filter_date_from": date_from_str or "",
            "filter_date_to": date_to_str or "",
            "sort_by": sort_by,
            "sort_dir": sort_dir,
            "providers": providers,
            "methods": methods,
        })
        page = Page("Gestion des Paiements", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_payment_detail(request: Request, response: Response):
        """3. Fiche détaillée d'un paiement avec exécution sécurisée des opérations métier."""
        payment_id = request.query.get("id") or request.path_params.get("id")
        if not payment_id:
            return response.redirect("/admin/melodi_payment/payments")

        flash_message = None
        flash_type = "info"

        if request.method == "POST":
            form = request.form
            action_type = form.get("action_type")
            async with request.module.app.db.get_session() as session:
                try:
                    if action_type == "process":
                        method = form.get("method")
                        await PaymentService.process_payment(
                            session=session,
                            payment_id=payment_id,
                            method=method,
                            module_instance=request.module,
                        )
                        await session.commit()
                        flash_message = f"Tentative de paiement via {method} initiée."
                        flash_type = "success"
                    elif action_type == "verify":
                        res = await PaymentService.verify_payment(
                            session=session,
                            payment_id=payment_id,
                            module_instance=request.module,
                        )
                        await session.commit()
                        flash_message = f"Vérification terminée : statut '{res.get('status')}'."
                        flash_type = "info"
                    elif action_type == "cancel":
                        reason = form.get("reason", "Annulation administrative")
                        await PaymentService.cancel_payment(
                            session=session,
                            payment_id=payment_id,
                            reason=reason,
                            module_instance=request.module,
                        )
                        await session.commit()
                        flash_message = "Paiement annulé avec succès."
                        flash_type = "warning"
                    elif action_type == "refund":
                        amount = Decimal(form.get("amount", "0"))
                        reason = form.get("reason", "Remboursement administratif")
                        await RefundService.process_refund(
                            session=session,
                            payment_id=payment_id,
                            amount=amount,
                            reason=reason,
                            module_instance=request.module,
                        )
                        await session.commit()
                        flash_message = f"Remboursement de {amount} validé avec succès."
                        flash_type = "success"
                except Exception as e:
                    flash_message = f"Erreur : {str(e)}"
                    flash_type = "danger"

            return response.redirect(f"/admin/melodi_payment/detail?id={payment_id}&msg={flash_message}&msg_type={flash_type}")

        async with request.module.app.db.get_session() as session:
            payment = await PaymentService.get_payment(
                session=session,
                payment_id=payment_id,
                include_attempts=True,
                include_refunds=True,
            )
            if not payment:
                return response.redirect("/admin/melodi_payment/payments")

            methods = await ProviderService.get_available_methods(
                module_instance=request.module,
                context={"currency": payment.get("currency"), "amount": payment.get("amount_float")}
            )

            # Calcul du solde remboursable
            refunds = payment.get("refunds", [])
            total_refunded = sum(float(r.get("amount_float", 0)) for r in refunds if r.get("status") == "succeeded")
            max_refundable = max(0.0, float(payment.get("amount_float", 0)) - total_refunded)

        content = Component(module_name="melodi_payment", name="admin_payment_detail", context={
            "payment": payment,
            "methods": methods,
            "max_refundable": max_refundable,
            "total_refunded": total_refunded,
            "flash_message": request.query.get("msg") or flash_message,
            "flash_type": request.query.get("msg_type") or flash_type,
        })
        page = Page(f"Détail Paiement {payment.get('reference')}", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_attempts(request: Request, response: Response):
        """4. Tentatives de paiement : audit transversal des essais et métadonnées passerelles."""
        query = request.query or {}
        search = query.get("q") or None
        status = query.get("status") or None
        provider = query.get("provider") or None
        method = query.get("method") or None

        page_num = max(1, int(query.get("page") or 1))
        limit = max(10, min(100, int(query.get("limit") or 25)))
        offset = (page_num - 1) * limit

        async with request.module.app.db.get_session() as session:
            attempts = await PaymentAttemptRepository.list_all_attempts(
                session=session,
                limit=limit,
                offset=offset,
                status=status,
                provider=provider,
                method=method,
                search=search,
            )
            total = await PaymentAttemptRepository.count_all_attempts(
                session=session,
                status=status,
                provider=provider,
                method=method,
                search=search,
            )
            providers = await ProviderService.get_registered_providers(request.module)
            methods = await ProviderService.get_available_methods(request.module)

        total_pages = max(1, (total + limit - 1) // limit)

        attempts_data = []
        for a in attempts:
            ad = a.to_dict()
            ad["payment_ref"] = a.payment.reference if a.payment else "N/A"
            attempts_data.append(ad)

        content = Component(module_name="melodi_payment", name="admin_attempts", context={
            "attempts": attempts_data,
            "total": total,
            "page": page_num,
            "total_pages": total_pages,
            "limit": limit,
            "filter_search": search or "",
            "filter_status": status or "",
            "filter_provider": provider or "",
            "filter_method": method or "",
            "providers": providers,
            "methods": methods,
        })
        page = Page("Tentatives de Paiement", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_refunds(request: Request, response: Response):
        """5. Remboursements : consultation des remboursements complets et partiels."""
        query = request.query or {}
        search = query.get("q") or None
        status = query.get("status") or None

        page_num = max(1, int(query.get("page") or 1))
        limit = max(10, min(100, int(query.get("limit") or 25)))
        offset = (page_num - 1) * limit

        async with request.module.app.db.get_session() as session:
            refunds = await RefundRepository.list_all_refunds(
                session=session,
                limit=limit,
                offset=offset,
                status=status,
                search=search,
            )
            total = await RefundRepository.count_all_refunds(
                session=session,
                status=status,
                search=search,
            )

        total_pages = max(1, (total + limit - 1) // limit)

        refunds_data = []
        for r in refunds:
            rd = r.to_dict()
            rd["payment_ref"] = r.payment.reference if r.payment else "N/A"
            rd["payment_amount"] = str(r.payment.amount) if r.payment else "0.00"
            rd["payment_uuid"] = r.payment.payment_id if r.payment else ""
            refunds_data.append(rd)

        content = Component(module_name="melodi_payment", name="admin_refunds", context={
            "refunds": refunds_data,
            "total": total,
            "page": page_num,
            "total_pages": total_pages,
            "limit": limit,
            "filter_search": search or "",
            "filter_status": status or "",
        })
        page = Page("Remboursements", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_methods(request: Request, response: Response):
        """6. Méthodes de paiement : affichage dynamique des moyens déclarés via hooks."""
        methods = await ProviderService.get_available_methods(request.module, only_active=False)
        providers = await ProviderService.get_registered_providers(request.module)

        content = Component(module_name="melodi_payment", name="admin_methods", context={
            "methods": methods,
            "providers": providers,
        })
        page = Page("Moyens de Paiement", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_providers(request: Request, response: Response):
        """7. Fournisseurs (Providers) : affichage dynamique, activation/désactivation et configuration."""
        from ..services.payment_service_registry import PaymentServiceRegistry
        repo = ProviderService._get_setting_repo(request.module)
        registry = PaymentServiceRegistry.get_instance(getattr(request.module, "app", None))
        message = request.query.get("msg") if request.query else None
        error = request.query.get("err") if request.query else None

        if request.method == "POST":
            form = request.form or {}
            raw_active = form.getlist("active_services") if hasattr(form, "getlist") else form.get("active_services")
            if isinstance(raw_active, str):
                selected_active = [raw_active]
            elif isinstance(raw_active, (list, tuple)):
                selected_active = list(raw_active)
            else:
                selected_active = []

            default_service = (form.get("default_service") or "").strip()
            if default_service and default_service not in selected_active:
                selected_active.append(default_service)

            try:
                await registry.set_active_services(repo, selected_active, default_service or None)
                message = "Sélection des services de paiement et fournisseur par défaut enregistrés avec succès."
            except Exception as e:
                error = f"Erreur lors de l'enregistrement : {str(e)}"

        providers = await ProviderService.get_registered_providers(request.module)
        active_ids = await registry.get_active_service_ids(repo)
        default_id = await registry.get_default_service_id(repo)

        content = Component(module_name="melodi_payment", name="admin_providers", context={
            "providers": providers,
            "active_ids": active_ids,
            "default_id": default_id,
            "message": message,
            "error": error,
        })
        page = Page("Connecteurs de Paiement (Providers)", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_providers_toggle(request: Request, response: Response):
        """Bascule l'état d'activation d'un service de paiement."""
        from ..services.payment_service_registry import PaymentServiceRegistry
        repo = ProviderService._get_setting_repo(request.module)
        registry = PaymentServiceRegistry.get_instance(getattr(request.module, "app", None))

        form = request.form or {}
        service_id = (form.get("service_id") or (request.query and request.query.get("service_id")) or "").strip()

        if service_id:
            await registry.toggle_service(repo, service_id)

        return response.redirect("/admin/melodi_payment/providers")

    @staticmethod
    async def admin_providers_set_default(request: Request, response: Response):
        """Définit le service de paiement par défaut."""
        from ..services.payment_service_registry import PaymentServiceRegistry
        repo = ProviderService._get_setting_repo(request.module)
        registry = PaymentServiceRegistry.get_instance(getattr(request.module, "app", None))

        form = request.form or {}
        service_id = (form.get("service_id") or (request.query and request.query.get("service_id")) or "").strip()

        if service_id:
            await registry.set_default_service(repo, service_id)

        return response.redirect("/admin/melodi_payment/providers")

    @staticmethod
    async def admin_webhooks(request: Request, response: Response):
        """8. Webhooks & Callbacks : diagnostic technique des notifications de passerelles."""
        async with request.module.app.db.get_session() as session:
            # Les tentatives portant des response_metadata et provider_reference constituent l'historique des retours passerelles
            attempts = await PaymentAttemptRepository.list_all_attempts(session=session, limit=50, offset=0)

        webhooks_log = []
        for a in attempts:
            if a.provider_reference or a.response_metadata_raw:
                webhooks_log.append({
                    "id": a.id,
                    "attempt_id": a.attempt_id,
                    "payment_id": a.payment.payment_id if a.payment else "N/A",
                    "payment_ref": a.payment.reference if a.payment else "N/A",
                    "provider": a.provider,
                    "method": a.method,
                    "status": a.status.value if hasattr(a.status, "value") else str(a.status),
                    "provider_reference": a.provider_reference or "N/A",
                    "received_at": a.updated_at.isoformat() if a.updated_at else "",
                    "payload_preview": a.response_metadata,
                    "error_message": a.error_message,
                })

        content = Component(module_name="melodi_payment", name="admin_webhooks", context={
            "webhooks": webhooks_log,
        })
        page = Page("Webhooks & Callbacks", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_reconciliation(request: Request, response: Response):
        """9. Rapprochement : détection et synchronisation en lot des statuts externes."""
        msg = None
        if request.method == "POST":
            # Action de synchronisation
            form = request.form
            action_type = form.get("action_type")
            target_id = form.get("payment_id")

            async with request.module.app.db.get_session() as session:
                try:
                    if action_type == "sync_single" and target_id:
                        res = await PaymentService.verify_payment(session, target_id, request.module)
                        await session.commit()
                        msg = f"Paiement #{target_id} synchronisé : nouveau statut '{res.get('status')}'."
                    elif action_type == "sync_all_processing":
                        processing_payments = await PaymentRepository.list_payments(session, status="processing", limit=50)
                        synced_count = 0
                        for p in processing_payments:
                            try:
                                await PaymentService.verify_payment(session, p.payment_id, request.module)
                                synced_count += 1
                            except Exception:
                                pass
                        await session.commit()
                        msg = f"{synced_count} paiement(s) en cours synchronisé(s) auprès des fournisseurs."
                except Exception as e:
                    msg = f"Erreur de synchronisation : {str(e)}"

            return response.redirect(f"/admin/melodi_payment/reconciliation?msg={msg}")

        async with request.module.app.db.get_session() as session:
            processing_payments = await PaymentRepository.list_payments(session, status="processing", limit=50)
            pending_payments = await PaymentRepository.list_payments(session, status="pending", limit=50)

        content = Component(module_name="melodi_payment", name="admin_reconciliation", context={
            "processing_payments": [p.to_dict() for p in processing_payments],
            "pending_payments": [p.to_dict() for p in pending_payments],
            "flash_message": request.query.get("msg") or msg,
        })
        page = Page("Rapprochement & Synchronisation", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_logs(request: Request, response: Response):
        """10. Journaux & Audit : traçabilité chronologique des statuts avec masquage des données sensibles."""
        async with request.module.app.db.get_session() as session:
            attempts = await PaymentAttemptRepository.list_all_attempts(session=session, limit=100, offset=0)

        logs = []
        for a in attempts:
            st = a.status.value if hasattr(a.status, "value") else str(a.status)
            level = "SUCCESS" if st == "succeeded" else ("ERROR" if st == "failed" else "INFO")
            logs.append({
                "timestamp": a.created_at.isoformat() if a.created_at else "",
                "level": level,
                "event": f"payment.attempt.{st}",
                "payment_ref": a.payment.reference if a.payment else f"ID #{a.payment_id}",
                "payment_id": a.payment.payment_id if a.payment else "",
                "provider": a.provider,
                "method": a.method,
                "message": a.error_message or (f"Transaction {a.provider_reference} validée" if a.provider_reference else "Tentative enregistrée"),
            })

        content = Component(module_name="melodi_payment", name="admin_logs", context={
            "logs": logs,
        })
        page = Page("Journaux d'Audit Paiements", admin_layout(content))
        return await response.render_page(page)

    @staticmethod
    async def admin_settings(request: Request, response: Response):
        """11. Paramètres : vue récapitulative des constantes et configurations techniques du module."""
        from ..services.payment_service_registry import PaymentServiceRegistry
        repo = ProviderService._get_setting_repo(request.module)
        registry = PaymentServiceRegistry.get_instance(getattr(request.module, "app", None))
        active_ids = await registry.get_active_service_ids(repo)
        default_id = await registry.get_default_service_id(repo)

        content = Component(module_name="melodi_payment", name="admin_settings", context={
            "default_currency": DEFAULT_CURRENCY,
            "default_expiration_minutes": DEFAULT_EXPIRATION_MINUTES,
            "module_name": MODULE_NAME,
            "table_payments": PaymentTables.PAYMENTS,
            "table_attempts": PaymentTables.PAYMENT_ATTEMPTS,
            "table_refunds": PaymentTables.REFUNDS,
            "active_services": active_ids,
            "default_service": default_id,
        })
        page = Page("Paramètres Paiement", admin_layout(content))
        return await response.render_page(page)
