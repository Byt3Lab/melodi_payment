from core import get_prefix_table
from core.db.base_module_tables import BaseModuleTables

MODULE_NAME = "melodi_payment"
PREFIX_TABLE = get_prefix_table(MODULE_NAME)


class PaymentTables(BaseModuleTables):
    """Centralisation dynamique des noms de tables SQL du module melodi_payment."""
    PAYMENTS = f"{PREFIX_TABLE}payments"
    PAYMENT_ATTEMPTS = f"{PREFIX_TABLE}payment_attempts"
    REFUNDS = f"{PREFIX_TABLE}refunds"


DEFAULT_EXPIRATION_MINUTES = 60
DEFAULT_CURRENCY = "XAF"
