from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Subh AI"
    agent_name: str = "Subh AI"
    environment: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # SQLite by default so the stack runs with no infrastructure. Point this at
    # postgresql+asyncpg://... in deployment; the models are unchanged.
    database_url: str = "sqlite+aiosqlite:///./subh_ai.db"
    secret_key: str = "change-me"
    log_level: str = "INFO"

    # --- LLM ---
    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-5"
    llm_max_tokens: int = 16000
    llm_effort: str = "high"
    llm_server_side_fallbacks: bool = True
    llm_max_iterations: int = 8

    # --- Web / API tools ---
    web_timeout_seconds: int = 15
    web_max_bytes: int = 400_000
    # Only these hosts may be reached by the http_api tool. Empty blocks all.
    api_allowed_hosts: str = ""

    # --- Voice ---
    # "browser" uses the client's Web Speech API (no keys, works offline-ish).
    # "server" expects an STT/TTS provider to be configured.
    voice_mode: str = "browser"

    # --- Scheduler (Phase 5) ---
    scheduler_enabled: bool = True
    scheduler_tick_seconds: int = 15
    task_retry_backoff_seconds: int = 5

    # --- Auth / security (Phase 6) ---
    # Off by default so local development is frictionless. Turn on for anything
    # reachable by another machine.
    auth_enabled: bool = False
    jwt_algorithm: str = "HS256"
    jwt_ttl_seconds: int = 86400
    # Base64 Fernet key for encrypting stored secrets. Generated from
    # secret_key when unset, which is fine for dev and not for production.
    data_encryption_key: str = ""
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_api_hosts(self) -> set[str]:
        return {h.strip().lower() for h in self.api_allowed_hosts.split(",") if h.strip()}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
