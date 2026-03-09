"""
main.py — Entry point. Wires together the app, routers, startup/shutdown.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import VAULT_API_URL, get_from_vault
from app.database import init_db
from app.scheduler import scheduler
from app.stock_data import cache_info
from app.routes.portfolio import router as portfolio_router
from app.routes.scheduler_routes import router as scheduler_router
from app.routes.nifty_routes import router as nifty_router
from app.routes.cache_routes import router as cache_router

app = FastAPI(title="Stock Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(portfolio_router)
app.include_router(scheduler_router)
app.include_router(nifty_router)
app.include_router(cache_router)


# ── Lifecycle ──────────────────────────────────────────────────────────────────
@app.on_event("startup")
def startup_event():
    init_db()
    if not scheduler.running:
        scheduler.start()


@app.on_event("shutdown")
def shutdown_event():
    if scheduler.running:
        scheduler.shutdown(wait=False)


# ── Root ───────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "message": "Stock Dashboard API",
        "vault_url": VAULT_API_URL,
        "vault_connected": bool(get_from_vault("SMTP_HOST")),
        **cache_info(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, timeout_keep_alive=120)
