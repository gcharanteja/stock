"""
smtp.py — HTML email notifications via Brevo SMTP
"""
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from app.config import FROM_EMAIL, IST, SMTP_HOST, SMTP_PORT, SMTP_PASS, SMTP_USER, TO_EMAIL
from app.database import EmailLogModel, get_db_session
from app.schemas import DeclinedStock, PriceAlert


def send_email_notification(
    alerts: List[PriceAlert],
    declined_stocks: Optional[List[DeclinedStock]] = None,
):
    """Build and send an HTML alert email, then log it to the DB."""
    if not alerts and not declined_stocks:
        return

    msg          = MIMEMultipart()
    msg["From"]  = FROM_EMAIL
    msg["To"]    = TO_EMAIL

    if declined_stocks and alerts:
        msg["Subject"] = f"🚨 Stock Alert - {len(alerts)} Portfolio + {len(declined_stocks)} Nifty Stocks Down!"
    elif declined_stocks:
        msg["Subject"] = f"📉 Nifty Screener - {len(declined_stocks)} Stocks Down Significantly!"
    else:
        msg["Subject"] = f"Stock Alert - {len(alerts)} Alert(s)!"

    # ---- HTML body ----
    body = "<html><body><h2>Stock Price Alert</h2>"

    if alerts:
        body += (
            "<h3 style='color:orange;'>📊 Portfolio Alerts</h3>"
            "<table border='1' style='border-collapse:collapse;width:100%;'>"
            "<tr><th>Symbol</th><th>Buy Price</th><th>Current</th><th>Alert</th><th>Details</th></tr>"
        )
        for a in alerts:
            if a.alert_type == "52_week_high_reached":
                details = f"52W High: ₹{a.high_price} | +{a.potential_return}%"
            elif a.alert_type == "100_week_high_reached":
                details = f"100W High: ₹{a.high_price} | +{a.potential_return}%"
            elif a.alert_type == "52_week_low_near":
                details = f"52W Low: ₹{a.low_price} | Buying Opportunity!"
            elif a.alert_type == "target_price_reached":
                details = f"Target: ₹{a.target_price} | +{a.potential_return}%"
            else:
                details = ""
            body += (
                f"<tr><td>{a.symbol}</td><td>₹{a.buy_price}</td>"
                f"<td>₹{a.current_price}</td><td>{a.alert_type}</td><td>{details}</td></tr>"
            )
        body += "</table>"

    if declined_stocks:
        body += (
            "<h3 style='color:red;'>📉 Nifty Buying Opportunities</h3>"
            "<table border='1' style='border-collapse:collapse;width:100%;'>"
            "<tr><th>Symbol</th><th>Price</th><th>Sector</th><th>3M</th><th>6M</th><th>1Y</th></tr>"
        )
        for s in declined_stocks:
            body += (
                f"<tr><td>{s.symbol}</td><td>₹{s.current_price}</td><td>{s.sector or 'N/A'}</td>"
                f"<td>{'↓'+str(s.decline_3m)+'%' if s.decline_3m else '-'}</td>"
                f"<td>{'↓'+str(s.decline_6m)+'%' if s.decline_6m else '-'}</td>"
                f"<td>{'↓'+str(s.decline_1y)+'%' if s.decline_1y else '-'}</td></tr>"
            )
        body += "</table>"

    body += (
        f"<p style='color:gray;font-size:12px;'>"
        f"<i>Generated: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')} IST</i>"
        f"</p></body></html>"
    )
    msg.attach(MIMEText(body, "html"))

    # ---- Send ----
    status = "failed"
    try:
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        status = "sent"
        print(f"✅ Email sent! Alerts: {len(alerts)}, Declined: {len(declined_stocks) if declined_stocks else 0}")
    except Exception as e:
        print(f"❌ Email failed: {e}")

    # ---- Log to DB ----
    with get_db_session() as db:
        try:
            db.add(EmailLogModel(
                subject=msg["Subject"],
                recipient=TO_EMAIL,
                alerts_count=len(alerts),
                declined_count=len(declined_stocks) if declined_stocks else 0,
                status=status,
            ))
            db.commit()
        except Exception:
            db.rollback()
