"""Pembuatan aplikasi FastAPI: REST, WebSocket, dan web statis (PWA)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .auth import Auth
from .routes import public, router
from .ws import router as ws_router


def create_app(ctx) -> FastAPI:
    app = FastAPI(title="Guardian Pocket Device", version=__version__, docs_url="/api/docs",
                  openapi_url="/api/openapi.json", redoc_url=None)
    app.state.ctx = ctx
    app.state.auth = Auth(ctx.cfg.env["WEB_PASSWORD_HASH"], ctx.cfg.env["SESSION_SECRET"],
                          ctx.cfg.path(ctx.cfg.get("storage.db", "data/guardian.db")).parent)
    app.include_router(public)
    app.include_router(router)
    app.include_router(ws_router)

    web_dir = ctx.cfg.path("web")

    @app.get("/sw.js", include_in_schema=False)
    async def service_worker():
        # dilayani dari root agar scope service worker mencakup seluruh situs
        return FileResponse(web_dir / "sw.js", media_type="application/javascript",
                            headers={"Cache-Control": "no-cache"})

    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app
