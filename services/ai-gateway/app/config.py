"""Runtime configuration with secret-safe validation."""

from __future__ import annotations

from dataclasses import dataclass
import os
import tempfile


class ConfigurationError(RuntimeError):
    """Raised when the runtime boundary is unsafe or incomplete."""


@dataclass(frozen=True, repr=False)
class Settings:
    environment: str = "development"
    store_backend: str = "memory"
    database_dsn: str | None = None
    provider_mode: str = "mock"
    openai_api_key_file: str | None = None
    openai_project_id_file: str | None = None
    safety_identifier_salt_file: str | None = None
    embedding_batch_size: int = 128
    classification: str = "D0"
    log_level: str = "INFO"
    database_pool_min: int = 1
    database_pool_max: int = 4
    artifact_root: str = os.path.join(tempfile.gettempdir(), "techflow-artifacts")
    artifact_retention_hours: int = 24
    artifact_max_bytes: int = 10 * 1024 * 1024
    artifact_max_extracted_bytes: int = 20 * 1024 * 1024
    artifact_max_archive_entries: int = 100
    artifact_max_compression_ratio: int = 20
    artifact_max_log_evidence_chars: int = 120_000
    flarum_base_url: str = "https://community.ablecloud.io"
    flarum_public_url: str = "https://community.ablecloud.io"
    flarum_api_key_file: str | None = None
    flarum_assistant_user_id_file: str | None = None
    community_publish_enabled: bool = False
    community_review_post_enabled: bool = False
    community_auto_publish_enabled: bool = False
    chat_bot_enabled: bool = False
    chat_base_url: str = "https://chat.ablecloud.io"
    chat_bot_token_file: str | None = None
    chat_reviewer_usernames: tuple[str, ...] = ()
    community_approve_webhook_file: str | None = None
    community_reject_webhook_file: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            environment=os.getenv("TECHFLOW_RAG_ENVIRONMENT", "development").strip().lower(),
            store_backend=os.getenv("TECHFLOW_RAG_STORE", "memory").strip().lower(),
            database_dsn=os.getenv("TECHFLOW_RAG_DATABASE_DSN") or None,
            provider_mode=os.getenv("TECHFLOW_RAG_PROVIDER_MODE", "mock").strip().lower(),
            openai_api_key_file=os.getenv("TECHFLOW_OPENAI_API_KEY_FILE") or None,
            openai_project_id_file=os.getenv("TECHFLOW_OPENAI_PROJECT_ID_FILE") or None,
            safety_identifier_salt_file=os.getenv("TECHFLOW_SAFETY_IDENTIFIER_SALT_FILE") or None,
            embedding_batch_size=int(os.getenv("TECHFLOW_EMBEDDING_BATCH_SIZE", "128")),
            classification=os.getenv("TECHFLOW_RAG_CLASSIFICATION", "D0").strip().upper(),
            log_level=os.getenv("TECHFLOW_RAG_LOG_LEVEL", "INFO").strip().upper(),
            database_pool_min=int(os.getenv("TECHFLOW_RAG_DATABASE_POOL_MIN", "1")),
            database_pool_max=int(os.getenv("TECHFLOW_RAG_DATABASE_POOL_MAX", "4")),
            artifact_root=os.getenv("TECHFLOW_ARTIFACT_ROOT", os.path.join(tempfile.gettempdir(), "techflow-artifacts")),
            artifact_retention_hours=int(os.getenv("TECHFLOW_ARTIFACT_RETENTION_HOURS", "24")),
            artifact_max_bytes=int(os.getenv("TECHFLOW_ARTIFACT_MAX_BYTES", str(10 * 1024 * 1024))),
            artifact_max_extracted_bytes=int(os.getenv("TECHFLOW_ARTIFACT_MAX_EXTRACTED_BYTES", str(20 * 1024 * 1024))),
            artifact_max_archive_entries=int(os.getenv("TECHFLOW_ARTIFACT_MAX_ARCHIVE_ENTRIES", "100")),
            artifact_max_compression_ratio=int(os.getenv("TECHFLOW_ARTIFACT_MAX_COMPRESSION_RATIO", "20")),
            artifact_max_log_evidence_chars=int(os.getenv("TECHFLOW_ARTIFACT_MAX_LOG_EVIDENCE_CHARS", "120000")),
            flarum_base_url=os.getenv("TECHFLOW_FLARUM_BASE_URL", "https://community.ablecloud.io").rstrip("/"),
            flarum_public_url=os.getenv("TECHFLOW_FLARUM_PUBLIC_URL", "https://community.ablecloud.io").rstrip("/"),
            flarum_api_key_file=os.getenv("TECHFLOW_FLARUM_API_KEY_FILE") or None,
            flarum_assistant_user_id_file=os.getenv("TECHFLOW_FLARUM_ASSISTANT_USER_ID_FILE") or None,
            community_publish_enabled=os.getenv("TECHFLOW_COMMUNITY_PUBLISH_ENABLED", "false").lower() == "true",
            community_review_post_enabled=os.getenv("TECHFLOW_COMMUNITY_REVIEW_POST_ENABLED", "false").lower() == "true",
            community_auto_publish_enabled=os.getenv("TECHFLOW_COMMUNITY_AUTO_PUBLISH_ENABLED", "false").lower() == "true",
            chat_bot_enabled=os.getenv("TECHFLOW_CHAT_BOT_ENABLED", "false").lower() == "true",
            chat_base_url=os.getenv("TECHFLOW_CHAT_BASE_URL", "https://chat.ablecloud.io").rstrip("/"),
            chat_bot_token_file=os.getenv("TECHFLOW_CHAT_BOT_TOKEN_FILE") or None,
            chat_reviewer_usernames=tuple(
                item.strip() for item in os.getenv("TECHFLOW_CHAT_REVIEWER_USERNAMES", "").split(",") if item.strip()
            ),
            community_approve_webhook_file=os.getenv("TECHFLOW_COMMUNITY_APPROVE_WEBHOOK_FILE") or None,
            community_reject_webhook_file=os.getenv("TECHFLOW_COMMUNITY_REJECT_WEBHOOK_FILE") or None,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.store_backend not in {"memory", "postgres"}:
            raise ConfigurationError("TECHFLOW_RAG_STORE must be memory or postgres")
        if self.store_backend == "postgres" and not self.database_dsn:
            raise ConfigurationError("TECHFLOW_RAG_DATABASE_DSN is required for postgres")
        if self.provider_mode not in {"mock", "openai"}:
            raise ConfigurationError("TECHFLOW_RAG_PROVIDER_MODE must be mock or openai")
        if self.provider_mode == "openai":
            required = {
                "TECHFLOW_OPENAI_API_KEY_FILE": self.openai_api_key_file,
                "TECHFLOW_OPENAI_PROJECT_ID_FILE": self.openai_project_id_file,
                "TECHFLOW_SAFETY_IDENTIFIER_SALT_FILE": self.safety_identifier_salt_file,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ConfigurationError(f"{', '.join(missing)} required for openai mode")
        if not 1 <= self.embedding_batch_size <= 128:
            raise ConfigurationError("TECHFLOW_EMBEDDING_BATCH_SIZE must be between 1 and 128")
        if self.classification != "D0":
            raise ConfigurationError("Issue #41 permits D0 data only")
        if self.database_pool_min < 0 or self.database_pool_max < max(1, self.database_pool_min):
            raise ConfigurationError("invalid database pool bounds")
        if not 1 <= self.artifact_retention_hours <= 168:
            raise ConfigurationError("TECHFLOW_ARTIFACT_RETENTION_HOURS must be between 1 and 168")
        if not 1024 <= self.artifact_max_bytes <= 20 * 1024 * 1024:
            raise ConfigurationError("TECHFLOW_ARTIFACT_MAX_BYTES must be between 1 KiB and 20 MiB")
        if not self.artifact_max_bytes <= self.artifact_max_extracted_bytes <= 100 * 1024 * 1024:
            raise ConfigurationError("TECHFLOW_ARTIFACT_MAX_EXTRACTED_BYTES must be between upload max and 100 MiB")
        if not 1 <= self.artifact_max_archive_entries <= 500:
            raise ConfigurationError("TECHFLOW_ARTIFACT_MAX_ARCHIVE_ENTRIES must be between 1 and 500")
        if not 1 <= self.artifact_max_compression_ratio <= 100:
            raise ConfigurationError("TECHFLOW_ARTIFACT_MAX_COMPRESSION_RATIO must be between 1 and 100")
        if not 4096 <= self.artifact_max_log_evidence_chars <= 500_000:
            raise ConfigurationError("TECHFLOW_ARTIFACT_MAX_LOG_EVIDENCE_CHARS must be between 4096 and 500000")
        if self.flarum_base_url not in {"https://community.ablecloud.io", "http://172.16.0.234"}:
            raise ConfigurationError("TECHFLOW_FLARUM_BASE_URL must use an approved Community API route")
        if self.flarum_public_url != "https://community.ablecloud.io":
            raise ConfigurationError("TECHFLOW_FLARUM_PUBLIC_URL must use the approved HTTPS community origin")
        if self.community_publish_enabled and not self.flarum_api_key_file:
            raise ConfigurationError("TECHFLOW_FLARUM_API_KEY_FILE is required when publishing is enabled")
        if self.community_review_post_enabled and not (self.flarum_api_key_file and self.flarum_assistant_user_id_file):
            raise ConfigurationError(
                "TECHFLOW_FLARUM_API_KEY_FILE and TECHFLOW_FLARUM_ASSISTANT_USER_ID_FILE are required when review posts are enabled"
            )
        if self.community_auto_publish_enabled and not (
            self.community_publish_enabled and self.flarum_api_key_file and self.flarum_assistant_user_id_file
        ):
            raise ConfigurationError(
                "automatic Community publication requires publishing, API key and assistant identity"
            )
        if self.community_auto_publish_enabled and self.community_review_post_enabled:
            raise ConfigurationError("automatic publication and review posting are mutually exclusive")
        if self.chat_base_url != "https://chat.ablecloud.io":
            raise ConfigurationError("TECHFLOW_CHAT_BASE_URL must use the approved HTTPS Chat origin")
        if self.chat_bot_enabled:
            required = {
                "TECHFLOW_CHAT_BOT_TOKEN_FILE": self.chat_bot_token_file,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ConfigurationError(f"{', '.join(missing)} required when Chat Bot is enabled")
            if not self.chat_reviewer_usernames:
                raise ConfigurationError("TECHFLOW_CHAT_REVIEWER_USERNAMES required when Chat Bot is enabled")

    def __repr__(self) -> str:
        return (
            "Settings(environment={!r}, store_backend={!r}, database_dsn=<redacted>, "
            "provider_mode={!r}, openai_api_key_file=<redacted>, openai_project_id_file=<redacted>, "
            "safety_identifier_salt_file=<redacted>, embedding_batch_size={!r}, "
            "classification={!r}, log_level={!r}, "
            "database_pool_min={!r}, database_pool_max={!r}, artifact_root=<redacted>, "
            "artifact_retention_hours={!r}, artifact_max_bytes={!r}, artifact_max_extracted_bytes={!r}, "
            "artifact_max_archive_entries={!r}, artifact_max_compression_ratio={!r}, "
            "artifact_max_log_evidence_chars={!r}, flarum_base_url={!r}, flarum_public_url={!r}, "
            "flarum_api_key_file=<redacted>, flarum_assistant_user_id_file=<redacted>, "
            "community_publish_enabled={!r}, community_review_post_enabled={!r}, community_auto_publish_enabled={!r}, chat_bot_enabled={!r}, "
            "chat_base_url={!r}, chat_bot_token_file=<redacted>, chat_reviewer_usernames=<redacted>, "
            "community_approve_webhook_file=<redacted>, community_reject_webhook_file=<redacted>)"
        ).format(
            self.environment,
            self.store_backend,
            self.provider_mode,
            self.embedding_batch_size,
            self.classification,
            self.log_level,
            self.database_pool_min,
            self.database_pool_max,
            self.artifact_retention_hours,
            self.artifact_max_bytes,
            self.artifact_max_extracted_bytes,
            self.artifact_max_archive_entries,
            self.artifact_max_compression_ratio,
            self.artifact_max_log_evidence_chars,
            self.flarum_base_url,
            self.flarum_public_url,
            self.community_publish_enabled,
            self.community_review_post_enabled,
            self.community_auto_publish_enabled,
            self.chat_bot_enabled,
            self.chat_base_url,
        )
