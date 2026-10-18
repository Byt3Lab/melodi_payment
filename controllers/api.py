from core.routing import Request, Response
from ..services.payment_service import PaymentService
from ..services.provider_service import ProviderService
from ..services.refund_service import RefundService


class PaymentAPIController:
    """Contrôleur API REST pour les opérations de paiement."""

    @staticmethod
    async def create_payment(request: Request, response: Response):
        data = request.json or {}
        amount = data.get("amount")
        currency = data.get("currency")
        reference = data.get("reference")
        idempotency_key = data.get("idempotency_key")
        description = data.get("description")
        source_type = data.get("source_type")
        source_id = data.get("source_id")
        payer = data.get("payer")
        metadata = data.get("metadata")
        expiration_minutes = data.get("expiration_minutes")

        if amount is None:
            return response.render_json({
                "status": "error",
                "message": "Le champ 'amount' est obligatoire."
            }, status_code=400)

        async with request.module.app.db.get_session() as session:
            try:
                res = await PaymentService.create_payment(
                    session=session,
                    amount=amount,
                    currency=currency,
                    reference=reference,
                    idempotency_key=idempotency_key,
                    description=description,
                    source_type=source_type,
                    source_id=source_id,
                    payer=payer,
                    metadata=metadata,
                    expiration_minutes=expiration_minutes,
                    module_instance=request.module,
                )
                await session.commit()
                status_code = 200 if res.get("is_idempotent") else 201
                return response.render_json({
                    "status": "success",
                    "data": res
                }, status_code=status_code)
            except Exception as e:
                return response.render_json({
                    "status": "error",
                    "message": str(e)
                }, status_code=400)

    @staticmethod
    async def list_payments(request: Request, response: Response):
        query = request.query or {}
        limit = int(query.get("limit") or 50)
        offset = int(query.get("offset") or 0)
        status = query.get("status")
        source_type = query.get("source_type")
        source_id = query.get("source_id")

        async with request.module.app.db.get_session() as session:
            data = await PaymentService.list_payments(
                session=session,
                limit=limit,
                offset=offset,
                status=status,
                source_type=source_type,
                source_id=source_id,
            )
            return response.render_json({
                "status": "success",
                "data": data
            })

    @staticmethod
    async def get_payment(request: Request, response: Response):
        payment_id = request.path_params.get("id") or request.query.get("id")
        if not payment_id:
            return response.render_json({
                "status": "error",
                "message": "Identifiant de paiement manquant."
            }, status_code=400)

        async with request.module.app.db.get_session() as session:
            payment = await PaymentService.get_payment(
                session=session,
                payment_id=payment_id,
                include_attempts=True,
                include_refunds=True,
            )
            if not payment:
                return response.render_json({
                    "status": "error",
                    "message": f"Paiement #{payment_id} introuvable."
                }, status_code=404)

            return response.render_json({
                "status": "success",
                "data": payment
            })

    @staticmethod
    async def process_payment(request: Request, response: Response):
        payment_id = request.path_params.get("id") or request.query.get("id")
        data = request.json or {}
        method = data.get("method")
        context = data.get("context") or {}

        if not payment_id or not method:
            return response.render_json({
                "status": "error",
                "message": "Les paramètres 'id' et 'method' sont obligatoires."
            }, status_code=400)

        async with request.module.app.db.get_session() as session:
            try:
                res = await PaymentService.process_payment(
                    session=session,
                    payment_id=payment_id,
                    method=method,
                    module_instance=request.module,
                    context=context,
                )
                await session.commit()
                return response.render_json({
                    "status": "success",
                    "data": res
                })
            except Exception as e:
                return response.render_json({
                    "status": "error",
                    "message": str(e)
                }, status_code=400)

    @staticmethod
    async def verify_payment(request: Request, response: Response):
        payment_id = request.path_params.get("id") or request.query.get("id")
        if not payment_id:
            return response.render_json({
                "status": "error",
                "message": "Identifiant de paiement manquant."
            }, status_code=400)

        async with request.module.app.db.get_session() as session:
            try:
                res = await PaymentService.verify_payment(
                    session=session,
                    payment_id=payment_id,
                    module_instance=request.module,
                )
                await session.commit()
                return response.render_json({
                    "status": "success",
                    "data": res
                })
            except Exception as e:
                return response.render_json({
                    "status": "error",
                    "message": str(e)
                }, status_code=400)

    @staticmethod
    async def cancel_payment(request: Request, response: Response):
        payment_id = request.path_params.get("id") or request.query.get("id")
        data = request.json or {}
        reason = data.get("reason")

        if not payment_id:
            return response.render_json({
                "status": "error",
                "message": "Identifiant de paiement manquant."
            }, status_code=400)

        async with request.module.app.db.get_session() as session:
            try:
                res = await PaymentService.cancel_payment(
                    session=session,
                    payment_id=payment_id,
                    reason=reason,
                    module_instance=request.module,
                )
                await session.commit()
                return response.render_json({
                    "status": "success",
                    "data": res
                })
            except Exception as e:
                return response.render_json({
                    "status": "error",
                    "message": str(e)
                }, status_code=400)

    @staticmethod
    async def refund_payment(request: Request, response: Response):
        payment_id = request.path_params.get("id") or request.query.get("id")
        data = request.json or {}
        amount = data.get("amount")
        reason = data.get("reason")
        metadata = data.get("metadata")

        if not payment_id or amount is None:
            return response.render_json({
                "status": "error",
                "message": "L'identifiant du paiement et le montant sont requis."
            }, status_code=400)

        async with request.module.app.db.get_session() as session:
            try:
                res = await RefundService.process_refund(
                    session=session,
                    payment_id=payment_id,
                    amount=amount,
                    reason=reason,
                    module_instance=request.module,
                    metadata=metadata,
                )
                await session.commit()
                return response.render_json({
                    "status": "success",
                    "data": res
                })
            except Exception as e:
                return response.render_json({
                    "status": "error",
                    "message": str(e)
                }, status_code=400)

    @staticmethod
    async def get_methods(request: Request, response: Response):
        context = request.query or {}
        methods = await ProviderService.get_available_methods(
            module_instance=request.module,
            context=context
        )
        return response.render_json({
            "status": "success",
            "count": len(methods),
            "data": methods
        })

    @staticmethod
    async def list_providers(request: Request, response: Response):
        providers = await ProviderService.get_registered_providers(module_instance=request.module)
        return response.render_json({
            "status": "success",
            "count": len(providers),
            "data": providers
        })
