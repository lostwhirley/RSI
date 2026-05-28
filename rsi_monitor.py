import json
import os
import smtplib
import pytz
import yfinance as yf
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- Configure these ---
TICKERS    = ["AAPL", "AMZN", "ASML", "BTC-USD", "GDXU", "GGLL", "GLW", "GOOG", "JNUG", "META", "MU", "MUU", "MSFT", "NVDA", "NVDL", "SPXL", "TQQQ", "TSM", "TSLA"]
RSI_PERIOD = 14
RSI_LOW    = 30
RSI_HIGH   = 70
# -----------------------

EMAIL_FROM          = os.environ["EMAIL_FROM"]
EMAIL_TO            = os.environ["EMAIL_TO"]
EMAIL_PASSWORD      = os.environ["EMAIL_PASSWORD"]
PHONE_TO            = os.environ.get("PHONE_TO", "")
SMS_CARRIER_GATEWAY = "tmomail.net"


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
    hist = ticker.history(period="3mo", interval="1d", auto_adjust=False)
    if hist.empty or len(hist) < RSI_PERIOD + 1:
        return None, None

    close = hist["Close"]
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)

    avg_gain = gain.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD, adjust=False).mean()
    avg_loss = loss.ewm(com=RSI_PERIOD - 1, min_periods=RSI_PERIOD, adjust=False).mean()

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


def send_sms(alerts: list[dict]) -> None:
    if not PHONE_TO:
        return
    lines = ", ".join(
        f"{a['ticker']} {a['rsi']} ({'overbought' if a['rsi'] > RSI_HIGH else 'oversold'})"
        for a in alerts
    )
    msg = MIMEText(f"RSI Alert: {lines}", "plain")
    msg["From"]    = EMAIL_FROM
    msg["To"]      = f"{PHONE_TO}@{SMS_CARRIER_GATEWAY}"
    msg["Subject"] = ""
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, f"{PHONE_TO}@{SMS_CARRIER_GATEWAY}", msg.as_string())
    print(f"SMS sent to {PHONE_TO}@{SMS_CARRIER_GATEWAY}")


def generate_dashboard(results: list[dict], market_open: bool) -> None:
    init_results = [
        {"ticker": r["ticker"], "rsi": r.get("rsi"), "price": r.get("price")}
        for r in results
    ]
    cfg = {
        "tickers":          TICKERS,
        "RSI_PERIOD":       RSI_PERIOD,
        "RSI_LOW":          RSI_LOW,
        "RSI_HIGH":         RSI_HIGH,
        "alertEmail":       os.environ.get("EMAIL_TO", "lostwhirley@gmail.com"),
        "ejsPublicKey":     os.environ.get("EMAILJS_PUBLIC_KEY", ""),
        "ejsServiceId":     os.environ.get("EMAILJS_SERVICE_ID", ""),
        "ejsTemplateId":    os.environ.get("EMAILJS_TEMPLATE_ID", ""),
        "phoneNumber":      PHONE_TO,
        "smsGateway":       SMS_CARRIER_GATEWAY,
        "initResults":      init_results,
    }
    cfg_js = f"const CFG={json.dumps(cfg)};"

    js_logic = """
let _timer = null, _countdown = null, _tickers = [];

function computeRSI(closes) {
  var P = CFG.RSI_PERIOD;
  if (closes.length < P + 1) return null;
  var d = closes.slice(1).map((c, i) => c - closes[i]);
  var ag = 0, al = 0;
  for (var i = 0; i < P; i++) { ag += Math.max(d[i], 0); al += Math.max(-d[i], 0); }
  ag /= P; al /= P;
  for (var i = P; i < d.length; i++) {
    ag = (ag * (P - 1) + Math.max(d[i], 0)) / P;
    al = (al * (P - 1) + Math.max(-d[i], 0)) / P;
  }
  return al === 0 ? 100 : +(100 - 100 / (1 + ag / al)).toFixed(2);
}

async function fetchRSI(sym) {
  var base = "https://query1.finance.yahoo.com/v8/finance/chart/" + sym
    + "?interval=1d&range=3mo&includePrePost=false";
  try {
    var r = await fetch("https://corsproxy.io/?" + encodeURIComponent(base));
    var data = await r.json();
    var cl = data.chart.result[0].indicators.quote[0].close.filter(c => c != null);
    return { ticker: sym, rsi: computeRSI(cl), price: +(cl.at(-1).toFixed(2)), closes: cl };
  } catch(e) {
    return { ticker: sym, rsi: null, price: null };
  }
}

function isMarketOpen() {
  var et = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
  if (et.getDay() === 0 || et.getDay() === 6) return false;
  var mins = et.getHours() * 60 + et.getMinutes();
  return mins >= 9 * 60 + 30 && mins < 16 * 60;
}

function updateMarketBadge() {
  var open = isMarketOpen();
  var el = document.getElementById("market-badge");
  el.className = "market-badge " + (open ? "open" : "closed");
  document.getElementById("market-text").textContent = open ? "market open" : "market closed";
}

function getTickers() { return _tickers.slice(); }

function renderTickers() {
  var chips = _tickers.map(function(t) {
    var onclick = "removeTicker('" + t + "')";
    return '<span class="ticker-chip">' + t
      + '<button onclick="' + onclick + '">&times;</button></span>';
  }).join('');
  document.getElementById('ticker-tags').innerHTML = chips
    + '<input class="ticker-input" id="ticker-input" placeholder="add…" maxlength="6">';
  document.getElementById('ticker-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      var val = this.value.trim().toUpperCase().replace(',', '');
      if (val && !_tickers.includes(val)) { _tickers.push(val); renderTickers(); }
      else this.value = '';
    }
  });
}

function removeTicker(t) {
  _tickers = _tickers.filter(function(x) { return x !== t; });
  renderTickers();
}

function cardHTML(ticker, rsi, price) {
  var cls = "card", rsiCls = "card-rsi empty", rsiVal = "\\u2014",
      sigCls = "card-signal muted", sigVal = "";
  if (rsi !== null && rsi !== undefined) {
    if (rsi > CFG.RSI_HIGH) {
      cls = "card overbought"; rsiCls = "card-rsi over";
      sigCls = "card-signal sig-over"; sigVal = "overbought";
    } else if (rsi < CFG.RSI_LOW) {
      cls = "card oversold"; rsiCls = "card-rsi under";
      sigCls = "card-signal sig-under"; sigVal = "oversold";
    } else {
      rsiCls = "card-rsi neutral"; sigCls = "card-signal sig-neutral"; sigVal = "neutral";
    }
    rsiVal = rsi;
  }
  var priceHTML = price ? '<div class="card-price">$' + price + '</div>' : "";
  var yhUrl = 'https://finance.yahoo.com/quote/' + ticker;
  return '<div class="' + cls + '" id="card-' + ticker + '">'
    + '<div class="card-ticker"><a href="' + yhUrl + '" target="_blank" rel="noopener" class="ticker-link">' + ticker + '</a></div>'
    + '<div class="' + rsiCls + '">' + rsiVal + '</div>'
    + '<div class="' + sigCls + '">' + sigVal + '</div>'
    + priceHTML + '</div>';
}

function renderCards(tickers, resultsMap) {
  document.getElementById("cards-grid").innerHTML = tickers
    .map(t => { var r = (resultsMap || {})[t] || {}; return cardHTML(t, r.rsi, r.price); })
    .join("");
}

function updateCard(ticker, rsi, price) {
  var el = document.getElementById("card-" + ticker);
  if (!el) return;
  var tmp = document.createElement("div");
  tmp.innerHTML = cardHTML(ticker, rsi, price);
  el.replaceWith(tmp.firstChild);
}

function sparklineSVG(closes) {
  var w = 120, h = 44, pad = 2;
  if (!closes || closes.length < 2) {
    return '<svg class="chart-sparkline" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">'
      + '<line x1="0" y1="22" x2="' + w + '" y2="22" stroke="#e8e6e0" stroke-width="1"/></svg>';
  }
  var min = Math.min.apply(null, closes), max = Math.max.apply(null, closes);
  var range = max - min || 1;
  var pts = closes.map(function(c, i) {
    var x = (i / (closes.length - 1)) * w;
    var y = pad + (h - pad * 2) * (1 - (c - min) / range);
    return x.toFixed(1) + ',' + y.toFixed(1);
  }).join(' ');
  var stroke = closes[closes.length - 1] >= closes[0] ? '#639922' : '#A32D2D';
  return '<svg class="chart-sparkline" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none">'
    + '<polyline points="' + pts + '" fill="none" stroke="' + stroke
    + '" stroke-width="1.5" stroke-linejoin="round"/></svg>';
}

function chartCardHTML(ticker, closes, rsi, price) {
  var cls = 'chart-card';
  if (rsi !== null && rsi !== undefined) {
    if (rsi > CFG.RSI_HIGH) cls += ' chart-overbought';
    else if (rsi < CFG.RSI_LOW) cls += ' chart-oversold';
  }
  var priceStr = price ? '$' + price : '';
  var rsiStr = (rsi !== null && rsi !== undefined) ? 'RSI ' + rsi : '';
  var yhUrl = 'https://finance.yahoo.com/quote/' + ticker;
  return '<div class="' + cls + '" id="chart-' + ticker + '">'
    + '<div class="chart-card-header"><span class="chart-label"><a href="' + yhUrl + '" target="_blank" rel="noopener" class="ticker-link">' + ticker + '</a></span>'
    + '<span class="chart-meta">' + priceStr + '</span></div>'
    + sparklineSVG(closes)
    + (rsiStr ? '<div class="chart-rsi-label">' + rsiStr + '</div>' : '')
    + '</div>';
}

function renderCharts(tickers, resultsMap) {
  var el = document.getElementById('chart-grid');
  if (!el) return;
  el.innerHTML = tickers.map(function(t) {
    var r = (resultsMap || {})[t] || {};
    return chartCardHTML(t, r.closes, r.rsi, r.price);
  }).join('');
}

function updateChart(ticker, closes, rsi, price) {
  var el = document.getElementById('chart-' + ticker);
  if (!el) return;
  var tmp = document.createElement('div');
  tmp.innerHTML = chartCardHTML(ticker, closes, rsi, price);
  el.replaceWith(tmp.firstChild);
}

function setStatus(msg) {
  document.getElementById("status-text").textContent = msg;
}

function showAlertBanner(alerts, phone, testMode, smsSent) {
  var banner = document.getElementById("alert-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "alert-banner";
    document.getElementById("cards-grid").insertAdjacentElement("beforebegin", banner);
  }
  var lines = alerts.map(a =>
    a.ticker + ": RSI " + a.rsi + " (" + (a.rsi > CFG.RSI_HIGH ? "overbought" : "oversold") + ")"
  ).join(", ");
  var smsNote = phone && smsSent ? " \\u00b7 text sent" : "";
  banner.className = "alert-banner" + (testMode ? " test" : "");
  banner.textContent = (testMode ? "[test] " : "") + "Alert \\u2014 " + lines + smsNote;
}

async function sendAlertSMS(alerts, phone, testMode) {
  if (!CFG.ejsPublicKey || !CFG.ejsServiceId || !CFG.ejsTemplateId || !phone) return false;
  var digits = phone.replace(/\\D/g, '');
  if (!digits) return false;
  var smsAddr = digits + '@' + CFG.smsGateway;
  var lines = alerts.map(function(a) {
    return a.ticker + ' ' + a.rsi + ' (' + (a.rsi > CFG.RSI_HIGH ? 'overbought' : 'oversold') + ')';
  }).join(', ');
  try {
    await emailjs.send(CFG.ejsServiceId, CFG.ejsTemplateId, {
      to_email: smsAddr,
      subject:  (testMode ? '[TEST] ' : '') + 'RSI Alert',
      message:  (testMode ? '[TEST] ' : '') + 'RSI Alert: ' + lines
    }, CFG.ejsPublicKey);
    return true;
  } catch(e) {
    console.error('SMS error:', e);
    return false;
  }
}


function startCountdown(secs) {
  clearInterval(_countdown);
  var rem = secs;
  var el = document.getElementById("countdown");
  var tick = function() {
    if (rem < 0) { clearInterval(_countdown); el.textContent = ""; return; }
    el.textContent = "next in " + Math.floor(rem / 60) + ":" + String(rem % 60).padStart(2, "0");
    rem--;
  };
  tick();
  _countdown = setInterval(tick, 1000);
}

async function runCheck(forceRun, noAlerts) {
  var testMode = document.getElementById("test-mode").checked;
  var tickers = getTickers();
  if (!forceRun && !testMode && !isMarketOpen()) {
    setStatus("market closed");
    return;
  }
  setStatus("fetching\\u2026");
  tickers.forEach(t => {
    var c = document.getElementById("card-" + t);
    if (c) c.querySelector(".card-rsi").textContent = "\\u2026";
  });
  var results = await Promise.all(tickers.map(fetchRSI));
  if (testMode && results.length > 0) {
    results[0] = Object.assign({}, results[0], { rsi: 75 });
  }
  results.forEach(r => updateCard(r.ticker, r.rsi, r.price));
  results.forEach(r => updateChart(r.ticker, r.closes, r.rsi, r.price));
  var banner = document.getElementById("alert-banner");
  if (banner) banner.remove();
  var alerts = results.filter(r => r.rsi !== null && (r.rsi < CFG.RSI_LOW || r.rsi > CFG.RSI_HIGH));
  var phone = document.getElementById("alert-phone").value.trim();
  if (alerts.length && !noAlerts) {
    var smsSent = await sendAlertSMS(alerts, phone, testMode);
    showAlertBanner(alerts, phone, testMode, smsSent);
  }
  var now = new Date().toLocaleTimeString("en-US",
    { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit" });
  setStatus("last checked " + now + " ET" + (testMode ? " \\u00b7 test mode" : ""));
}

function startMonitor() {
  var tickers = getTickers();
  var resultsMap = {};
  CFG.initResults.forEach(r => { resultsMap[r.ticker] = r; });
  renderCards(tickers, resultsMap);
  document.getElementById("start-btn").style.display = "none";
  document.getElementById("running-controls").style.display = "flex";
  runCheck(true);
  startCountdown(5 * 60);
  _timer = setInterval(function() { runCheck(false); startCountdown(5 * 60); }, 5 * 60 * 1000);
}

function stopMonitor() {
  clearInterval(_timer); clearInterval(_countdown); _timer = null;
  document.getElementById("countdown").textContent = "";
  document.getElementById("start-btn").style.display = "";
  document.getElementById("running-controls").style.display = "none";
  setStatus("");
}

(function init() {
  var resultsMap = {};
  CFG.initResults.forEach(r => { resultsMap[r.ticker] = r; });
  renderCards(CFG.tickers, resultsMap);
  renderCharts(CFG.tickers, resultsMap);
  _tickers = CFG.tickers.slice();
  renderTickers();
  document.getElementById("alert-phone").value = CFG.phoneNumber || "5743836464";
  updateMarketBadge();
  setInterval(updateMarketBadge, 60000);
  runCheck(true, true);
})();
"""

    script_tag = f"<script>{cfg_js}{js_logic}</script>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Relative Strength Index (RSI 14)</title>
  <script src="https://cdn.jsdelivr.net/npm/@emailjs/browser@4/dist/email.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f2; color: #1a1a1a; min-height: 100vh; padding: 2rem 1rem; }}
    .container {{ max-width: 900px; margin: 0 auto; }}
    header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.75rem; flex-wrap: wrap; gap: 8px; }}
    h1 {{ font-size: 22px; font-weight: 500; }}
    .header-right {{ display: flex; align-items: center; gap: 14px; }}
    .market-badge {{ font-size: 12px; display: flex; align-items: center; gap: 6px; color: #888; }}
    .market-badge .dot {{ width: 8px; height: 8px; border-radius: 50%; background: #bbb; display: inline-block; }}
    .market-badge.open {{ color: #3B6D11; }} .market-badge.open .dot {{ background: #639922; }}
    .test-label {{ font-size: 12px; display: flex; align-items: center; gap: 5px; cursor: pointer; color: #555; user-select: none; }}
    .test-label input {{ cursor: pointer; accent-color: #4A90D9; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 1.5rem; }}
    .card {{ background: #fff; border: 0.5px solid #e0ddd6; border-radius: 12px; padding: 16px 18px; }}
    .card.overbought {{ background: #FCEBEB; border-color: #F09595; }}
    .card.oversold   {{ background: #E6F2FB; border-color: #90C4E8; }}
    .card-ticker {{ font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: .06em; color: #888; margin-bottom: 8px; }}
    .card-rsi {{ font-size: 32px; font-weight: 500; font-family: "SF Mono", "Fira Code", monospace; line-height: 1; margin-bottom: 4px; }}
    .card-rsi.over    {{ color: #A32D2D; }} .card-rsi.under   {{ color: #3B6D11; }}
    .card-rsi.neutral {{ color: #555; }}    .card-rsi.empty   {{ color: #bbb; }}
    .card-signal {{ font-size: 11px; text-transform: uppercase; letter-spacing: .05em; margin-bottom: 4px; }}
    .sig-over {{ color: #A32D2D; }} .sig-under {{ color: #1A6FA8; }} .sig-neutral {{ color: #888; }} .muted {{ color: #bbb; }}
    .card-price {{ font-size: 12px; color: #888; font-family: "SF Mono", "Fira Code", monospace; margin-top: 2px; }}
    .divider {{ border: none; border-top: 0.5px solid #e0ddd6; margin-bottom: 1.5rem; }}
    .top-bar {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 1.5rem; flex-wrap: wrap; }}
    .top-bar-left {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
    .top-bar-right {{ display: flex; align-items: center; gap: 8px; }}
    .alert-label {{ font-size: 12px; color: #888; white-space: nowrap; }}
    .top-bar-right input {{ padding: 7px 10px; border: 0.5px solid #e0ddd6; border-radius: 8px; font-size: 13px; background: #fff; font-family: inherit; color: #1a1a1a; width: 210px; }}
    .top-bar-right input:focus {{ outline: none; border-color: #999; }}
    .controls {{ margin-bottom: 1.25rem; }}
    .field label {{ font-size: 12px; color: #888; display: block; margin-bottom: 8px; text-align: center; font-weight: 600; }}
    .ticker-tags {{ display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 10px; border: 0.5px solid #e0ddd6; border-radius: 8px; background: #fff; min-height: 42px; align-items: center; }}
    .ticker-chip {{ display: inline-flex; align-items: center; gap: 3px; background: #ede9e3; border-radius: 5px; padding: 3px 7px 3px 9px; font-size: 12px; font-weight: 500; letter-spacing: .04em; }}
    .ticker-chip button {{ background: none; border: none; cursor: pointer; color: #999; font-size: 15px; line-height: 1; padding: 0 0 0 2px; }}
    .ticker-chip button:hover {{ color: #333; }}
    .ticker-input {{ border: none; outline: none; font-size: 13px; padding: 2px 0; min-width: 70px; background: transparent; font-family: inherit; }}
    .btn {{ padding: 8px 18px; border-radius: 8px; font-size: 14px; font-weight: 500; cursor: pointer; border: 1px solid; font-family: inherit; background: #fff; }}
    .btn-start {{ border-color: #ccc; color: #1a1a1a; }} .btn-start:hover {{ border-color: #999; }}
    .btn-stop  {{ border-color: #E05050; color: #C0392B; }} .btn-stop:hover {{ background: #FFF5F5; }}
    .btn-check {{ border-color: #ccc; color: #1a1a1a; }} .btn-check:hover {{ border-color: #999; }}
    #running-controls {{ display: none; align-items: center; gap: 10px; }}
    #countdown {{ font-size: 13px; color: #888; }}
    #status-text {{ font-size: 12px; color: #aaa; }}
    .alert-banner {{ background: #FCEBEB; border: 1px solid #F09595; border-radius: 8px; padding: 10px 14px; font-size: 13px; color: #A32D2D; margin-bottom: 1rem; }}
    .alert-banner.test {{ background: #FFF8E8; border-color: #F0C070; color: #8A6000; }}
    @media (max-width: 520px) {{ .top-bar {{ flex-direction: column; align-items: flex-start; }} .top-bar-right input {{ width: 100%; }} }}
    .chart-section {{ margin-top: 1.5rem; }}
    .chart-section-title {{ font-size: 12px; color: #888; margin-bottom: 10px; text-align: center; }}
    .chart-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }}
    .chart-card {{ background: #fff; border: 0.5px solid #e0ddd6; border-radius: 10px; padding: 10px 12px 8px; }}
    .chart-card.chart-overbought {{ background: #FCEBEB; border-color: #F09595; }}
    .chart-card.chart-oversold {{ background: #E6F2FB; border-color: #90C4E8; }}
    .chart-card-header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }}
    .chart-label {{ font-size: 10px; font-weight: 500; text-transform: uppercase; letter-spacing: .06em; color: #888; }}
    .ticker-link {{ color: inherit; text-decoration: none; }}
    .ticker-link:hover {{ text-decoration: underline; }}
    .chart-meta {{ font-size: 10px; color: #aaa; font-family: "SF Mono", "Fira Code", monospace; }}
    .chart-sparkline {{ width: 100%; height: 44px; display: block; }}
    .chart-rsi-label {{ font-size: 10px; color: #aaa; text-align: right; margin-top: 3px; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>Relative Strength Index (RSI 14)</h1>
      <div class="header-right">
        <label class="test-label">
          <input type="checkbox" id="test-mode"> test mode
        </label>
        <span class="market-badge closed" id="market-badge">
          <span class="dot"></span><span id="market-text">market closed</span>
        </span>
      </div>
    </header>
    <div class="top-bar">
      <div class="top-bar-left">
        <button class="btn btn-start" id="start-btn" onclick="startMonitor()">Start</button>
        <div id="running-controls">
          <button class="btn btn-stop" onclick="stopMonitor()">Stop</button>
          <button class="btn btn-check" onclick="runCheck(true)">Check now</button>
          <span id="countdown"></span>
        </div>
        <span id="status-text"></span>
      </div>
      <div class="top-bar-right">
        <span class="alert-label">Text to:</span>
        <input type="text" id="alert-phone" placeholder="10-digit" style="width:140px">
      </div>
    </div>
    <div class="controls" id="controls-section">
      <div class="field">
        <label>Stocks</label>
        <div class="ticker-tags" id="ticker-tags"></div>
      </div>
    </div>
    <div class="cards" id="cards-grid"></div>
    <hr class="divider">
    <div class="chart-section">
      <div class="chart-section-title">3-month price history</div>
      <div class="chart-grid" id="chart-grid"></div>
    </div>
  </div>
  {script_tag}
</body>
</html>"""

    with open("index.html", "w") as f:
        f.write(html)
    print("Dashboard written to index.html")


def main() -> None:
    market_open = is_market_open()
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
        send_sms(alerts)
        send_email(alerts)
    else:
        print("No alerts triggered.")


if __name__ == "__main__":
    main()
