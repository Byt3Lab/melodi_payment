from core.module import Permission


def get_payment_permissions(module) -> list[Permission]:
    """Retourne la liste des permissions RBAC fines pour melodi_payment."""
    return [
        Permission(module, "payment:read", "Consulter les paiements et le tableau de bord"),
        Permission(module, "payment:create", "Créer des demandes de paiement"),
        Permission(module, "payment:process", "Exécuter ou relancer des tentatives de paiement"),
        Permission(module, "payment:cancel", "Annuler des demandes de paiement en attente"),
        Permission(module, "payment:refund", "Initier et exécuter des remboursements"),
        Permission(module, "payment:reconcile", "Effectuer le rapprochement et la synchronisation externe"),
        Permission(module, "payment:attempts:read", "Consulter l'historique technique des tentatives"),
        Permission(module, "payment:refunds:read", "Consulter les remboursements"),
        Permission(module, "payment:providers:read", "Consulter les connecteurs providers et méthodes"),
        Permission(module, "payment:logs:read", "Consulter les journaux d'audit et callbacks"),
        Permission(module, "payment:settings:read", "Consulter les paramètres du module de paiement"),
        Permission(module, "payment:admin", "Administration complète de l'infrastructure de paiement"),
    ]
