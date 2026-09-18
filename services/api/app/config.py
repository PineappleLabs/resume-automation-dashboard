from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

API_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = API_ROOT.parent.parent
PIPELINE_ROOT = REPO_ROOT / "packages" / "resume_pipeline"

# Load services/api's own secrets first, then fall back to the pipeline's .env so
# ANTHROPIC_API_KEY is set in this process's environment before resume_pipeline.select
# looks for it -- load_dotenv() defaults to override=False, so this never clobbers a
# value already set above, and the key is never duplicated across files. Not required
# here: resume_pipeline.select raises its own clear error if it's still missing, and
# only the /tailor route needs it, so nothing else (migrations, other routes) should
# fail to start over it.
load_dotenv(API_ROOT / ".env")
load_dotenv(PIPELINE_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    session_secret_key: str
    dashboard_password: str
    host: str
    port: int
    pipeline_jobs_dir: Path


def _require(name: str, hint: str = "") -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set.{(' ' + hint) if hint else ''}")
    return value


def _load_settings() -> Settings:
    return Settings(
        session_secret_key=_require("SESSION_SECRET_KEY"),
        dashboard_password=_require("DASHBOARD_PASSWORD"),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        pipeline_jobs_dir=PIPELINE_ROOT / "jobs",
    )


settings = _load_settings()
