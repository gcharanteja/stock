"""
database.py — SQLAlchemy engine, models, session helper
"""
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL

# ✅ pool_size=2, max_overflow=3 — stays well within Aiven free tier limits
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=1,
    max_overflow=1,
    pool_timeout=30,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ── ORM Models ────────────────────────────────────────────────────────────────

class PortfolioModel(Base):
    __tablename__ = "portfolio"
    id           = Column(Integer, primary_key=True, index=True)
    symbol       = Column(String(20), unique=True, nullable=False, index=True)
    buy_price    = Column(Float, nullable=False)
    target_price = Column(Float, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PriceHistoryModel(Base):
    __tablename__ = "price_history"
    id          = Column(Integer, primary_key=True, index=True)
    symbol      = Column(String(20), nullable=False, index=True)
    price_date  = Column(DateTime, nullable=False)
    open_price  = Column(Float)
    high_price  = Column(Float)
    low_price   = Column(Float)
    close_price = Column(Float)
    volume      = Column(Integer)
    created_at  = Column(DateTime, default=datetime.utcnow)


class ScreenerResultModel(Base):
    __tablename__ = "screener_results"
    id            = Column(Integer, primary_key=True, index=True)
    index_name    = Column(String(20), nullable=False)
    symbol        = Column(String(20), nullable=False, index=True)
    current_price = Column(Float)
    sector        = Column(String(100))
    decline_3m    = Column(Float)
    decline_6m    = Column(Float)
    decline_1y    = Column(Float)
    alert_type    = Column(String(50))
    thresholds_3m = Column(Float)
    thresholds_6m = Column(Float)
    thresholds_1y = Column(Float)
    scanned_at    = Column(DateTime, default=datetime.utcnow, index=True)


class EmailLogModel(Base):
    __tablename__ = "email_logs"
    id             = Column(Integer, primary_key=True, index=True)
    subject        = Column(String(255))
    recipient      = Column(String(255))
    alerts_count   = Column(Integer)
    declined_count = Column(Integer)
    sent_at        = Column(DateTime, default=datetime.utcnow)
    status         = Column(String(20), default="sent")


# ── Helpers ───────────────────────────────────────────────────────────────────

@contextmanager
def get_db_session():
    """Always closes the connection back to pool after use."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()   # ✅ always returns connection to pool


def init_db():
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created/verified")
