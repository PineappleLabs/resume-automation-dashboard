from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DB_PACKAGE_ROOT = Path(__file__).resolve().parent.parent

# Explicit path, not a bare load_dotenv() -- this must resolve correctly regardless of
# which service's CWD is importing it (services/api, services/ingest_gmail, alembic, ...).
load_dotenv(DB_PACKAGE_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    database_url: str


def _require(name: str, hint: str = "") -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set.{(' ' + hint) if hint else ''}")
    return value


settings = Settings(
    database_url=_require("DATABASE_URL", hint=f"Set it in {DB_PACKAGE_ROOT / '.env'}"),
)
