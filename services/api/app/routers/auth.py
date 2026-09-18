from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ..security import check_password
from ..templating import templates

router = APIRouter(tags=["auth"])


@router.get("/login")
def login_form(request: Request, next: str = "/leads") -> object:
    if request.session.get("authenticated"):
        return RedirectResponse(url=next, status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"next": next, "error": False}
    )


@router.post("/login")
def login_submit(request: Request, password: str = Form(...), next: str = Form("/leads")) -> object:
    if not check_password(password):
        return templates.TemplateResponse(
            request, "login.html", {"next": next, "error": True}, status_code=401
        )
    request.session["authenticated"] = True
    return RedirectResponse(url=next or "/leads", status_code=303)


@router.post("/logout")
def logout(request: Request) -> object:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
