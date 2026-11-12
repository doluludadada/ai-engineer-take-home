from pathlib import Path
from typing import Annotated, Literal, override

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

from a_domain.types.enums import SigningAlgorithm
from a_domain.types.values import ListLimit, NonEmptyText
from b_application.config.masking_config import MaskingConfig
from b_application.config.texts_config import TextsConfig


class AppConfig(BaseSettings):
    """
    The order tool server's settings. config/appsetting.yaml holds the values every deployment shares, and the
    environment variable ORDER_TOOLS_<NAME> sets, or overrides, one for a deployment.
    """

    model_config = SettingsConfigDict(
        env_prefix="ORDER_TOOLS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        yaml_file=Path(__file__).parents[3] / "config" / "appsetting.yaml",
        yaml_file_encoding="utf-8",
    )

    db: Path
    """The SQLite file that holds the orders and the audit log."""

    db_busy_timeout_seconds: Annotated[float, Field(gt=0, le=60)]
    """How long a write waits for another connection's write to finish before it fails."""

    jwt_public_key: Path
    """The PEM file of the company SSO's RSA public key, which checks a token's signature."""

    jwt_issuer: Annotated[str, Field(pattern=r"^https?://\S+$")]
    """The `iss` a token must carry: the SSO's issuer URL, http or https. The MCP SDK also takes it as its issuer URL."""

    jwt_audience: NonEmptyText
    """The `aud` a token must carry: this service's name at the SSO."""

    jwt_algorithm: SigningAlgorithm
    """The one algorithm a token must be signed with. A token that names any other is refused."""

    jwt_leeway_seconds: Annotated[int, Field(ge=0, le=300)]
    """How far this machine's clock and the SSO's may differ when a token's expiry is checked."""

    server_name: NonEmptyText
    """The name the MCP server gives itself to the agents that connect."""

    transport: Literal["streamable-http"]
    """
    How agents reach the server. Only HTTP is accepted: the gateway forwards the user's token in an HTTP header, and
    the token check runs on every HTTP request.
    """

    host: NonEmptyText
    """The address the server listens on. 0.0.0.0 in a container."""

    port: Annotated[int, Field(gt=0, lt=65536)]

    request_id_header: NonEmptyText
    """The HTTP header, in lower case, in which the gateway sends its request id."""

    list_default_limit: ListLimit
    """How many orders list_my_orders returns when the caller names no limit."""

    request_id_max_length: Annotated[int, Field(gt=0, le=1024)]
    """The gateway's request id is cut to this length before it is stored."""

    masking: MaskingConfig
    texts: TextsConfig

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """A value given in code wins, then the environment, then .env, then config/appsetting.yaml."""
        return init_settings, env_settings, dotenv_settings, YamlConfigSettingsSource(settings_cls)
