from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from a_domain.ports.order.order_repository import IOrderRepository
from b_application.config.app_config import AppConfig
from b_application.pipeline import Pipeline
from b_application.use_cases.order.order_cancellation import OrderCancellation
from b_application.use_cases.order.order_listing import OrderListing
from b_application.use_cases.order.order_lookup import OrderLookup
from b_application.use_cases.order.recipient_lookup import RecipientLookup
from b_application.use_cases.system.audit_trail import AuditTrail
from b_application.use_cases.system.sign_in import SignIn
from c_infrastructure.auth.jwt_token_verifier import JwtTokenVerifier
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.audit_log import AuditLog
from c_infrastructure.database.repositories.order_repository import OrderRepository
from c_infrastructure.privacy.pii_guard_filter import PiiGuardFilter
from c_infrastructure.system.system_clock import SystemClock


def load_config() -> AppConfig:
    """
    The settings from config/appsetting.yaml, with .env and the environment over them. It fails at startup, naming the
    setting, when a required one is missing.
    """
    return AppConfig.model_validate({})


def load_public_key(config: AppConfig) -> RSAPublicKey:
    public_key = load_pem_public_key(config.jwt_public_key.read_bytes())

    if not isinstance(public_key, RSAPublicKey):
        raise ValueError(f"{config.jwt_public_key} is not an RSA public key, and the SSO signs with {config.jwt_algorithm}")

    return public_key


async def open_database(config: AppConfig) -> DatabaseConnector:
    """The database with its tables in place, ready for the repositories."""
    database = DatabaseConnector(config)
    await database.init_db()

    return database


def create_order_repository(database: DatabaseConnector) -> IOrderRepository:
    return OrderRepository(database)


def build_pipeline(config: AppConfig, database: DatabaseConnector) -> Pipeline:
    clock = SystemClock()
    personal_data_filter = PiiGuardFilter()
    order_repository = create_order_repository(database)
    audit_log = AuditLog(database)

    return Pipeline(
        sign_in=SignIn(JwtTokenVerifier(load_public_key(config), config), audit_log, clock),
        order_lookup=OrderLookup(order_repository),
        recipient_lookup=RecipientLookup(order_repository, config),
        order_listing=OrderListing(order_repository),
        order_cancellation=OrderCancellation(order_repository, personal_data_filter, clock),
        audit_trail=AuditTrail(audit_log, personal_data_filter, clock),
    )
