"""
routes/portfolio.py — /stocks and /portfolio endpoints
"""
from datetime import datetime
from typing import Dict, List

from fastapi import APIRouter, HTTPException

from app.database import PortfolioModel, get_db_session
from app.schemas import (
    CustomAlertInput,
    DeleteResponse,
    StockAddResponse,
    StockInput,
    StockReturn,
)
from app.stock_data import (
    calculate_potential_return,
    fetch_stock_data,
    get_cached_stock_data,
    normalize_symbol,
)

router = APIRouter()


@router.post("/stocks", response_model=StockAddResponse)
def add_stock(stock: StockInput):
    symbol_upper = normalize_symbol(stock.symbol)
    with get_db_session() as db:
        if db.query(PortfolioModel).filter(PortfolioModel.symbol == symbol_upper).first():
            raise HTTPException(status_code=400, detail=f"{symbol_upper} already in portfolio")
        try:
            fetch_stock_data(symbol_upper)
        except HTTPException:
            raise HTTPException(status_code=400, detail=f"'{symbol_upper}' not found on NSE")
        db.add(PortfolioModel(symbol=symbol_upper, buy_price=stock.buy_price))
        db.commit()
        return StockAddResponse(message="Stock added successfully", symbol=symbol_upper, buy_price=stock.buy_price)


@router.delete("/stocks/{symbol}", response_model=DeleteResponse)
def delete_stock(symbol: str):
    symbol_upper = normalize_symbol(symbol)
    with get_db_session() as db:
        stock = db.query(PortfolioModel).filter(PortfolioModel.symbol == symbol_upper).first()
        if not stock:
            raise HTTPException(status_code=404, detail=f"{symbol_upper} not found")
        db.delete(stock)
        db.commit()
        return DeleteResponse(message=f"{symbol_upper} removed", symbol=symbol_upper)


@router.post("/stocks/{symbol}/alert")
def set_custom_alert(symbol: str, alert_input: CustomAlertInput):
    symbol_upper = normalize_symbol(symbol)
    with get_db_session() as db:
        stock = db.query(PortfolioModel).filter(PortfolioModel.symbol == symbol_upper).first()
        if not stock:
            raise HTTPException(status_code=404, detail=f"{symbol_upper} not found")
        stock.target_price = alert_input.target_price
        stock.updated_at   = datetime.utcnow()
        db.commit()
        return {"message": f"Alert set for {symbol_upper}", "symbol": symbol_upper, "target_price": alert_input.target_price}


@router.get("/portfolio")
def get_portfolio():
    with get_db_session() as db:
        items   = db.query(PortfolioModel).all()
        results = []
        for item in items:
            try:
                data = get_cached_stock_data(item.symbol)
                results.append(StockReturn(
                    symbol=item.symbol,
                    buy_price=item.buy_price,
                    target_price=item.target_price,
                    current_price=data["current_price"],
                    week_52_high=data["week_52_high"],
                    week_52_low=data["week_52_low"],
                    week_100_high=data["week_100_high"],
                    potential_return_52w=calculate_potential_return(item.buy_price, data["week_52_high"]),
                    potential_return_100w=calculate_potential_return(item.buy_price, data["week_100_high"]) if data["week_100_high"] else None,
                    dividend_yield=data["dividend_yield"],
                    dividend_history=data["dividend_history"],
                    sector=data["sector"],
                ))
            except Exception as e:
                results.append(StockReturn(symbol=item.symbol, buy_price=item.buy_price, target_price=item.target_price, error=str(e)))
        return results


@router.get("/portfolio/sector")
def get_portfolio_by_sector():
    with get_db_session() as db:
        items         = db.query(PortfolioModel).all()
        sector_groups: Dict[str, List[dict]] = {}

        for item in items:
            try:
                data   = get_cached_stock_data(item.symbol)
                sector = data["sector"] or "Unknown"
                info   = {
                    "symbol": item.symbol,
                    "buy_price": item.buy_price,
                    "current_price": data["current_price"],
                    "potential_return_52w": calculate_potential_return(item.buy_price, data["week_52_high"]),
                    "sector": sector,
                }
            except Exception as e:
                sector = "Unknown"
                info   = {"symbol": item.symbol, "buy_price": item.buy_price, "error": str(e), "sector": "Unknown"}
            sector_groups.setdefault(sector, []).append(info)

        return [
            {
                "sector": s,
                "stocks": stocks,
                "total_stocks": len(stocks),
                "avg_return": round(
                    sum(x["potential_return_52w"] for x in stocks if "potential_return_52w" in x)
                    / max(len([x for x in stocks if "potential_return_52w" in x]), 1),
                    2,
                ),
            }
            for s, stocks in sector_groups.items()
        ]
