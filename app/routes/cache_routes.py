"""
routes/cache_routes.py — /cache endpoints
"""
from typing import Optional

from fastapi import APIRouter

from app.stock_data import cache_info, clear_stock_cache

router = APIRouter(prefix="/cache")


@router.post("/clear")
def clear_cache(symbol: Optional[str] = None):
    clear_stock_cache(symbol)
    return {"message": f"Cache cleared for {'all stocks' if not symbol else symbol}"}


@router.get("/status")
def get_cache_status():
    return cache_info()
