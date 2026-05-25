# RSI Monitor

Monitors RSI for a list of stocks every 5 minutes during market hours. Sends a Gmail alert when any ticker crosses the oversold (<30) or overbought (>70) threshold, and publishes an HTML dashboard to the repo.

## How it works

- **GitHub Actions** runs `rsi_monitor.py` on a `*/5 * * * *` cron schedule
- If the market is open, it fetches 5-day / 5-minute candle data via `yfinance` and computes a 14-bar RSI for each ticker
- Stocks outside the RSI thresholds trigger an email alert
- An `index.html` dashboard is written and committed back to the repo on every run

## Setup

### 1. Add GitHub Secrets

Go to **Settings → Secrets and variables → Actions** in your repo and add:

| Secret | Value |
|---|---|
| `EMAIL_FROM` | Gmail address to send alerts from |
| `EMAIL_TO` | Address to receive alerts |
| `EMAIL_PASSWORD` | Gmail [App Password](https://myaccount.google.com/apppasswords) (not your account password) |

> Gmail requires a 16-character App Password. Enable 2-Step Verification first, then generate one at the link above.

### 2. Enable GitHub Actions

Make sure Actions are enabled in your repo (**Settings → Actions → General → Allow all actions**).

The workflow will start running automatically every 5 minutes.

### 3. (Optional) Trigger manually

Go to **Actions → RSI Monitor → Run workflow** to run it immediately.

## Run locally

```bash
pip install yfinance pandas numpy pytz

export EMAIL_FROM="you@gmail.com"
export EMAIL_TO="you@gmail.com"
export EMAIL_PASSWORD="your-app-password"

python rsi_monitor.py
```

This writes `index.html` to the current directory and prints RSI values to stdout. An email is only sent if a threshold is crossed.

## Configuration

Edit the top of `rsi_monitor.py`:

```python
TICKERS    = ["AAPL", "TSLA", "NVDA", "MSFT"]  # stocks to watch
RSI_PERIOD = 14                                  # RSI lookback bars
RSI_LOW    = 30                                  # oversold threshold
RSI_HIGH   = 70                                  # overbought threshold
```
