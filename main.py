import os
import smtplib
import threading
from contextlib import contextmanager
from datetime import datetime, time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional

import pytz
import yfinance as yf
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

load_dotenv()

app = FastAPI(title="Stock Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Email configuration
SMTP_HOST = "smtp-relay.brevo.com"
SMTP_PORT = 587
SMTP_USER = "7f75f2003@smtp-brevo.com"
SMTP_PASS = os.getenv(
    "SMTP_PASS",
    "xsmtpsib-3492d6ce8135986bb1763490ca3dade1d613f143e92667571be5ffe39beefc05-TXHt0UO2QnS1ILBK",
)
FROM_EMAIL = "abcxyz123inf@gmail.com"
TO_EMAIL = "gattucharanteja8143@gmail.com"

# Indian market hours (IST)
IST = pytz.timezone("Asia/Kolkata")
MARKET_OPEN = time(9, 20)
MARKET_CLOSE = time(15, 20)

# Nifty screener configuration
NIFTY_3M_DECLINE_THRESHOLD = 25.0
NIFTY_6M_DECLINE_THRESHOLD = 40.0
NIFTY_1Y_DECLINE_THRESHOLD = 48.0

NIFTY_50 = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "SBIN", "BHARTIARTL",
    "ITC", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "BAJFINANCE", "TITAN",
    "SUNPHARMA", "ULTRACEMCO", "NESTLEIND", "BAJAJFINSV", "POWERGRID", "NTPC", "ONGC",
    "TATASTEEL", "M&M", "ADANIENT", "WIPRO", "JSWSTEEL", "TATAMOTORS", "GRASIM",
    "HCLTECH", "COALINDIA", "EICHERMOT", "BRITANNIA", "CIPLA", "HEROMOTOCO", "HINDALCO",
    "DRREDDY", "ADANIPORTS", "BPCL", "SHRIRAMFIN", "INDUSINDBK", "SBILIFE", "TATACONSUM",
    "DIVISLAB", "APOLLOHOSP", "BAJAJ-AUTO", "COFORGE", "PIDILITIND"
]

NIFTY_100 = NIFTY_50 + [
    "BEL", "TRENT", "OFSS", "POLYCAB", "VOLTAS", "TATAELXSI", "LUPIN", "SIEMENS",
    "BSE", "CUMMINSIND", "ABB", "THERMAX", "NH", "MAXHEALTH", "VARROC", "CROMPTON",
    "AUROPHARMA", "BANDHANBNK", "BANKBARODA", "CANBK", "CHOLAFIN", "DIXON", "GODREJCP",
    "HAVELLS", "ICICIPRULI", "IDFCFIRSTB", "INDIGO", "IRCTC", "JINDALSTEL", "LALPATHLAB",
    "MARICO", "METROPOLIS", "MOTHERSON", "NAUKRI", "OFSS", "PAGEIND", "PERSISTENT",
    "PETRONET", "PNB", "QUESS", "RBLBANK", "RECLTD", "SAIL", "SANOFI", "TATACOMM",
    "TATATECH", "TORNTPOWER", "UCOBANK", "UNIONBANK", "UPL", "ZYDUSLIFE"
]

scheduler = BackgroundScheduler()
nifty_screener_results: Dict[str, dict] = {}
nifty_screener_running: Dict[str, bool] = {}


@contextmanager
def get_db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def to_yahoo_symbol(symbol: str) -> str:
    cleaned = normalize_symbol(symbol)
    if cleaned.endswith((".NS", ".BO")):
        return cleaned
    return f"{cleaned}.NS"


def init_db():
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully")


@app.on_event("startup")
def startup_event():
    init_db()
    if not scheduler.running:
        scheduler.start()


@app.on_event("shutdown")
def shutdown_event():
    if scheduler.running:
        scheduler.shutdown(wait=False)


# SQLAlchemy Models
class PortfolioModel(Base):
    __tablename__ = "portfolio"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), unique=True, nullable=False, index=True)
    buy_price = Column(Float, nullable=False)
    target_price = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PriceHistoryModel(Base):
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    price_date = Column(DateTime, nullable=False)
    open_price = Column(Float)
    high_price = Column(Float)
    low_price = Column(Float)
    close_price = Column(Float)
    volume = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class ScreenerResultModel(Base):
    __tablename__ = "screener_results"

    id = Column(Integer, primary_key=True, index=True)
    index_name = Column(String(20), nullable=False)
    symbol = Column(String(20), nullable=False, index=True)
    current_price = Column(Float)
    sector = Column(String(100))
    decline_3m = Column(Float)
    decline_6m = Column(Float)
    decline_1y = Column(Float)
    alert_type = Column(String(50))
    thresholds_3m = Column(Float)
    thresholds_6m = Column(Float)
    thresholds_1y = Column(Float)
    scanned_at = Column(DateTime, default=datetime.utcnow, index=True)


class EmailLogModel(Base):
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    subject = Column(String(255))
    recipient = Column(String(255))
    alerts_count = Column(Integer)
    declined_count = Column(Integer)
    sent_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="sent")


class StockInput(BaseModel):
    symbol: str
    buy_price: float


class StockAddResponse(BaseModel):
    message: str
    symbol: str
    buy_price: float


class CustomAlertInput(BaseModel):
    target_price: float


class StockReturn(BaseModel):
    symbol: str
    buy_price: float
    current_price: Optional[float]
    week_52_high: Optional[float]
    week_52_low: Optional[float]
    week_100_high: Optional[float]
    potential_return_52w: Optional[float]
    potential_return_100w: Optional[float]
    dividend_yield: Optional[float]
    dividend_history: Optional[List[dict]]
    sector: Optional[str]
    target_price: Optional[float] = None
    error: Optional[str] = None


class PriceAlert(BaseModel):
    symbol: str
    buy_price: float
    current_price: float
    alert_type: str
    high_price: Optional[float]
    low_price: Optional[float]
    target_price: Optional[float]
    potential_return: Optional[float]


class DeleteResponse(BaseModel):
    message: str
    symbol: str


class SectorInfo(BaseModel):
    sector: str
    stocks: List[dict]
    total_stocks: int
    average_return: Optional[float]


class NiftyScreenerInput(BaseModel):
    index: str = "NIFTY100"
    months_3_decline: float = NIFTY_3M_DECLINE_THRESHOLD
    months_6_decline: float = NIFTY_6M_DECLINE_THRESHOLD
    year_1_decline: float = NIFTY_1Y_DECLINE_THRESHOLD


class DeclinedStock(BaseModel):
    symbol: str
    current_price: float
    sector: Optional[str]
    decline_3m: Optional[float]
    decline_6m: Optional[float]
    decline_1y: Optional[float]
    alert_type: str


class NiftyScreenerResult(BaseModel):
    index: str
    total_stocks: int
    scanned: int
    declined_stocks: List[DeclinedStock]
    thresholds: dict


def is_market_open() -> bool:
    now_ist = datetime.now(IST)
    current_time = now_ist.time()
    weekday = now_ist.weekday()
    if weekday >= 5:
        return False
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def calculate_potential_return(buy_price: float, high_price: float) -> float:
    if buy_price <= 0:
        return 0.0
    return round(((high_price - buy_price) / buy_price) * 100, 2)


def fetch_stock_data(symbol: str) -> dict:
    ticker_symbol = to_yahoo_symbol(symbol)
    ticker = yf.Ticker(ticker_symbol)

    try:
        info = ticker.info or {}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch stock info for {symbol}: {str(e)}")

    week_52_high = info.get("fiftyTwoWeekHigh")
    week_52_low = info.get("fiftyTwoWeekLow")
    current_price = info.get("currentPrice") or info.get("previousClose")
    sector = info.get("sector")
    dividend_yield = info.get("dividendYield")

    week_100_high = None
    try:
        hist = ticker.history(period="2y", auto_adjust=False)
        if not hist.empty and "High" in hist:
            week_100_high = round(float(hist["High"].max()), 2)
    except Exception:
        pass

    dividend_history = []
    try:
        dividends = ticker.dividends
        if dividends is not None and len(dividends) > 0:
            for date, amount in dividends.tail(5).items():
                dividend_history.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "amount": round(float(amount), 2),
                })
    except Exception:
        pass

    if week_52_high is None or current_price is None:
        raise HTTPException(
            status_code=404,
            detail=f"Could not fetch usable data for symbol: {symbol}"
        )

    return {
        "symbol": normalize_symbol(symbol),
        "current_price": round(float(current_price), 2),
        "week_52_high": round(float(week_52_high), 2),
        "week_52_low": round(float(week_52_low), 2) if week_52_low is not None else None,
        "week_100_high": week_100_high,
        "sector": sector,
        "dividend_yield": round(float(dividend_yield) * 100, 2) if dividend_yield is not None else None,
        "dividend_history": dividend_history,
    }


def send_email_notification(
    alerts: List[PriceAlert],
    declined_stocks: Optional[List[DeclinedStock]] = None
):
    if not alerts and not declined_stocks:
        return

    with get_db_session() as db:
        msg = MIMEMultipart()
        msg["From"] = FROM_EMAIL
        msg["To"] = TO_EMAIL

        if declined_stocks and alerts:
            msg["Subject"] = f"🚨 Stock Alert - {len(alerts)} Portfolio + {len(declined_stocks)} Nifty Stocks Down!"
        elif declined_stocks:
            msg["Subject"] = f"📉 Nifty Screener - {len(declined_stocks)} Stocks Down Significantly!"
        else:
            msg["Subject"] = f"Stock Alert - {len(alerts)} Alert(s)!"

        body = """
        <html>
        <body>
            <h2>Stock Price Alert</h2>
        """

        if alerts:
            body += """
            <h3 style="color: orange;">📊 Portfolio Alerts</h3>
            <p>The following stocks have triggered alerts:</p>
            <table border="1" style="border-collapse: collapse; width: 100%; margin-bottom: 20px;">
                <tr>
                    <th>Symbol</th>
                    <th>Buy Price</th>
                    <th>Current Price</th>
                    <th>Alert Type</th>
                    <th>Details</th>
                </tr>
            """
            for alert in alerts:
                details = ""
                if alert.alert_type == "52_week_high_reached":
                    details = f"52W High: Rs.{alert.high_price} | Return: +{alert.potential_return}%"
                elif alert.alert_type == "100_week_high_reached":
                    details = f"100W High: Rs.{alert.high_price} | Return: +{alert.potential_return}%"
                elif alert.alert_type == "52_week_low_near":
                    details = f"52W Low: Rs.{alert.low_price} | Buying Opportunity!"
                elif alert.alert_type == "target_price_reached":
                    details = f"Target: Rs.{alert.target_price} | Return: +{alert.potential_return}%"

                body += f"""
                <tr>
                    <td>{alert.symbol}</td>
                    <td>Rs.{alert.buy_price}</td>
                    <td>Rs.{alert.current_price}</td>
                    <td>{alert.alert_type.replace("_", " ").title()}</td>
                    <td>{details}</td>
                </tr>
                """
            body += "</table>"

        if declined_stocks:
            body += """
            <h3 style="color: red;">📉 Nifty Stocks - Buying Opportunities</h3>
            <p>The following Nifty stocks are down significantly:</p>
            <table border="1" style="border-collapse: collapse; width: 100%;">
                <tr>
                    <th>Symbol</th>
                    <th>Current Price</th>
                    <th>Sector</th>
                    <th>3M Decline</th>
                    <th>6M Decline</th>
                    <th>1Y Decline</th>
                </tr>
            """
            for stock in declined_stocks:
                body += f"""
                <tr>
                    <td style="font-weight: bold;">{stock.symbol}</td>
                    <td>Rs.{stock.current_price}</td>
                    <td>{stock.sector or 'N/A'}</td>
                    <td style="color: {'red' if stock.decline_3m else 'black'};">{"↓" + str(stock.decline_3m) + "%" if stock.decline_3m else "-"}</td>
                    <td style="color: {'red' if stock.decline_6m else 'black'};">{"↓" + str(stock.decline_6m) + "%" if stock.decline_6m else "-"}</td>
                    <td style="color: {'red' if stock.decline_1y else 'black'};">{"↓" + str(stock.decline_1y) + "%" if stock.decline_1y else "-"}</td>
                </tr>
                """
            body += "</table>"

        body += f"""
            <p style="color: gray; font-size: 12px;"><i>Generated at: {datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")} IST</i></p>
        </body>
        </html>
        """

        msg.attach(MIMEText(body, "html"))

        try:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
            server.quit()

            email_log = EmailLogModel(
                subject=msg["Subject"],
                recipient=TO_EMAIL,
                alerts_count=len(alerts),
                declined_count=len(declined_stocks) if declined_stocks else 0,
                status="sent",
            )
            db.add(email_log)
            db.commit()
        except Exception as e:
            print(f"Failed to send email: {e}")
            db.rollback()
            try:
                email_log = EmailLogModel(
                    subject=msg["Subject"],
                    recipient=TO_EMAIL,
                    alerts_count=len(alerts),
                    declined_count=len(declined_stocks) if declined_stocks else 0,
                    status="failed",
                )
                db.add(email_log)
                db.commit()
            except Exception:
                db.rollback()


def check_portfolio_prices():
    if not is_market_open():
        print(f"Market closed - Skipping check at {datetime.now(IST)}")
        return

    with get_db_session() as db:
        portfolio_items = db.query(PortfolioModel).all()
        if not portfolio_items:
            return

        alerts: List[PriceAlert] = []

        for item in portfolio_items:
            try:
                data = fetch_stock_data(item.symbol)
                current_price = data["current_price"]
                week_52_high = data["week_52_high"]
                week_52_low = data["week_52_low"]
                week_100_high = data["week_100_high"]

                if week_52_high and abs(current_price - week_52_high) / week_52_high < 0.01:
                    alerts.append(PriceAlert(
                        symbol=item.symbol,
                        buy_price=item.buy_price,
                        current_price=current_price,
                        alert_type="52_week_high_reached",
                        high_price=week_52_high,
                        low_price=None,
                        target_price=None,
                        potential_return=calculate_potential_return(item.buy_price, week_52_high),
                    ))

                if week_100_high and abs(current_price - week_100_high) / week_100_high < 0.01:
                    alerts.append(PriceAlert(
                        symbol=item.symbol,
                        buy_price=item.buy_price,
                        current_price=current_price,
                        alert_type="100_week_high_reached",
                        high_price=week_100_high,
                        low_price=None,
                        target_price=None,
                        potential_return=calculate_potential_return(item.buy_price, week_100_high),
                    ))

                if week_52_low and abs(current_price - week_52_low) / week_52_low < 0.01:
                    alerts.append(PriceAlert(
                        symbol=item.symbol,
                        buy_price=item.buy_price,
                        current_price=current_price,
                        alert_type="52_week_low_near",
                        high_price=None,
                        low_price=week_52_low,
                        target_price=None,
                        potential_return=None,
                    ))

                if item.target_price and current_price >= item.target_price:
                    alerts.append(PriceAlert(
                        symbol=item.symbol,
                        buy_price=item.buy_price,
                        current_price=current_price,
                        alert_type="target_price_reached",
                        high_price=None,
                        low_price=None,
                        target_price=item.target_price,
                        potential_return=calculate_potential_return(item.buy_price, current_price),
                    ))
            except HTTPException as e:
                print(f"Could not fetch data for {item.symbol}: {e.detail}")
            except Exception as e:
                print(f"Unexpected error for {item.symbol}: {e}")

        if alerts:
            send_email_notification(alerts)
        else:
            print(f"Price check completed at {datetime.now(IST)} - No alerts")


def screen_nifty_stocks(
    index: str = "NIFTY100",
    months_3_decline: float = 25.0,
    months_6_decline: float = 40.0,
    year_1_decline: float = 48.0,
) -> NiftyScreenerResult:
    constituents = NIFTY_50 if index == "NIFTY50" else NIFTY_100
    declined_stocks: List[DeclinedStock] = []
    scanned = 0

    with get_db_session() as db:
        for symbol in constituents:
            try:
                ticker = yf.Ticker(to_yahoo_symbol(symbol))

                try:
                    info = ticker.info or {}
                except Exception:
                    info = {}

                current_price = info.get("currentPrice") or info.get("previousClose")
                sector = info.get("sector")

                if current_price is None:
                    continue

                hist_3m = ticker.history(period="3mo", auto_adjust=False)
                hist_6m = ticker.history(period="6mo", auto_adjust=False)
                hist_1y = ticker.history(period="1y", auto_adjust=False)

                decline_3m = None
                decline_6m = None
                decline_1y = None

                if not hist_3m.empty:
                    price_3m_ago = hist_3m["Close"].iloc[0]
                    if price_3m_ago > 0:
                        decline_3m = round(((price_3m_ago - current_price) / price_3m_ago) * 100, 2)

                if not hist_6m.empty:
                    price_6m_ago = hist_6m["Close"].iloc[0]
                    if price_6m_ago > 0:
                        decline_6m = round(((price_6m_ago - current_price) / price_6m_ago) * 100, 2)

                if not hist_1y.empty:
                    price_1y_ago = hist_1y["Close"].iloc[0]
                    if price_1y_ago > 0:
                        decline_1y = round(((price_1y_ago - current_price) / price_1y_ago) * 100, 2)

                scanned += 1

                alert_type = None
                if decline_3m is not None and decline_3m >= months_3_decline:
                    alert_type = "3_month_decline"
                elif decline_6m is not None and decline_6m >= months_6_decline:
                    alert_type = "6_month_decline"
                elif decline_1y is not None and decline_1y >= year_1_decline:
                    alert_type = "1_year_decline"

                if alert_type:
                    declined_stock = DeclinedStock(
                        symbol=symbol,
                        current_price=round(float(current_price), 2),
                        sector=sector,
                        decline_3m=decline_3m,
                        decline_6m=decline_6m,
                        decline_1y=decline_1y,
                        alert_type=alert_type,
                    )
                    declined_stocks.append(declined_stock)

                    db.add(ScreenerResultModel(
                        index_name=index,
                        symbol=symbol,
                        current_price=round(float(current_price), 2),
                        sector=sector,
                        decline_3m=decline_3m,
                        decline_6m=decline_6m,
                        decline_1y=decline_1y,
                        alert_type=alert_type,
                        thresholds_3m=months_3_decline,
                        thresholds_6m=months_6_decline,
                        thresholds_1y=year_1_decline,
                    ))
                    db.commit()

            except Exception as e:
                print(f"Error processing {symbol}: {e}")

    return NiftyScreenerResult(
        index=index,
        total_stocks=len(constituents),
        scanned=scanned,
        declined_stocks=declined_stocks,
        thresholds={
            "3_month": months_3_decline,
            "6_month": months_6_decline,
            "1_year": year_1_decline,
        },
    )


def check_nifty_opportunities(index: str = "NIFTY100"):
    if not is_market_open():
        print(f"Market closed - Skipping Nifty screener at {datetime.now(IST)}")
        return

    try:
        result = screen_nifty_stocks(
            index=index,
            months_3_decline=NIFTY_3M_DECLINE_THRESHOLD,
            months_6_decline=NIFTY_6M_DECLINE_THRESHOLD,
            year_1_decline=NIFTY_1Y_DECLINE_THRESHOLD,
        )
        if result.declined_stocks:
            send_email_notification([], result.declined_stocks)
    except Exception as e:
        print(f"Error in Nifty screener: {e}")


@app.post("/stocks", response_model=StockAddResponse)
def add_stock(stock: StockInput):
    symbol_upper = normalize_symbol(stock.symbol)

    with get_db_session() as db:
        existing = db.query(PortfolioModel).filter(PortfolioModel.symbol == symbol_upper).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Stock {symbol_upper} already in portfolio")

        try:
            fetch_stock_data(symbol_upper)
        except HTTPException:
            raise HTTPException(
                status_code=400,
                detail=f"Stock '{symbol_upper}' does not exist on NSE or data is unavailable",
            )

        new_stock = PortfolioModel(symbol=symbol_upper, buy_price=stock.buy_price)
        db.add(new_stock)
        db.commit()

        return StockAddResponse(
            message="Stock added successfully",
            symbol=symbol_upper,
            buy_price=stock.buy_price,
        )


@app.delete("/stocks/{symbol}", response_model=DeleteResponse)
def delete_stock(symbol: str):
    symbol_upper = normalize_symbol(symbol)

    with get_db_session() as db:
        stock = db.query(PortfolioModel).filter(PortfolioModel.symbol == symbol_upper).first()
        if not stock:
            raise HTTPException(status_code=404, detail=f"Stock {symbol_upper} not found in portfolio")

        db.delete(stock)
        db.commit()

        return DeleteResponse(
            message=f"Stock {symbol_upper} removed successfully",
            symbol=symbol_upper,
        )


@app.post("/stocks/{symbol}/alert")
def set_custom_alert(symbol: str, alert_input: CustomAlertInput):
    symbol_upper = normalize_symbol(symbol)

    with get_db_session() as db:
        stock = db.query(PortfolioModel).filter(PortfolioModel.symbol == symbol_upper).first()
        if not stock:
            raise HTTPException(status_code=404, detail=f"Stock {symbol_upper} not found in portfolio")

        stock.target_price = alert_input.target_price
        stock.updated_at = datetime.utcnow()
        db.commit()

        return {
            "message": f"Custom alert set for {symbol_upper}",
            "symbol": symbol_upper,
            "target_price": alert_input.target_price,
        }


@app.get("/portfolio")
def get_portfolio():
    with get_db_session() as db:
        portfolio_items = db.query(PortfolioModel).all()
        results = []

        for item in portfolio_items:
            result = {
                "symbol": item.symbol,
                "buy_price": item.buy_price,
                "target_price": item.target_price,
                "current_price": None,
                "week_52_high": None,
                "week_52_low": None,
                "week_100_high": None,
                "potential_return_52w": None,
                "potential_return_100w": None,
                "dividend_yield": None,
                "dividend_history": [],
                "sector": None,
                "error": None,
            }

            try:
                data = fetch_stock_data(item.symbol)
                result["current_price"] = data.get("current_price")
                result["week_52_high"] = data.get("week_52_high")
                result["week_52_low"] = data.get("week_52_low")
                result["week_100_high"] = data.get("week_100_high")
                result["dividend_yield"] = data.get("dividend_yield")
                result["dividend_history"] = data.get("dividend_history", [])
                result["sector"] = data.get("sector")

                if data.get("week_52_high") is not None:
                    result["potential_return_52w"] = calculate_potential_return(item.buy_price, data["week_52_high"])

                if data.get("week_100_high") is not None:
                    result["potential_return_100w"] = calculate_potential_return(item.buy_price, data["week_100_high"])

            except HTTPException as e:
                result["error"] = e.detail
            except Exception as e:
                result["error"] = f"Failed to fetch market data: {str(e)}"

            results.append(result)

        return results


@app.get("/portfolio/sector")
def get_portfolio_by_sector():
    with get_db_session() as db:
        portfolio_items = db.query(PortfolioModel).all()
        sector_groups: Dict[str, List[dict]] = {}

        for item in portfolio_items:
            try:
                data = fetch_stock_data(item.symbol)
                sector = data.get("sector") or "Unknown"
                stock_info = {
                    "symbol": item.symbol,
                    "buy_price": item.buy_price,
                    "current_price": data.get("current_price"),
                    "potential_return_52w": calculate_potential_return(item.buy_price, data["week_52_high"])
                    if data.get("week_52_high") is not None else None,
                    "sector": sector,
                    "error": None,
                }
            except HTTPException as e:
                sector = "Unknown"
                stock_info = {
                    "symbol": item.symbol,
                    "buy_price": item.buy_price,
                    "current_price": None,
                    "potential_return_52w": None,
                    "sector": sector,
                    "error": e.detail,
                }
            except Exception as e:
                sector = "Unknown"
                stock_info = {
                    "symbol": item.symbol,
                    "buy_price": item.buy_price,
                    "current_price": None,
                    "potential_return_52w": None,
                    "sector": sector,
                    "error": str(e),
                }

            sector_groups.setdefault(sector, []).append(stock_info)

        result = []
        for sector, stocks in sector_groups.items():
            valid_returns = [s["potential_return_52w"] for s in stocks if s.get("potential_return_52w") is not None]
            avg_return = round(sum(valid_returns) / len(valid_returns), 2) if valid_returns else None
            result.append({
                "sector": sector,
                "stocks": stocks,
                "total_stocks": len(stocks),
                "avg_return": avg_return,
            })

        return result


@app.post("/scheduler/start")
def start_scheduler():
    scheduler.remove_all_jobs()
    scheduler.add_job(
        check_portfolio_prices,
        "interval",
        minutes=60,
        id="price_checker",
        replace_existing=True,
    )
    return {"message": "Scheduler started - Price checker runs every 60 minutes", "status": "running"}


@app.post("/scheduler/stop")
def stop_scheduler():
    try:
        scheduler.remove_job("price_checker")
    except Exception:
        pass
    return {"message": "Scheduler stopped", "status": "stopped"}


@app.get("/scheduler/status")
def scheduler_status():
    jobs = scheduler.get_jobs()
    return {
        "status": "running" if jobs else "stopped",
        "market_open": is_market_open(),
        "ist_time": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"),
        "jobs": [str(job) for job in jobs],
    }


@app.post("/scheduler/check-now")
def check_now():
    check_portfolio_prices()
    return {"message": "Price check completed"}


@app.post("/nifty/screen")
def screen_nifty(input_data: NiftyScreenerInput):
    index_name = normalize_symbol(input_data.index)

    def run_screener():
        try:
            nifty_screener_running[index_name] = True
            result = screen_nifty_stocks(
                index=index_name,
                months_3_decline=input_data.months_3_decline,
                months_6_decline=input_data.months_6_decline,
                year_1_decline=input_data.year_1_decline,
            )
            nifty_screener_results[index_name] = result.model_dump()
        except Exception as e:
            nifty_screener_results[index_name] = {"error": str(e)}
        finally:
            nifty_screener_running[index_name] = False

    thread = threading.Thread(target=run_screener, daemon=True)
    thread.start()

    return {
        "message": f"Screener started for {index_name}",
        "status": "running",
        "check_status_at": f"/nifty/screen/status/{index_name}",
    }


@app.get("/nifty/screen/status/{index}")
def get_screener_status(index: str):
    index_name = normalize_symbol(index)

    if index_name not in ["NIFTY50", "NIFTY100"]:
        raise HTTPException(status_code=400, detail="Index must be NIFTY50 or NIFTY100")

    if nifty_screener_running.get(index_name):
        return {"status": "running", "message": "Screener is still processing..."}

    if index_name in nifty_screener_results:
        return {"status": "completed", **nifty_screener_results[index_name]}

    return {"status": "not_started", "message": "No screener run yet. Use POST /nifty/screen to start."}


@app.get("/nifty/screen/{index}")
def screen_nifty_quick(
    index: str,
    months_3_decline: Optional[float] = None,
    months_6_decline: Optional[float] = None,
    year_1_decline: Optional[float] = None,
):
    index_name = normalize_symbol(index)
    if index_name not in ["NIFTY50", "NIFTY100"]:
        raise HTTPException(status_code=400, detail="Index must be NIFTY50 or NIFTY100")

    m3 = months_3_decline if months_3_decline is not None else NIFTY_3M_DECLINE_THRESHOLD
    m6 = months_6_decline if months_6_decline is not None else NIFTY_6M_DECLINE_THRESHOLD
    y1 = year_1_decline if year_1_decline is not None else NIFTY_1Y_DECLINE_THRESHOLD

    def run_screener():
        try:
            nifty_screener_running[index_name] = True
            result = screen_nifty_stocks(
                index=index_name,
                months_3_decline=m3,
                months_6_decline=m6,
                year_1_decline=y1,
            )
            nifty_screener_results[index_name] = result.model_dump()
        except Exception as e:
            nifty_screener_results[index_name] = {"error": str(e)}
        finally:
            nifty_screener_running[index_name] = False

    thread = threading.Thread(target=run_screener, daemon=True)
    thread.start()

    return {
        "message": f"Screener started for {index_name}",
        "status": "running",
        "thresholds": {
            "3_month": m3,
            "6_month": m6,
            "1_year": y1,
        },
        "check_status_at": f"/nifty/screen/status/{index_name}",
    }


@app.post("/nifty/alert/enable")
def enable_nifty_alerts(input_data: NiftyScreenerInput):
    global NIFTY_3M_DECLINE_THRESHOLD, NIFTY_6M_DECLINE_THRESHOLD, NIFTY_1Y_DECLINE_THRESHOLD

    NIFTY_3M_DECLINE_THRESHOLD = input_data.months_3_decline
    NIFTY_6M_DECLINE_THRESHOLD = input_data.months_6_decline
    NIFTY_1Y_DECLINE_THRESHOLD = input_data.year_1_decline

    scheduler.add_job(
        lambda: check_nifty_opportunities(normalize_symbol(input_data.index)),
        "interval",
        minutes=60,
        id="nifty_screener",
        replace_existing=True,
    )

    return {
        "message": f"Nifty {normalize_symbol(input_data.index)} screener alerts enabled",
        "status": "running",
        "thresholds": {
            "3_month": input_data.months_3_decline,
            "6_month": input_data.months_6_decline,
            "1_year": input_data.year_1_decline,
        },
    }


@app.post("/nifty/alert/disable")
def disable_nifty_alerts():
    try:
        scheduler.remove_job("nifty_screener")
        return {"message": "Nifty screener alerts disabled", "status": "stopped"}
    except Exception:
        return {"message": "Nifty screener was not running", "status": "stopped"}


@app.get("/")
def root():
    return {
        "message": "Stock Dashboard API (PostgreSQL)",
        "database": "Configured",
        "endpoints": {
            "POST /stocks": "Add a stock to portfolio",
            "DELETE /stocks/{symbol}": "Remove a stock",
            "GET /portfolio": "View all stocks",
            "GET /portfolio/sector": "View by sector",
            "POST /stocks/{symbol}/alert": "Set price target",
            "POST /nifty/screen": "Screen Nifty (async)",
            "GET /nifty/screen/{index}": "Quick screen (async)",
            "GET /nifty/screen/status/{index}": "Get results",
            "POST /nifty/alert/enable": "Enable alerts",
            "POST /nifty/alert/disable": "Disable alerts",
            "POST /scheduler/start": "Start price checker",
            "POST /scheduler/stop": "Stop price checker",
            "GET /scheduler/status": "Check status",
            "POST /scheduler/check-now": "Run check now",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, timeout_keep_alive=120)