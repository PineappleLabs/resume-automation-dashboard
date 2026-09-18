from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

INGEST_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = INGEST_ROOT.parent.parent
PIPELINE_ROOT = REPO_ROOT / "packages" / "resume_pipeline"
SECRETS_DIR = INGEST_ROOT / "secrets"

load_dotenv(INGEST_ROOT / ".env")
load_dotenv(PIPELINE_ROOT / ".env")  # shared ANTHROPIC_API_KEY, same fallback as services/api


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    anthropic_model: str
    classification_confidence_threshold: float
    target_location_description: str
    interview_confidence_threshold: float
    poll_interval_minutes: int
    full_resync_days: int
    client_secret_path: Path
    token_path: Path


def _require(name: str, hint: str = "") -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set.{(' ' + hint) if hint else ''}")
    return value


def _load_settings() -> Settings:
    return Settings(
        anthropic_api_key=_require(
            "ANTHROPIC_API_KEY", hint=f"Set it in {PIPELINE_ROOT / '.env'}"
        ),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
        classification_confidence_threshold=float(
            os.environ.get("CLASSIFICATION_CONFIDENCE_THRESHOLD", "0.75")
        ),
        target_location_description=os.environ.get(
            "TARGET_LOCATION_DESCRIPTION", "Atlanta, Georgia, or fully remote"
        ),
        interview_confidence_threshold=float(
            os.environ.get("INTERVIEW_CONFIDENCE_THRESHOLD", "0.75")
        ),
        poll_interval_minutes=int(os.environ.get("POLL_INTERVAL_MINUTES", "30")),
        full_resync_days=int(os.environ.get("FULL_RESYNC_DAYS", "7")),
        client_secret_path=SECRETS_DIR / "client_secret.json",
        token_path=SECRETS_DIR / "token.json",
    )


settings = _load_settings()
