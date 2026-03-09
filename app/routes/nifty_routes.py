"""
routes/nifty_routes.py — /nifty/screen and /nifty/alert endpoints
"""
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException

from app.config import (
    NIFTY_3M_DECLINE_THRESHOLD,
    NIFTY_6M_DECLINE_THRESHOLD,
    NIFTY_1Y_DECLINE_THRESHOLD,
)
from app.scheduler import (
    check_nifty_opportunities,
    nifty_screener_results,
    nifty_screener_running,
    scheduler,
    screen_nifty_stocks,
)
from app.schemas import NiftyScreenerInput
import app.config as cfg
from app.stock_data import calculate_potential_return, get_cached_stock_data, normalize_symbol  # ✅ no to_yahoo_symbol

router = APIRouter(prefix="/nifty")


def _run_screener(index, m3, m6, y1):
    try:
        nifty_screener_running[index] = True
        result = screen_nifty_stocks(index, m3, m6, y1)
        nifty_screener_results[index] = result.model_dump()
    except Exception as e:
        nifty_screener_results[index] = {"error": str(e)}
    finally:
        nifty_screener_running[index] = False


@router.post("/screen")
def screen_nifty(input_data: NiftyScreenerInput):
    threading.Thread(target=_run_screener, args=(
        input_data.index, input_data.months_3_decline,
        input_data.months_6_decline, input_data.year_1_decline,
    )).start()
    return {
        "message": f"Screener started for {input_data.index}",
        "status": "running",
        "check_status_at": f"/nifty/screen/status/{input_data.index}",
    }


@router.get("/screen/status/{index}")
def get_screener_status(index: str):
    if index not in ["NIFTY50", "NIFTY100"]:
        raise HTTPException(status_code=400, detail="Index must be NIFTY50 or NIFTY100")
    if nifty_screener_running.get(index):
        return {"status": "running"}
    if index in nifty_screener_results:
        return {"status": "completed", **nifty_screener_results[index]}
    return {"status": "not_started"}


@router.get("/screen/{index}")
def screen_nifty_quick(
    index: str,
    months_3_decline: Optional[float] = None,
    months_6_decline: Optional[float] = None,
    year_1_decline:   Optional[float] = None,
):
    if index not in ["NIFTY50", "NIFTY100"]:
        raise HTTPException(status_code=400, detail="Index must be NIFTY50 or NIFTY100")
    m3 = months_3_decline or cfg.NIFTY_3M_DECLINE_THRESHOLD
    m6 = months_6_decline or cfg.NIFTY_6M_DECLINE_THRESHOLD
    y1 = year_1_decline   or cfg.NIFTY_1Y_DECLINE_THRESHOLD
    threading.Thread(target=_run_screener, args=(index, m3, m6, y1)).start()
    return {
        "message": f"Screener started for {index}",
        "status": "running",
        "thresholds": {"3_month": m3, "6_month": m6, "1_year": y1},
        "check_status_at": f"/nifty/screen/status/{index}",
    }


@router.post("/alert/enable")
def enable_nifty_alerts(input_data: NiftyScreenerInput):
    cfg.NIFTY_3M_DECLINE_THRESHOLD = input_data.months_3_decline
    cfg.NIFTY_6M_DECLINE_THRESHOLD = input_data.months_6_decline
    cfg.NIFTY_1Y_DECLINE_THRESHOLD = input_data.year_1_decline
    scheduler.add_job(
        lambda: check_nifty_opportunities(input_data.index),
        "interval", minutes=60, id="nifty_screener", replace_existing=True,
    )
    return {
        "message": f"Nifty {input_data.index} alerts enabled",
        "status": "running",
        "thresholds": {
            "3_month": input_data.months_3_decline,
            "6_month": input_data.months_6_decline,
            "1_year":  input_data.year_1_decline,
        },
    }


@router.post("/alert/disable")
def disable_nifty_alerts():
    try:
        scheduler.remove_job("nifty_screener")
    except Exception:
        pass
    return {"message": "Nifty alerts disabled", "status": "stopped"}
