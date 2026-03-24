"""FastAPI web dashboard — HTML pages + JSON API."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"


def create_app(
    database,
    secret_key: str = "agegate-default-secret",
    master_api_key: str = "",
) -> FastAPI:
    """Create the FastAPI dashboard application.

    Args:
        database: Database instance (shared with the bot).
        secret_key: Session signing secret.
        master_api_key: Optional master key for helpdesk access.

    Returns:
        Configured FastAPI app.
    """
    app = FastAPI(title="AgeGate Dashboard", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    serializer = URLSafeSerializer(secret_key)

    # ── Session Helpers ────────────────────────────────────────

    def set_session(response: Response, guild: dict[str, Any]) -> None:
        token = serializer.dumps({"guild_id": guild["guild_id"]})
        response.set_cookie("agegate_session", token, httponly=True, max_age=86400)

    def get_session_guild(request: Request) -> dict[str, Any] | None:
        token = request.cookies.get("agegate_session")
        if not token:
            return None
        try:
            data = serializer.loads(token)
            return data
        except Exception:
            return None

    async def resolve_guild(request: Request) -> dict[str, Any] | None:
        session = get_session_guild(request)
        if not session:
            return None
        guild_id = session.get("guild_id")
        if not guild_id:
            return None
        return await database.get_guild_settings(guild_id)

    # ── HTML Routes ────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def login_page(request: Request):
        guild = await resolve_guild(request)
        if guild:
            return RedirectResponse("/dashboard", status_code=302)
        return templates.TemplateResponse(
            "login.html", {"request": request, "guild": None, "error": None}
        )

    @app.post("/login")
    async def login_submit(request: Request):
        form = await request.form()
        api_key = form.get("api_key", "").strip()

        if not api_key:
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "guild": None, "error": "API key is required."},
            )

        # Check master key
        if master_api_key and api_key == master_api_key:
            response = RedirectResponse("/dashboard", status_code=302)
            token = serializer.dumps({"guild_id": 0, "master": True})
            response.set_cookie("agegate_session", token, httponly=True, max_age=86400)
            return response

        guild = await database.get_guild_by_api_key(api_key)
        if not guild:
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "guild": None, "error": "Invalid API key."},
            )

        response = RedirectResponse("/dashboard", status_code=302)
        set_session(response, guild)
        return response

    @app.get("/logout")
    async def logout():
        response = RedirectResponse("/", status_code=302)
        response.delete_cookie("agegate_session")
        return response

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request):
        guild = await resolve_guild(request)
        if not guild:
            return RedirectResponse("/", status_code=302)

        guild_id = guild["guild_id"]
        stats = await database.get_guild_stats(guild_id)
        members = await database.get_guild_members(guild_id)
        audit_log = await database.get_audit_log(guild_id, limit=10)

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "guild": guild,
                "stats": stats,
                "members": members,
                "audit_log": audit_log,
            },
        )

    @app.get("/dashboard/search", response_class=HTMLResponse)
    async def search_page(request: Request, q: str = ""):
        guild = await resolve_guild(request)
        if not guild:
            return RedirectResponse("/", status_code=302)

        results = None
        if q.strip():
            # Search by agreement ID first
            agreement = await database.get_agreement_by_id(q.strip())
            if agreement:
                return RedirectResponse(
                    f"/dashboard/agreement/{agreement['agreement_id']}",
                    status_code=302,
                )
            results = await database.search_users(q.strip())

        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "guild": guild,
                "query": q,
                "results": results,
            },
        )

    @app.get("/dashboard/user/{user_id}", response_class=HTMLResponse)
    async def user_detail(request: Request, user_id: int):
        guild = await resolve_guild(request)
        if not guild:
            return RedirectResponse("/", status_code=302)

        verification = await database.get_verification(user_id)
        agreement = await database.get_agreement(user_id)
        guilds = await database.get_user_guilds(user_id)
        audit_entries = await database.get_audit_log(
            guild_id=guild["guild_id"], limit=20
        )
        # Filter audit entries for this user
        audit_entries = [e for e in audit_entries if e.get("user_id") == user_id]

        return templates.TemplateResponse(
            "user_detail.html",
            {
                "request": request,
                "guild": guild,
                "user_id": user_id,
                "verification": verification,
                "agreement": agreement,
                "guilds": guilds,
                "audit_entries": audit_entries,
            },
        )

    @app.get("/dashboard/agreement/{agreement_id}", response_class=HTMLResponse)
    async def agreement_detail(request: Request, agreement_id: str):
        guild = await resolve_guild(request)
        if not guild:
            return RedirectResponse("/", status_code=302)

        agreement = await database.get_agreement_by_id(agreement_id)
        if not agreement:
            return HTMLResponse("<h1>Agreement not found</h1>", status_code=404)

        return templates.TemplateResponse(
            "agreement.html",
            {
                "request": request,
                "guild": guild,
                "agreement": agreement,
            },
        )

    # ── JSON API ───────────────────────────────────────────────

    async def _api_auth(request: Request) -> dict[str, Any] | None:
        api_key = request.headers.get("X-API-Key", "")
        if not api_key:
            return None
        if master_api_key and api_key == master_api_key:
            return {"guild_id": 0, "master": True}
        guild = await database.get_guild_by_api_key(api_key)
        return guild

    @app.get("/api/v1/status")
    async def api_status():
        return {"status": "ok", "service": "agegate", "version": "1.0.0"}

    @app.get("/api/v1/user/{user_id}")
    async def api_user(request: Request, user_id: int):
        guild = await _api_auth(request)
        if not guild:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        verification = await database.get_verification(user_id)
        agreement = await database.get_agreement(user_id)
        guilds = await database.get_user_guilds(user_id)

        return {
            "user_id": user_id,
            "verification": verification,
            "agreement": _sanitize_agreement(agreement),
            "guilds": guilds,
        }

    @app.get("/api/v1/agreement/{agreement_id}")
    async def api_agreement(request: Request, agreement_id: str):
        guild = await _api_auth(request)
        if not guild:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        agreement = await database.get_agreement_by_id(agreement_id)
        if not agreement:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return agreement

    @app.get("/api/v1/guild/members")
    async def api_guild_members(request: Request):
        guild = await _api_auth(request)
        if not guild:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        guild_id = guild.get("guild_id", 0)
        if guild_id == 0:
            return JSONResponse(
                {"error": "Master key cannot list guild members"}, status_code=400
            )
        members = await database.get_guild_members(guild_id)
        return members

    @app.get("/api/v1/guild/stats")
    async def api_guild_stats(request: Request):
        guild = await _api_auth(request)
        if not guild:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        guild_id = guild.get("guild_id", 0)
        if guild_id == 0:
            return await database.get_global_stats()
        return await database.get_guild_stats(guild_id)

    def _sanitize_agreement(agreement: dict | None) -> dict | None:
        if not agreement:
            return None
        # Don't include full document text in user endpoint
        return {
            k: v for k, v in agreement.items() if k != "document_text"
        }

    return app
