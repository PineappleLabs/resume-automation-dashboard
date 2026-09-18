from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .routers import auth, interview_events, leads, tailor
from .security import NotAuthenticated

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Job Search Dashboard")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key, same_site="lax")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.exception_handler(NotAuthenticated)
def _redirect_to_login(request: Request, exc: NotAuthenticated) -> RedirectResponse:
    return RedirectResponse(url=f"/login?next={request.url.path}", status_code=303)


@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url="/leads", status_code=303)


app.include_router(auth.router)
app.include_router(leads.router)
app.include_router(interview_events.router)
app.include_router(tailor.router)
