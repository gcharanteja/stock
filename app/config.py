"""
config.py — Vault secrets + all app-level constants
"""
import os

from datetime import time

import pytz
import requests
from dotenv import load_dotenv

load_dotenv()

# ============== VAULT ==============

VAULT_API_URL = "https://keyvaultt.onrender.com"


def get_from_vault(key: str, default: str = None) -> str:
    """Fetch a single secret from the Key Vault API."""
    try:
        response = requests.get(f"{VAULT_API_URL}/secrets/{key}", timeout=5)
        if response.status_code == 200:
            return response.json().get("value")
        return default
    except Exception as e:
        print(f"⚠️ Vault fetch error for {key}: {e}")
        return default


# ============== SECRETS ==============

print("🔐 Fetching secrets from Key Vault...")

DATABASE_URL = os.getenv("DATABASE_URL") or get_from_vault("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in env or Key Vault")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)

SMTP_HOST  = os.getenv("SMTP_HOST")  or get_from_vault("SMTP_HOST",  "smtp-relay.brevo.com")
SMTP_PORT  = int(os.getenv("SMTP_PORT") or get_from_vault("SMTP_PORT", "587"))
SMTP_USER  = os.getenv("SMTP_USER")  or get_from_vault("SMTP_USER",  "")
SMTP_PASS  = os.getenv("SMTP_PASS")  or get_from_vault("SMTP_PASS",  "")
FROM_EMAIL = os.getenv("FROM_EMAIL") or get_from_vault("FROM_EMAIL", "")
TO_EMAIL   = os.getenv("TO_EMAIL")   or get_from_vault("TO_EMAIL",   "")

print(f"✅ Secrets loaded | DB: {'SET' if DATABASE_URL else 'NOT SET'} | SMTP: {SMTP_HOST}")

# ============== MARKET CONFIG ==============

IST          = pytz.timezone("Asia/Kolkata")
MARKET_OPEN  = time(9, 20)
MARKET_CLOSE = time(15, 20)

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
    "DIVISLAB", "APOLLOHOSP", "BAJAJ-AUTO", "COFORGE", "PIDILITIND",
]

NIFTY_100 = NIFTY_50 + [
    "BEL", "TRENT", "OFSS", "POLYCAB", "VOLTAS", "TATAELXSI", "LUPIN", "SIEMENS",
    "BSE", "CUMMINSIND", "ABB", "THERMAX", "NH", "MAXHEALTH", "VARROC", "CROMPTON",
    "AUROPHARMA", "BANDHANBNK", "BANKBARODA", "CANBK", "CHOLAFIN", "DIXON", "GODREJCP",
    "HAVELLS", "ICICIPRULI", "IDFCFIRSTB", "INDIGO", "IRCTC", "JINDALSTEL", "LALPATHLAB",
    "MARICO", "METROPOLIS", "MOTHERSON", "NAUKRI", "PAGEIND", "PERSISTENT",
    "PETRONET", "PNB", "QUESS", "RBLBANK", "RECLTD", "SAIL", "SANOFI", "TATACOMM",
    "TATATECH", "TORNTPOWER", "UCOBANK", "UNIONBANK", "UPL", "ZYDUSLIFE",
]
