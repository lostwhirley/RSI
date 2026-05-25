import os
import smtplib
import pytz
import yfinance as yf
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- Configure these ---
TICKERS    = ["AAPL", "TSLA", "NVDA", "MSFT"]
RSI_PERIOD = 14
RSI_LOW    = 30
RSI_HIGH   = 70
# -----------------------

EMAIL_FROM     = os.environ["EMAIL_FROM"]
EMAIL_TO       = os.environ["EMAIL_TO"]
EMAIL_PASSWORD = os.environ["EMAIL_PASSWORD"]


def is_market_open() -> bool:
    eastern = pytz.timezone("America/New_York")
    now = datetime.now(eastern)
    if now.weekday() >= 5:
        return False
    opens  = now.replace(hour=9,  minute=30, second=0, microsecond=0)
    closes = now.replace(hour=16, minute=0,  second=0, microsecond=0)
    return opens <= now <= closes


def calculate_rsi(symbol: str) -> tuple[float | None, float | None]:
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="5d", interval="5m")
    if hist.empty or len(hist) < RSI_PERIOD + 1:
        return None, None

    close = hist["Close"]
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)

    avg_gain = gain.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD).mean()
    avg_loss = loss.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD).mean()

    rs  = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    price = round(float(close.iloc[-1]), 2)
    return round(float(rsi.iloc[-1]), 2), price


def send_email(alerts: list[dict]) -> None:
    now_str = datetime.now(pytz.timezone("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    lines = "\n".join(
        f"  • {a['ticker']}: RSI {a['rsi']} "
        f"({'OVERSOLD — potential buy' if a['rsi'] < RSI_LOW else 'OVERBOUGHT — potential sell'})"
        f"{' @ $' + str(a['price']) if a['price'] else ''}"
        for a in alerts
    )
    body = (
        f"RSI Alert — {now_str}\n\n"
        f"The following stocks crossed RSI thresholds:\n\n"
        f"{lines}\n\n"
        f"Thresholds: oversold < {RSI_LOW}, overbought > {RSI_HIGH}\n"
        f"Period: {RSI_PERIOD}-bar RSI on 5-minute candles"
    )
    msg = MIMEMultipart()
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg["Subject"] = f"RSI Alert — {now_str}"
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
    print(f"Alert sent for: {[a['ticker'] for a in alerts]}")


def generate_dashboard(results: list[dict], market_open: bool) -> None:
    now_et = datetime.now(pytz.timezone("America/New_York"))
    now_str = now_et.strftime("%B %d, %Y at %I:%M %p ET")

    def card(r):
        rsi   = r.get("rsi")
        price = r.get("price")
        ticker = r["ticker"]

        if rsi is None:
            return f"""
            <div class="card">
              <div class="card-ticker">{ticker}</div>
              <div class="card-rsi empty">—</div>
              <div class="card-signal muted">no data</div>
            </div>"""

        if rsi > RSI_HIGH:
            card_cls, rsi_cls, signal, sig_cls = "card overbought", "over", "overbought", "sig-over"
        elif rsi < RSI_LOW:
            card_cls, rsi_cls, signal, sig_cls = "card oversold", "under", "oversold", "sig-under"
        else:
            card_cls, rsi_cls, signal, sig_cls = "card", "neutral", "neutral", "sig-neutral"

        price_html = f'<div class="card-price">${price}</div>' if price else ""
        return f"""
            <div class="{card_cls}">
              <div class="card-ticker">{ticker}</div>
              <div class="card-rsi {rsi_cls}">{rsi}</div>
              <div class="card-signal {sig_cls}">{signal}</div>
              {price_html}
            </div>"""

    cards_html = "\n".join(card(r) for r in results)
    market_status = "market open" if market_open else "market closed"
    market_cls    = "open" if market_open else "closed"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>RSI Monitor</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f2; color: #1a1a1a; min-height: 100vh; padding: 2rem 1rem; }}
    .container {{ max-width: 860px; margin: 0 auto; }}
    header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.75rem; flex-wrap: wrap; gap: 8px; }}
    h1 {{ font-size: 22px; font-weight: 500; }}
    .market-badge {{ font-size: 12px; display: flex; align-items: center; gap: 6px; }}
    .market-badge .dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}
    .market-badge.open {{ color: #3B6D11; }} .market-badge.open .dot {{ background: #639922; }}
    .market-badge.closed {{ color: #888; }} .market-badge.closed .dot {{ background: #bbb; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 2rem; }}
    .card {{ background: #fff; border: 0.5px solid #e0ddd6; border-radius: 12px; padding: 16px 18px; }}
    .card.overbought {{ background: #FCEBEB; border-color: #F09595; }}
    .card.oversold   {{ background: #EAF3DE; border-color: #C0DD97; }}
    .card-ticker {{ font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: .06em; color: #888; margin-bottom: 8px; }}
    .card-rsi {{ font-size: 32px; font-weight: 500; font-family: "SF Mono", "Fira Code", monospace; line-height: 1; margin-bottom: 4px; }}
    .card-rsi.over    {{ color: #A32D2D; }}
    .card-rsi.under   {{ color: #3B6D11; }}
    .card-rsi.neutral {{ color: #555; }}
    .card-rsi.empty   {{ color: #bbb; }}
    .card-signal {{ font-size: 11px; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 4px; }}
    .sig-over    {{ color: #A32D2D; }} .sig-under {{ color: #3B6D11; }}
    .sig-neutral {{ color: #888; }}    .muted {{ color: #bbb; }}
    .card-price {{ font-size: 12px; color: #888; font-family: "SF Mono", "Fira Code", monospace; margin-top: 2px; }}
    footer {{ font-size: 12px; color: #aaa; border-top: 0.5px solid #e0ddd6; padding-top: 1rem; }}
    @media (max-width: 480px) {{ .cards {{ grid-template-columns: repeat(2, 1fr); }} }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>RSI monitor</h1>
      <span class="market-badge {market_cls}"><span class="dot"></span>{market_status}</span>
    </header>
    <div class="cards">
      {cards_html}
    </div>
    <footer>Last updated: {now_str} &nbsp;·&nbsp; RSI period: {RSI_PERIOD} &nbsp;·&nbsp; Thresholds: &lt;{RSI_LOW} oversold, &gt;{RSI_HIGH} overbought</footer>
  </div>
</body>
</html>"""

    with open("index.html", "w") as f:
        f.write(html)
    print("Dashboard written to index.html")


def main() -> None:
    test_mode   = os.environ.get("TEST_MODE", "").lower() == "true"
    market_open = test_mode or is_market_open()
    results = []

    if not market_open:
        print("Market closed — updating dashboard with last known state.")
        for symbol in TICKERS:
            results.append({"ticker": symbol, "rsi": None, "price": None})
        generate_dashboard(results, market_open)
        return

    alerts = []
    for symbol in TICKERS:
        rsi, price = calculate_rsi(symbol)
        if rsi is None:
            print(f"{symbol}: could not compute RSI (insufficient data)")
            results.append({"ticker": symbol, "rsi": None, "price": None})
            continue
        print(f"{symbol}: RSI = {rsi}, price = {price}")
        results.append({"ticker": symbol, "rsi": rsi, "price": price})
        if rsi < RSI_LOW or rsi > RSI_HIGH:
            alerts.append({"ticker": symbol, "rsi": rsi, "price": price})

    generate_dashboard(results, market_open)

    if alerts:
        send_email(alerts)
    else:
        print("No alerts triggered.")


if __name__ == "__main__":
    main()
