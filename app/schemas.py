"""
schemas.py — All Pydantic models (request/response shapes)
"""
from typing import Dict, List, Optional

from pydantic import BaseModel


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
    current_price: Optional[float]       = None
    week_52_high: Optional[float]        = None
    week_52_low: Optional[float]         = None
    week_100_high: Optional[float]       = None
    potential_return_52w: Optional[float] = None
    potential_return_100w: Optional[float] = None
    dividend_yield: Optional[float]      = None
    dividend_history: Optional[List[dict]] = []
    sector: Optional[str]                = None
    target_price: Optional[float]        = None
    error: Optional[str]                 = None


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


class NiftyScreenerInput(BaseModel):
    index: str            = "NIFTY100"
    months_3_decline: float = 25.0
    months_6_decline: float = 40.0
    year_1_decline: float   = 48.0


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
