"""
routes/scheduler_routes.py — /scheduler endpoints
"""
from datetime import datetime

from fastapi import APIRouter

from app.config import IST
from app.scheduler import (
    check_portfolio_prices,
    is_market_open,
    scheduler,
)

router = APIRouter(prefix="/scheduler")


@router.post("/start")
def start_scheduler():
    scheduler.add_job(check_portfolio_prices, "interval", minutes=60, id="price_checker", replace_existing=True)
    return {"message": "Scheduler started — price checker runs every 60 min", "status": "running"}


@router.post("/stop")
def stop_scheduler():
    try:
        scheduler.remove_job("price_checker")
    except Exception:
        pass
    return {"message": "Scheduler stopped", "status": "stopped"}


@router.get("/status")
def scheduler_status():
    jobs = scheduler.get_jobs()
    return {
        "status": "running" if jobs else "stopped",
        "market_open": is_market_open(),
        "ist_time": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"),
        "jobs": [str(j) for j in jobs],
    }


@router.post("/check-now")
def check_now():
    check_portfolio_prices()
    return {"message": "Price check completed"}
