"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_PATH = REPO_ROOT / "migrations"


class Settings(BaseSettings):

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    database_url: str = Field(
        default="postgresql://postgres:dev_password@localhost:5432/dynamic_unl_scoring",
        description="PostgreSQL connection string",
    )

    # -------------------------------------------------------------------------
    # PFTL Chain
    # -------------------------------------------------------------------------
    pftl_rpc_url: str = Field(
        default="",
        description="PFTL chain JSON-RPC URL",
    )
    pftl_wallet_secret: str = Field(
        default="",
        description="Backend wallet secret for memo transactions",
    )
    pftl_memo_destination: str = Field(
        default="",
        description="Destination address for memo transactions",
    )
    pftl_network: str = Field(
        default="devnet",
        description="PFTL network: devnet, testnet, or mainnet",
    )

    # -------------------------------------------------------------------------
    # VHS
    # -------------------------------------------------------------------------
    vhs_api_url: str = Field(
        default="https://vhs.testnet.postfiat.org",
        description="Validator History Service base URL",
    )

    # -------------------------------------------------------------------------
    # MaxMind (internal geolocation only, not published to IPFS)
    # -------------------------------------------------------------------------
    maxmind_account_id: str = Field(
        default="",
        description="MaxMind account ID for GeoIP2 Insights",
    )
    maxmind_license_key: str = Field(
        default="",
        description="MaxMind license key",
    )

    # -------------------------------------------------------------------------
    # Modal (LLM inference endpoint)
    # -------------------------------------------------------------------------
    modal_endpoint_url: str = Field(
        default="",
        description="Modal SGLang endpoint URL (OpenAI-compatible)",
    )

    # -------------------------------------------------------------------------
    # IPFS
    # -------------------------------------------------------------------------
    ipfs_api_url: str = Field(
        default="",
        description="IPFS API URL for pinning audit trail artifacts",
    )
    ipfs_gateway_url: str = Field(
        default="",
        description="IPFS gateway URL for public access",
    )

    # -------------------------------------------------------------------------
    # Scoring
    # -------------------------------------------------------------------------
    scoring_cadence_hours: int = Field(
        default=168,
        description="Hours between scoring rounds (168 = weekly)",
    )
    scoring_model_id: str = Field(
        default="Qwen/Qwen3-Next-80B-A3B-Instruct-FP8",
        description="Model ID for the scoring LLM",
    )
    scoring_model_name: str = Field(
        default="qwen3-next-80b-instruct",
        description="Short model name for display and file paths",
    )

    # -------------------------------------------------------------------------
    # VL Publisher
    # -------------------------------------------------------------------------
    vl_publisher_token: str = Field(
        default="",
        description="Base64 publisher token for signing Validator Lists",
    )
    vl_output_url: str = Field(
        default="",
        description="URL where signed VL is served to validators",
    )

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------
    debug: bool = Field(
        default=False,
        description="Enable debug mode (console logging, verbose output)",
    )
    log_level: str = Field(
        default="INFO",
        description="Log level: DEBUG, INFO, WARNING, ERROR",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def pftl_network_id(self) -> int:
        network_ids = {"devnet": 2024, "testnet": 2025, "mainnet": 2026}
        return network_ids.get(self.pftl_network.lower(), 2024)

    @property
    def pftl_enabled(self) -> bool:
        return bool(self.pftl_rpc_url and self.pftl_wallet_secret and self.pftl_memo_destination)


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
