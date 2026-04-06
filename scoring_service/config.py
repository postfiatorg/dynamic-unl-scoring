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
    # Geolocation (DB-IP Lite, CC BY 4.0 — freely publishable with attribution)
    # -------------------------------------------------------------------------
    geolocation_db_path: str = Field(
        default="data/geolocation/dbip-country-lite.mmdb",
        description="Path to DB-IP Lite Country MMDB database file",
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
        description="IPFS node API URL for uploading/pinning (e.g., https://ipfs-testnet.postfiat.org)",
    )
    ipfs_api_username: str = Field(
        default="",
        description="IPFS API basic auth username",
    )
    ipfs_api_password: str = Field(
        default="",
        description="IPFS API basic auth password",
    )
    ipfs_gateway_url: str = Field(
        default="",
        description="IPFS public gateway URL for reading pinned content (e.g., https://ipfs.io/ipfs/)",
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
    scoring_temperature: int = Field(
        default=0,
        description="LLM sampling temperature (0 = deterministic)",
    )
    scoring_max_tokens: int = Field(
        default=16384,
        description="Maximum tokens in LLM response",
    )

    # -------------------------------------------------------------------------
    # UNL Selection
    # -------------------------------------------------------------------------
    unl_score_cutoff: int = Field(
        default=40,
        description="Minimum score for a validator to be considered for the UNL",
    )
    unl_max_size: int = Field(
        default=35,
        description="Maximum number of validators on the UNL",
    )
    unl_min_score_gap: int = Field(
        default=5,
        description="Minimum score margin a challenger needs over the weakest incumbent to displace them",
    )

    # -------------------------------------------------------------------------
    # VL Publisher
    # -------------------------------------------------------------------------
    vl_publisher_token: str = Field(
        default="",
        description="Base64 publisher token for signing Validator Lists",
    )
    vl_expiration_days: int = Field(
        default=500,
        description="Days until a generated VL expires (safety net if service stops publishing)",
    )

    # -------------------------------------------------------------------------
    # RPC Node (for fetching validator manifests)
    # -------------------------------------------------------------------------
    rpc_url: str = Field(
        default="",
        description="postfiatd RPC endpoint URL (e.g., https://rpc.testnet.postfiat.org)",
    )

    # -------------------------------------------------------------------------
    # HTTP Clients (shared across all data collection clients)
    # -------------------------------------------------------------------------
    http_request_timeout: int = Field(
        default=30,
        description="HTTP request timeout in seconds",
    )
    http_max_retries: int = Field(
        default=3,
        description="Maximum retry attempts for failed HTTP requests",
    )
    http_retry_base_delay: int = Field(
        default=2,
        description="Base delay in seconds for exponential backoff between retries",
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
