from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Settings:
    project_root: Path = field(default_factory=lambda: Path.cwd())

    data_input_glob: str = os.getenv("DATA_INPUT_GLOB", "data/raw/*")
    default_country: str = os.getenv("DEFAULT_COUNTRY", "CA")
    default_language: str = os.getenv("DEFAULT_LANGUAGE", "en")
    dry_run: bool = _to_bool(os.getenv("DRY_RUN"), default=True)

    smtp_host: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_use_tls: bool = _to_bool(os.getenv("SMTP_USE_TLS"), default=True)
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from_email: str = os.getenv("SMTP_FROM_EMAIL", "")
    smtp_from_name: str = os.getenv("SMTP_FROM_NAME", "")
    reply_to: str = os.getenv("REPLY_TO", "")
    attachment_path: str = os.getenv("ATTACHMENT_PATH", "")
    send_rate_seconds: float = float(os.getenv("SEND_RATE_SECONDS", "3"))
    max_emails_per_run: int = int(os.getenv("MAX_EMAILS_PER_RUN", "20"))

    allowed_recipient_domains: str = os.getenv("ALLOWED_RECIPIENT_DOMAINS", "")
    blocked_recipient_domains: str = os.getenv("BLOCKED_RECIPIENT_DOMAINS", "")

    send_history_path: str = os.getenv("SEND_HISTORY_PATH", "logs/send_history.csv")
    learning_feedback_path: str = os.getenv(
        "LEARNING_FEEDBACK_PATH",
        "logs/learning_feedback.csv",
    )
    max_attempts_per_person: int = int(os.getenv("MAX_ATTEMPTS_PER_PERSON", "3"))
    max_retries_same_soft_bounce: int = int(
        os.getenv("MAX_RETRIES_SAME_SOFT_BOUNCE", "2")
    )

    imap_host: str = os.getenv("IMAP_HOST", "imap.gmail.com")
    imap_username: str = os.getenv("IMAP_USERNAME", "")
    imap_password: str = os.getenv("IMAP_PASSWORD", "")

    @property
    def input_paths(self) -> list[Path]:
        return sorted(self.project_root.glob(self.data_input_glob))

    @property
    def processed_dir(self) -> Path:
        path = self.project_root / "data" / "processed"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def logs_dir(self) -> Path:
        path = self.project_root / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def attachment(self) -> Path | None:
        if not self.attachment_path.strip():
            return None
        return Path(self.attachment_path).expanduser().resolve()


def get_settings() -> Settings:
    return Settings()