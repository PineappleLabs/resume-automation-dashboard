from __future__ import annotations

import hmac

from fastapi import Request

from .config import settings


class NotAuthenticated(Exception):
    pass


def check_password(submitted: str) -> bool:
    return hmac.compare_digest(submitted.encode(), settings.dashboard_password.encode())


def require_login(request: Request) -> None:
    if not request.session.get("authenticated"):
        raise NotAuthenticated()
