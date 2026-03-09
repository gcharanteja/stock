"""
stock_data.py — AngelOne SmartAPI fetching + in-memory 1-hour cache
Uses AngelOne symbol master JSON for accurate token lookup.
"""
import io
import time as time_module
from datetime import datetime, timedelta
from typing import Dict, Optional

import pyotp
import requests
from fastapi import HTTPException
from SmartApi import SmartConnect

from app.config import get_from_vault


# ============== SYMBOL MASTER ==============

_symbol_master: Dict[str, str] = {}
_master_loaded_at: float = 0
MASTER_TTL_SECONDS = 3600 * 12

SYMBOL_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"


def _load_symbol_master():
    global _symbol_master, _master_loaded_at
    now = time_module.time()
    if _symbol_master and (now - _master_loaded_at) < MASTER_TTL_SECONDS:
        return
    print("📥 Loading AngelOne symbol master...")
    try:
        resp = requests.get(SYMBOL_MASTER_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        master = {}
        for item in data:
            if item.get("exch_seg") == "NSE" and item.get("symbol", "").endswith("-EQ"):
                clean = item["symbol"].replace("-EQ", "").upper()
                master[clean] = item["token"]
        _symbol_master    = master
        _master_loaded_at = now
        print(f"✅ Symbol master loaded — {len(master)} NSE EQ symbols")
    except Exception as e:
        print(f"❌ Symbol master load failed: {e}")
        raise HTTPException(status_code=502, detail=f"Could not load AngelOne symbol master: {e}")


def _get_token(symbol: str) -> str:
    _load_symbol_master()
    token = _symbol_master.get(symbol.upper())
    if not token:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found in AngelOne NSE master")
    return token


def _get_trading_symbol(symbol: str) -> str:
    return f"{symbol.upper()}-EQ"


# ============== ANGEL ONE AUTH ==============

_angel_session: Optional[SmartConnect] = None
_session_created_at: float = 0
SESSION_TTL_SECONDS = 3600 * 8


def _get_angel_session() -> SmartConnect:
    global _angel_session, _session_created_at
    now = time_module.time()
    if _angel_session and (now - _session_created_at) < SESSION_TTL_SECONDS:
        return _angel_session

    print("🔐 Creating new AngelOne session...")
    api_key  = get_from_vault("API_KEY")
    username = get_from_vault("USERNAME")
    password = get_from_vault("PASSWORD")
    totp_key = get_from_vault("TOTP_KEY")

    if not all([api_key, username, password, totp_key]):
        raise HTTPException(status_code=500, detail="AngelOne credentials missing from vault")

    totp = pyotp.TOTP(totp_key).now()
    obj  = SmartConnect(api_key=api_key)
    try:
        data = obj.generateSession(username, password, totp)
        if not data or data.get("status") is False:
            raise HTTPException(
                status_code=401,
                detail=f"AngelOne login failed: {data.get('message','unknown') if data else 'no response'}"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AngelOne session error: {str(e)}")

    _angel_session      = obj
    _session_created_at = now
    print("✅ AngelOne session created")
    return _angel_session


# ============== RATE LIMIT GUARD ==============

_last_candle_call: float = 0
CANDLE_MIN_INTERVAL = 1.0  # ✅ minimum 1 second between candle calls


def _rate_limited_candle(obj: SmartConnect, params: dict) -> dict:
    """Call getCandleData with a minimum gap to avoid rate limiting."""
    global _last_candle_call
    now     = time_module.time()
    elapsed = now - _last_candle_call
    if elapsed < CANDLE_MIN_INTERVAL:
        time_module.sleep(CANDLE_MIN_INTERVAL - elapsed)
    result = obj.getCandleData(params)
    _last_candle_call = time_module.time()
    return result


# ============== SYMBOL HELPERS ==============

def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


# ============== SECTOR LOOKUP (NSE API) ==============

_sector_cache: Dict[str, str] = {}
_sector_loaded_at: float = 0
SECTOR_TTL_SECONDS = 3600 * 24  # refresh once a day

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com",
}


def _get_sector(symbol: str) -> Optional[str]:
    """Fetch sector for a symbol from NSE India API."""
    if symbol in _sector_cache:
        return _sector_cache[symbol]

    try:
        # NSE needs a session cookie first
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)

        url  = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
        resp = session.get(url, headers=NSE_HEADERS, timeout=10)

        if resp.status_code == 200:
            data   = resp.json()
            sector = data.get("industryInfo", {}).get("industry") \
                  or data.get("industryInfo", {}).get("sector") \
                  or data.get("metadata", {}).get("industry")
            if sector:
                _sector_cache[symbol] = sector
                return sector
    except Exception as e:
        print(f"⚠️ Sector fetch failed for {symbol}: {e}")

    _sector_cache[symbol] = "Unknown"
    return "Unknown"


# ============== FETCH ==============

def fetch_stock_data(symbol: str) -> dict:
    """Fetch live data from AngelOne SmartAPI for a single NSE symbol."""
    sym   = normalize_symbol(symbol)
    obj   = _get_angel_session()
    token = _get_token(sym)
    tsym  = _get_trading_symbol(sym)

    print(f"🔍 {sym} → token={token}, tradingSymbol={tsym}")

    # ── Live Quote ─────────────────────────────────────────────────────────────
    try:
        quote_resp = obj.ltpData("NSE", tsym, token)
        if not quote_resp or not quote_resp.get("status"):
            raise HTTPException(
                status_code=502,
                detail=f"Quote failed for {sym}: {quote_resp.get('message','unknown') if quote_resp else 'no response'}"
            )
        ltp = float(quote_resp["data"]["ltp"])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Quote error for {sym}: {str(e)}")

    # ── Candle history — 52W and 100W highs/lows ───────────────────────────────
    week_52_high  = None
    week_52_low   = None
    week_100_high = None

    now_dt  = datetime.now()
    to_dt   = now_dt.strftime("%Y-%m-%d %H:%M")
    from_1y = (now_dt - timedelta(days=365)).strftime("%Y-%m-%d %H:%M")
    from_2y = (now_dt - timedelta(days=730)).strftime("%Y-%m-%d %H:%M")

    params_1y = {
        "exchange":    "NSE",
        "symboltoken": token,
        "interval":    "ONE_DAY",
        "fromdate":    from_1y,
        "todate":      to_dt,
    }
    params_2y = {**params_1y, "fromdate": from_2y}

    try:
        candles_1y = _rate_limited_candle(obj, params_1y)
        if candles_1y and candles_1y.get("status") and candles_1y.get("data"):
            highs        = [c[2] for c in candles_1y["data"]]
            lows         = [c[3] for c in candles_1y["data"]]
            week_52_high = round(max(highs), 2)
            week_52_low  = round(min(lows),  2)
    except Exception as e:
        print(f"⚠️ 1Y candle failed for {sym}: {e}")

    try:
        candles_2y = _rate_limited_candle(obj, params_2y)
        if candles_2y and candles_2y.get("status") and candles_2y.get("data"):
            highs_2y      = [c[2] for c in candles_2y["data"]]
            week_100_high = round(max(highs_2y), 2)
    except Exception as e:
        print(f"⚠️ 2Y candle failed for {sym}: {e}")

    # ── Sector from NSE ────────────────────────────────────────────────────────
    sector = _get_sector(sym)   # ✅ fetched from NSE India API
    print(f"🏭 {sym} sector → {sector}")

    if ltp is None:
        raise HTTPException(status_code=404, detail=f"Could not fetch usable data for: {sym}")

    return {
        "symbol":           sym,
        "current_price":    round(ltp, 2),
        "week_52_high":     week_52_high,
        "week_52_low":      week_52_low,
        "week_100_high":    week_100_high,
        "sector":           sector,          # ✅ now populated
        "dividend_yield":   None,
        "dividend_history": [],
    }


# ============== CACHE LAYER ==============

_stock_cache: Dict[str, dict]       = {}
_cache_timestamps: Dict[str, float] = {}
CACHE_TTL_SECONDS = 3600  # 1 hour


def get_cached_stock_data(symbol: str) -> dict:
    """Return cached data if < 1 hour old, else fetch fresh from AngelOne."""
    now = time_module.time()
    age = now - _cache_timestamps.get(symbol, 0)

    if symbol in _stock_cache and age < CACHE_TTL_SECONDS:
        print(f"📦 Cache hit for {symbol} (age {int(age)}s)")
        return _stock_cache[symbol]

    print(f"🌐 Fetching fresh data for {symbol} via AngelOne")
    try:
        data = fetch_stock_data(symbol)
        _stock_cache[symbol]      = data
        _cache_timestamps[symbol] = now
        return data
    except Exception as e:
        if symbol in _stock_cache:
            print(f"⚠️ Error — returning stale cache for {symbol}: {e}")
            return _stock_cache[symbol]
        raise


def clear_stock_cache(symbol: str = None):
    if symbol:
        _stock_cache.pop(symbol, None)
        _cache_timestamps.pop(symbol, None)
    else:
        _stock_cache.clear()
        _cache_timestamps.clear()


def cache_info() -> dict:
    return {
        "cache_size":     len(_stock_cache),
        "cached_symbols": list(_stock_cache.keys()),
    }


def calculate_potential_return(buy_price: float, high_price: float) -> float:
    if not buy_price or buy_price <= 0 or not high_price:
        return 0.0
    return round(((high_price - buy_price) / buy_price) * 100, 2)
