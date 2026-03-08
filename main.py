import json
import os
import smtplib
import threading
from datetime import datetime, time
from typing import Dict, List, Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytz
import yfinance as yf
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

load_dotenv()

app = FastAPI(title="Stock Dashboard API")

# CORS - Allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

# Database configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psucharanteja814r?sslmode=require"
)

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


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


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
    print("Database tables created successfully")


# Initialize database on startup
init_db()

# Email configuration
SMTP_HOST = "smtp-relay.brevo.com"
SMTP_PORT = 587
SMTP_USER = "7f75f2003@smtp-brevo.com"
SMTP_PASS = os.getenv("SMTP_PASS", "xsmtpsib-3492d6ce8135986bb1763490ca3dade1d613f143e92667571be5ffe39beefc05-TXHt0UO2QnS1ILBK")
FROM_EMAIL = "abcxyz123inf@gmail.com"
TO_EMAIL = "gattucharanteja8143@gmail.com"

# Indian market hours (IST)
IST = pytz.timezone("Asia/Kolkata")
MARKET_OPEN = time(9, 20)  # 9:20 AM IST
MARKET_CLOSE = time(15, 20)  # 3:20 PM IST

# Nifty screener configuration (configurable thresholds)
NIFTY_3M_DECLINE_THRESHOLD = 25.0  # Down 25% in last 3 months
NIFTY_6M_DECLINE_THRESHOLD = 40.0  # Down 40% in last 6 months
NIFTY_1Y_DECLINE_THRESHOLD = 48.0  # Down 48% in last 1 year

# Nifty 50 and Nifty 100 constituents (common stocks)
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


def is_market_open() -> bool:
    """Check if Indian stock market is currently open (Mon-Fri, 9:20 AM - 3:20 PM IST)"""
    now_ist = datetime.now(IST)
    current_time = now_ist.time()
    weekday = now_ist.weekday()  # 0=Monday, 4=Friday

    # Check if weekend
    if weekday >= 5:  # Saturday or Sunday
        return False

    # Check market hours
    return MARKET_OPEN <= current_time <= MARKET_CLOSE


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        return db
    finally:
        pass


# Scheduler
scheduler = BackgroundScheduler()
scheduler.start()

# Global storage for nifty screener results
nifty_screener_results: Dict[str, dict] = {}
nifty_screener_running: Dict[str, bool] = {}


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
    current_price: float
    week_52_high: float
    week_52_low: Optional[float]
    week_100_high: Optional[float]
    potential_return_52w: float
    potential_return_100w: Optional[float]
    dividend_yield: Optional[float]
    dividend_history: Optional[List[dict]]
    sector: Optional[str]


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


def calculate_potential_return(buy_price: float, high_price: float) -> float:
    """Calculate potential return percentage when stock reaches the high price."""
    if buy_price <= 0:
        return 0.0
    return round(((high_price - buy_price) / buy_price) * 100, 2)


def fetch_stock_data(symbol: str) -> dict:
    """Fetch stock data from yfinance."""
    ticker_symbol = symbol.upper()
    if not ticker_symbol.endswith((".NS", ".BO")):
        ticker_symbol = ticker_symbol + ".NS"

    ticker = yf.Ticker(ticker_symbol)
    info = ticker.info

    week_52_high = info.get("fiftyTwoWeekHigh")
    week_52_low = info.get("fiftyTwoWeekLow")
    current_price = info.get("currentPrice") or info.get("previousClose")
    sector = info.get("sector")
    dividend_yield = info.get("dividendYield")

    week_100_high = None
    try:
        hist = ticker.history(period="2y")
        if len(hist) > 0:
            week_100_high = round(hist["High"].max(), 2)
    except Exception:
        pass

    dividend_history = []
    try:
        dividends = ticker.dividends
        if dividends is not None and len(dividends) > 0:
            recent_dividends = dividends.tail(5)
            for date, amount in recent_dividends.items():
                dividend_history.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "amount": round(amount, 2)
                })
    except Exception:
        pass

    if not week_52_high or not current_price:
        raise HTTPException(
            status_code=404,
            detail=f"Could not fetch data for symbol: {symbol}. Try adding .NS or .BO suffix (e.g., ITC.NS)"
        )

    return {
        "symbol": symbol.upper(),
        "current_price": round(current_price, 2),
        "week_52_high": round(week_52_high, 2),
        "week_52_low": round(week_52_low, 2) if week_52_low else None,
        "week_100_high": week_100_high,
        "sector": sector,
        "dividend_yield": round(dividend_yield * 100, 2) if dividend_yield else None,
        "dividend_history": dividend_history,
    }


def send_email_notification(alerts: List[PriceAlert], declined_stocks: List[DeclinedStock] = None):
    """Send email notification and log to database."""
    if not alerts and not declined_stocks:
        return

    db = SessionLocal()
    try:
        msg = MIMEMultipart()
        msg['From'] = FROM_EMAIL
        msg['To'] = TO_EMAIL

        if declined_stocks and alerts:
            msg['Subject'] = f"🚨 Stock Alert - {len(alerts)} Portfolio + {len(declined_stocks)} Nifty Stocks Down!"
        elif declined_stocks:
            msg['Subject'] = f"📉 Nifty Screener - {len(declined_stocks)} Stocks Down Significantly!"
        else:
            msg['Subject'] = f"Stock Alert - {len(alerts)} Alert(s)!"

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

        msg.attach(MIMEText(body, 'html'))

        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()

        # Log to database
        email_log = EmailLogModel(
            subject=msg['Subject'],
            recipient=TO_EMAIL,
            alerts_count=len(alerts),
            declined_count=len(declined_stocks) if declined_stocks else 0,
            status="sent"
        )
        db.add(email_log)
        db.commit()

        print(f"Email sent! Alerts: {len(alerts)}, Declined: {len(declined_stocks) if declined_stocks else 0}")
    except Exception as e:
        print(f"Failed to send email: {e}")
        db.rollback()
        # Log failure
        try:
            email_log = EmailLogModel(
                subject=msg['Subject'] if 'msg' in dir() else "Unknown",
                recipient=TO_EMAIL,
                alerts_count=len(alerts),
                declined_count=len(declined_stocks) if declined_stocks else 0,
                status="failed"
            )
            db.add(email_log)
            db.commit()
        except:
            pass
    finally:
        db.close()


def check_portfolio_prices():
    """Check all stocks in portfolio and send alerts."""
    if not is_market_open():
        print(f"Market closed - Skipping check at {datetime.now(IST)}")
        return

    db = SessionLocal()
    try:
        portfolio_items = db.query(PortfolioModel).all()
        
        if not portfolio_items:
            db.close()
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
                    potential_return = calculate_potential_return(item.buy_price, week_52_high)
                    alerts.append(PriceAlert(
                        symbol=item.symbol,
                        buy_price=item.buy_price,
                        current_price=current_price,
                        alert_type="52_week_high_reached",
                        high_price=week_52_high,
                        low_price=None,
                        target_price=None,
                        potential_return=potential_return
                    ))

                if week_100_high and abs(current_price - week_100_high) / week_100_high < 0.01:
                    potential_return = calculate_potential_return(item.buy_price, week_100_high)
                    alerts.append(PriceAlert(
                        symbol=item.symbol,
                        buy_price=item.buy_price,
                        current_price=current_price,
                        alert_type="100_week_high_reached",
                        high_price=week_100_high,
                        low_price=None,
                        target_price=None,
                        potential_return=potential_return
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
                        potential_return=None
                    ))

                if item.target_price and current_price >= item.target_price:
                    potential_return = calculate_potential_return(item.buy_price, current_price)
                    alerts.append(PriceAlert(
                        symbol=item.symbol,
                        buy_price=item.buy_price,
                        current_price=current_price,
                        alert_type="target_price_reached",
                        high_price=None,
                        low_price=None,
                        target_price=item.target_price,
                        potential_return=potential_return
                    ))
            except HTTPException:
                print(f"Could not fetch data for {item.symbol}")

        if alerts:
            send_email_notification(alerts)
        else:
            print(f"Price check completed at {datetime.now(IST)} - No alerts")
    finally:
        db.close()


def screen_nifty_stocks(index: str = "NIFTY100", months_3_decline: float = 25.0,
                        months_6_decline: float = 40.0, year_1_decline: float = 48.0) -> NiftyScreenerResult:
    """Screen Nifty stocks for significant declines."""
    constituents = NIFTY_50 if index == "NIFTY50" else NIFTY_100

    declined_stocks: List[DeclinedStock] = []
    scanned = 0
    failed = 0

    for symbol in constituents:
        try:
            ticker_symbol = symbol + ".NS"
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.info
            current_price = info.get("currentPrice") or info.get("previousClose")
            sector = info.get("sector")

            if not current_price:
                failed += 1
                continue

            hist_3m = ticker.history(period="3mo")
            hist_6m = ticker.history(period="6mo")
            hist_1y = ticker.history(period="1y")

            decline_3m = None
            decline_6m = None
            decline_1y = None

            if len(hist_3m) > 0:
                price_3m_ago = hist_3m["Close"].iloc[0]
                if price_3m_ago > 0:
                    decline_3m = round(((price_3m_ago - current_price) / price_3m_ago) * 100, 2)

            if len(hist_6m) > 0:
                price_6m_ago = hist_6m["Close"].iloc[0]
                if price_6m_ago > 0:
                    decline_6m = round(((price_6m_ago - current_price) / price_6m_ago) * 100, 2)

            if len(hist_1y) > 0:
                price_1y_ago = hist_1y["Close"].iloc[0]
                if price_1y_ago > 0:
                    decline_1y = round(((price_1y_ago - current_price) / price_1y_ago) * 100, 2)

            scanned += 1

            alert_type = None
            if decline_3m and decline_3m >= months_3_decline:
                alert_type = "3_month_decline"
            elif decline_6m and decline_6m >= months_6_decline:
                alert_type = "6_month_decline"
            elif decline_1y and decline_1y >= year_1_decline:
                alert_type = "1_year_decline"

            if alert_type:
                declined_stocks.append(DeclinedStock(
                    symbol=symbol,
                    current_price=round(current_price, 2),
                    sector=sector,
                    decline_3m=decline_3m,
                    decline_6m=decline_6m,
                    decline_1y=decline_1y,
                    alert_type=alert_type
                ))

                # Save to database
                db = SessionLocal()
                try:
                    screener_result = ScreenerResultModel(
                        index_name=index,
                        symbol=symbol,
                        current_price=round(current_price, 2),
                        sector=sector,
                        decline_3m=decline_3m,
                        decline_6m=decline_6m,
                        decline_1y=decline_1y,
                        alert_type=alert_type,
                        thresholds_3m=months_3_decline,
                        thresholds_6m=months_6_decline,
                        thresholds_1y=year_1_decline
                    )
                    db.add(screener_result)
                    db.commit()
                except:
                    db.rollback()
                finally:
                    db.close()

        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            failed += 1
            continue

    print(f"Screening complete: {scanned} scanned, {failed} failed, {len(declined_stocks)} declined")

    return NiftyScreenerResult(
        index=index,
        total_stocks=len(constituents),
        scanned=scanned,
        declined_stocks=declined_stocks,
        thresholds={
            "3_month": months_3_decline,
            "6_month": months_6_decline,
            "1_year": year_1_decline
        }
    )


def check_nifty_opportunities(index: str = "NIFTY100"):
    """Check Nifty stocks for buying opportunities and send email alerts."""
    if not is_market_open():
        print(f"Market closed - Skipping Nifty screener at {datetime.now(IST)}")
        return

    try:
        result = screen_nifty_stocks(
            index=index,
            months_3_decline=NIFTY_3M_DECLINE_THRESHOLD,
            months_6_decline=NIFTY_6M_DECLINE_THRESHOLD,
            year_1_decline=NIFTY_1Y_DECLINE_THRESHOLD
        )

        if result.declined_stocks:
            print(f"Found {len(result.declined_stocks)} declined stocks in {index}")
            send_email_notification([], result.declined_stocks)
        else:
            print(f"No declined stocks found in {index}")

    except Exception as e:
        print(f"Error in Nifty screener: {e}")


@app.post("/stocks", response_model=StockAddResponse)
def add_stock(stock: StockInput):
    """Add a stock to the portfolio."""
    symbol_upper = stock.symbol.upper()

    db = SessionLocal()
    try:
        # Check if already in portfolio
        existing = db.query(PortfolioModel).filter(PortfolioModel.symbol == symbol_upper).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Stock {symbol_upper} already in portfolio. Use GET /portfolio to view."
            )

        # Validate stock exists on NSE
        try:
            fetch_stock_data(symbol_upper)
        except HTTPException as e:
            raise HTTPException(
                status_code=400,
                detail=f"Stock '{symbol_upper}' does not exist on NSE. Please check the symbol."
            )

        # Add to database
        new_stock = PortfolioModel(
            symbol=symbol_upper,
            buy_price=stock.buy_price
        )
        db.add(new_stock)
        db.commit()
        db.refresh(new_stock)

        return StockAddResponse(
            message="Stock added successfully",
            symbol=symbol_upper,
            buy_price=stock.buy_price
        )
    finally:
        db.close()


@app.delete("/stocks/{symbol}", response_model=DeleteResponse)
def delete_stock(symbol: str):
    """Remove a stock from the portfolio."""
    symbol_upper = symbol.upper()

    db = SessionLocal()
    try:
        stock = db.query(PortfolioModel).filter(PortfolioModel.symbol == symbol_upper).first()
        
        if not stock:
            raise HTTPException(
                status_code=404,
                detail=f"Stock {symbol_upper} not found in portfolio"
            )

        db.delete(stock)
        db.commit()

        return DeleteResponse(
            message=f"Stock {symbol_upper} removed successfully",
            symbol=symbol_upper
        )
    finally:
        db.close()


@app.post("/stocks/{symbol}/alert")
def set_custom_alert(symbol: str, alert_input: CustomAlertInput):
    """Set a custom price target alert for a stock."""
    symbol_upper = symbol.upper()

    db = SessionLocal()
    try:
        stock = db.query(PortfolioModel).filter(PortfolioModel.symbol == symbol_upper).first()
        
        if not stock:
            raise HTTPException(
                status_code=404,
                detail=f"Stock {symbol_upper} not found in portfolio"
            )

        stock.target_price = alert_input.target_price
        stock.updated_at = datetime.utcnow()
        db.commit()

        return {
            "message": f"Custom alert set for {symbol_upper}",
            "symbol": symbol_upper,
            "target_price": alert_input.target_price
        }
    finally:
        db.close()


@app.get("/portfolio")
def get_portfolio():
    """Get all stocks in portfolio with their potential returns."""
    db = SessionLocal()
    try:
        portfolio_items = db.query(PortfolioModel).all()
        
        results = []
        for item in portfolio_items:
            try:
                data = fetch_stock_data(item.symbol)
                potential_52w = calculate_potential_return(item.buy_price, data["week_52_high"])
                potential_100w = None
                if data["week_100_high"]:
                    potential_100w = calculate_potential_return(item.buy_price, data["week_100_high"])

                results.append(StockReturn(
                    symbol=item.symbol,
                    buy_price=item.buy_price,
                    current_price=data["current_price"],
                    week_52_high=data["week_52_high"],
                    week_52_low=data["week_52_low"],
                    week_100_high=data["week_100_high"],
                    potential_return_52w=potential_52w,
                    potential_return_100w=potential_100w,
                    dividend_yield=data["dividend_yield"],
                    dividend_history=data["dividend_history"],
                    sector=data["sector"],
                ))
            except HTTPException:
                results.append({
                    "symbol": item.symbol,
                    "buy_price": item.buy_price,
                    "target_price": item.target_price,
                    "error": "Could not fetch data"
                })
        return results
    finally:
        db.close()


@app.get("/portfolio/sector")
def get_portfolio_by_sector():
    """Get stocks grouped by sector with sector-wise returns."""
    db = SessionLocal()
    try:
        portfolio_items = db.query(PortfolioModel).all()
        
        sector_groups: Dict[str, List[dict]] = {}

        for item in portfolio_items:
            try:
                data = fetch_stock_data(item.symbol)
                sector = data["sector"] or "Unknown"

                potential_52w = calculate_potential_return(item.buy_price, data["week_52_high"])

                stock_info = {
                    "symbol": item.symbol,
                    "buy_price": item.buy_price,
                    "current_price": data["current_price"],
                    "potential_return_52w": potential_52w,
                    "sector": sector
                }

                if sector not in sector_groups:
                    sector_groups[sector] = []
                sector_groups[sector].append(stock_info)

            except HTTPException:
                if "Unknown" not in sector_groups:
                    sector_groups["Unknown"] = []
                sector_groups["Unknown"].append({
                    "symbol": item.symbol,
                    "buy_price": item.buy_price,
                    "error": "Could not fetch data",
                    "sector": "Unknown"
                })

        result = []
        for sector, stocks in sector_groups.items():
            valid_returns = [s["potential_return_52w"] for s in stocks if "potential_return_52w" in s]
            avg_return = round(sum(valid_returns) / len(valid_returns), 2) if valid_returns else None

            result.append({
                "sector": sector,
                "stocks": stocks,
                "total_stocks": len(stocks),
                "avg_return": avg_return
            })

        return result
    finally:
        db.close()


@app.post("/scheduler/start")
def start_scheduler():
    """Start the price checker scheduler (runs every 60 minutes)"""
    global scheduler
    scheduler.remove_all_jobs()
    scheduler.add_job(
        check_portfolio_prices,
        'interval',
        minutes=60,
        id='price_checker',
        replace_existing=True
    )
    return {
        "message": "Scheduler started - Price checker runs every 60 minutes",
        "status": "running"
    }


@app.post("/scheduler/stop")
def stop_scheduler():
    """Stop the price checker scheduler"""
    global scheduler
    scheduler.remove_job('price_checker')
    return {
        "message": "Scheduler stopped",
        "status": "stopped"
    }


@app.get("/scheduler/status")
def scheduler_status():
    """Check scheduler status"""
    jobs = scheduler.get_jobs()
    return {
        "status": "running" if jobs else "stopped",
        "market_open": is_market_open(),
        "ist_time": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"),
        "jobs": [str(job) for job in jobs]
    }


@app.post("/scheduler/check-now")
def check_now():
    """Run price check immediately (for testing)"""
    check_portfolio_prices()
    return {"message": "Price check completed"}


@app.post("/nifty/screen")
def screen_nifty(input_data: NiftyScreenerInput):
    """Screen Nifty stocks (async)."""
    def run_screener():
        try:
            nifty_screener_running[input_data.index] = True
            result = screen_nifty_stocks(
                index=input_data.index,
                months_3_decline=input_data.months_3_decline,
                months_6_decline=input_data.months_6_decline,
                year_1_decline=input_data.year_1_decline
            )
            nifty_screener_results[input_data.index] = result.model_dump()
            nifty_screener_running[input_data.index] = False
        except Exception as e:
            nifty_screener_results[input_data.index] = {"error": str(e)}
            nifty_screener_running[input_data.index] = False

    thread = threading.Thread(target=run_screener)
    thread.start()

    return {
        "message": f"Screener started for {input_data.index}",
        "status": "running",
        "check_status_at": f"/nifty/screen/status/{input_data.index}"
    }


@app.get("/nifty/screen/status/{index}")
def get_screener_status(index: str):
    """Get screener results."""
    if index not in ["NIFTY50", "NIFTY100"]:
        raise HTTPException(status_code=400, detail="Index must be NIFTY50 or NIFTY100")

    if index in nifty_screener_running and nifty_screener_running[index]:
        return {"status": "running", "message": "Screener is still processing..."}

    if index in nifty_screener_results:
        return {"status": "completed", **nifty_screener_results[index]}

    return {"status": "not_started", "message": "No screener run yet. Use POST /nifty/screen to start."}


@app.get("/nifty/screen/{index}")
def screen_nifty_quick(index: str, 
                       months_3_decline: float = None,
                       months_6_decline: float = None,
                       year_1_decline: float = None):
    """Quick screen Nifty stocks (async)."""
    if index not in ["NIFTY50", "NIFTY100"]:
        raise HTTPException(status_code=400, detail="Index must be NIFTY50 or NIFTY100")

    # Handle NaN or None values
    m3 = months_3_decline if months_3_decline and months_3_decline == months_3_decline else NIFTY_3M_DECLINE_THRESHOLD
    m6 = months_6_decline if months_6_decline and months_6_decline == months_6_decline else NIFTY_6M_DECLINE_THRESHOLD
    y1 = year_1_decline if year_1_decline and year_1_decline == year_1_decline else NIFTY_1Y_DECLINE_THRESHOLD

    def run_screener():
        try:
            nifty_screener_running[index] = True
            result = screen_nifty_stocks(
                index=index,
                months_3_decline=m3,
                months_6_decline=m6,
                year_1_decline=y1
            )
            nifty_screener_results[index] = result.model_dump()
            nifty_screener_running[index] = False
        except Exception as e:
            nifty_screener_results[index] = {"error": str(e)}
            nifty_screener_running[index] = False

    thread = threading.Thread(target=run_screener)
    thread.start()

    return {
        "message": f"Screener started for {index}",
        "status": "running",
        "thresholds": {
            "3_month": m3,
            "6_month": m6,
            "1_year": y1
        },
        "check_status_at": f"/nifty/screen/status/{index}"
    }


@app.post("/nifty/alert/enable")
def enable_nifty_alerts(input_data: NiftyScreenerInput):
    """Enable Nifty screener alerts."""
    global scheduler
    global NIFTY_3M_DECLINE_THRESHOLD, NIFTY_6M_DECLINE_THRESHOLD, NIFTY_1Y_DECLINE_THRESHOLD
    
    NIFTY_3M_DECLINE_THRESHOLD = input_data.months_3_decline
    NIFTY_6M_DECLINE_THRESHOLD = input_data.months_6_decline
    NIFTY_1Y_DECLINE_THRESHOLD = input_data.year_1_decline

    scheduler.add_job(
        lambda: check_nifty_opportunities(input_data.index),
        'interval',
        minutes=60,
        id='nifty_screener',
        replace_existing=True
    )

    return {
        "message": f"Nifty {input_data.index} screener alerts enabled",
        "status": "running",
        "thresholds": {
            "3_month": input_data.months_3_decline,
            "6_month": input_data.months_6_decline,
            "1_year": input_data.year_1_decline
        }
    }


@app.post("/nifty/alert/disable")
def disable_nifty_alerts():
    """Disable Nifty screener alerts."""
    global scheduler
    try:
        scheduler.remove_job('nifty_screener')
        return {"message": "Nifty screener alerts disabled", "status": "stopped"}
    except Exception:
        return {"message": "Nifty screener was not running", "status": "stopped"}


@app.get("/")
def root():
    return {
        "message": "Stock Dashboard API (PostgreSQL)",
        "database": "Connected to Aiven PostgreSQL",
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
            "POST /scheduler/check-now": "Run check now"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, timeout_keep_alive=120)