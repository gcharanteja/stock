"""
scheduler.py — APScheduler jobs: portfolio price checker + Nifty screener
"""
import time as time_module
from datetime import datetime, time
from typing import Dict, List

import yfinance as yf
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import (
    IST,
    MARKET_OPEN,
    MARKET_CLOSE,
    NIFTY_50,
    NIFTY_100,
    NIFTY_3M_DECLINE_THRESHOLD,
    NIFTY_6M_DECLINE_THRESHOLD,
    NIFTY_1Y_DECLINE_THRESHOLD,
)
from app.database import PortfolioModel, ScreenerResultModel, get_db_session
from app.schemas import DeclinedStock, NiftyScreenerResult, PriceAlert
from app.stock_data import calculate_potential_return, get_cached_stock_data, normalize_symbol  # ✅ removed to_yahoo_symbol

scheduler = BackgroundScheduler()

# In-memory state for async screener results
nifty_screener_results: Dict[str, dict] = {}
nifty_screener_running: Dict[str, bool] = {}


def is_market_open() -> bool:
    now_ist      = datetime.now(IST)
    current_time = now_ist.time()
    if now_ist.weekday() >= 5:
        return False
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def check_portfolio_prices():
    """Run every 60 min during market hours — fires email alerts if price triggers hit."""
    if not is_market_open():
        print(f"Market closed — skipping at {datetime.now(IST)}")
        return

    with get_db_session() as db:
        items = db.query(PortfolioModel).all()
        if not items:
            return

        alerts: List[PriceAlert] = []
        for item in items:
            try:
                data = get_cached_stock_data(item.symbol)
                cp   = data["current_price"]
                h52  = data["week_52_high"]
                l52  = data["week_52_low"]
                h100 = data["week_100_high"]

                if h52  and abs(cp - h52)  / h52  < 0.01:
                    alerts.append(PriceAlert(symbol=item.symbol, buy_price=item.buy_price, current_price=cp, alert_type="52_week_high_reached",  high_price=h52,  low_price=None, target_price=None, potential_return=calculate_potential_return(item.buy_price, h52)))
                if h100 and abs(cp - h100) / h100 < 0.01:
                    alerts.append(PriceAlert(symbol=item.symbol, buy_price=item.buy_price, current_price=cp, alert_type="100_week_high_reached", high_price=h100, low_price=None, target_price=None, potential_return=calculate_potential_return(item.buy_price, h100)))
                if l52  and abs(cp - l52)  / l52  < 0.01:
                    alerts.append(PriceAlert(symbol=item.symbol, buy_price=item.buy_price, current_price=cp, alert_type="52_week_low_near",      high_price=None, low_price=l52, target_price=None, potential_return=None))
                if item.target_price and cp >= item.target_price:
                    alerts.append(PriceAlert(symbol=item.symbol, buy_price=item.buy_price, current_price=cp, alert_type="target_price_reached",  high_price=None, low_price=None, target_price=item.target_price, potential_return=calculate_potential_return(item.buy_price, cp)))

            except Exception as e:
                print(f"Error checking {item.symbol}: {e}")

        if alerts:
            # import here to avoid circular import
            from app.smtp import send_email_notification
            send_email_notification(alerts)
        else:
            print(f"Price check done at {datetime.now(IST)} — no alerts")


def screen_nifty_stocks(
    index: str = "NIFTY100",
    months_3_decline: float = 25.0,
    months_6_decline: float = 40.0,
    year_1_decline: float   = 48.0,
) -> NiftyScreenerResult:
    """Scan NIFTY50/100 for significant declines and persist results."""
    constituents    = NIFTY_50 if index == "NIFTY50" else NIFTY_100
    declined_stocks: List[DeclinedStock] = []
    scanned = 0

    with get_db_session() as db:
        for symbol in constituents:
            try:
                time_module.sleep(0.5)
                ticker = yf.Ticker(to_yahoo_symbol(symbol))
                try:
                    info = ticker.info or {}
                except Exception:
                    info = {}

                cp     = info.get("currentPrice") or info.get("previousClose")
                sector = info.get("sector")
                if not cp:
                    continue

                def calc_decline(hist):
                    if hist.empty:
                        return None
                    p = hist["Close"].iloc[0]
                    return round(((p - cp) / p) * 100, 2) if p > 0 else None

                d3m = calc_decline(ticker.history(period="3mo", auto_adjust=False))
                d6m = calc_decline(ticker.history(period="6mo", auto_adjust=False))
                d1y = calc_decline(ticker.history(period="1y",  auto_adjust=False))
                scanned += 1

                alert_type = None
                if d3m and d3m >= months_3_decline:
                    alert_type = "3_month_decline"
                elif d6m and d6m >= months_6_decline:
                    alert_type = "6_month_decline"
                elif d1y and d1y >= year_1_decline:
                    alert_type = "1_year_decline"

                if alert_type:
                    declined_stocks.append(DeclinedStock(
                        symbol=symbol, current_price=round(cp, 2), sector=sector,
                        decline_3m=d3m, decline_6m=d6m, decline_1y=d1y, alert_type=alert_type,
                    ))
                    try:
                        db.add(ScreenerResultModel(
                            index_name=index, symbol=symbol, current_price=round(cp, 2),
                            sector=sector, decline_3m=d3m, decline_6m=d6m, decline_1y=d1y,
                            alert_type=alert_type, thresholds_3m=months_3_decline,
                            thresholds_6m=months_6_decline, thresholds_1y=year_1_decline,
                        ))
                        db.commit()
                    except Exception:
                        db.rollback()

            except Exception as e:
                print(f"Error processing {symbol}: {e}")

    print(f"Screening complete: {scanned} scanned, {len(declined_stocks)} declined")
    return NiftyScreenerResult(
        index=index, total_stocks=len(constituents), scanned=scanned,
        declined_stocks=declined_stocks,
        thresholds={"3_month": months_3_decline, "6_month": months_6_decline, "1_year": year_1_decline},
    )


def check_nifty_opportunities(index: str = "NIFTY100"):
    if not is_market_open():
        return
    try:
        result = screen_nifty_stocks(
            index=index,
            months_3_decline=NIFTY_3M_DECLINE_THRESHOLD,
            months_6_decline=NIFTY_6M_DECLINE_THRESHOLD,
            year_1_decline=NIFTY_1Y_DECLINE_THRESHOLD,
        )
        if result.declined_stocks:
            from app.smtp import send_email_notification
            send_email_notification([], result.declined_stocks)
    except Exception as e:
        print(f"Nifty screener error: {e}")
