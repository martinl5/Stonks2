"""Daily stock alert job (runs on GitHub Actions, see .github/workflows/daily-job.yml).

Each run sends to Telegram:
  1. Per-stock Buy/Hold/Sell recommendations vs Damodaran industry benchmarks
  2. A McClellan Oscillator trend chart with breadth-thrust detection
  3. A VIX analysis chart with warning/high-fear thresholds
  4. A crash-protection status from VIX level + VIX3M/VIX term structure

Credentials come from the TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment
variables (repo Actions secrets). Stock symbols and recommendation multipliers
are read from config.yaml, with hardcoded fallbacks if it is missing.

The four sections run independently: a failure in one is reported (and fails
the Actions run via the exit code) but never stops the others.
"""
import math
import os
import re
import sys
import time
import traceback
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

import matplotlib
matplotlib.use('Agg')  # headless CI runner: render charts without a display
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yaml
from bs4 import BeautifulSoup
from yahooquery import Ticker


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_TIMEOUT = 20

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')

DEFAULT_STOCKS = ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'HSY', 'KO', 'PEP',
                  'NKE', 'V', 'INTC', 'NVDA', 'AMD', 'IBM', 'ORCL', 'ASML']

DEFAULT_RECOMMENDATION = {
    'buy_pe_multiplier': 0.85,
    'buy_pb_multiplier': 0.85,
    'sell_pe_multiplier': 1.15,
    'sell_pb_multiplier': 1.15,
}


def load_config():
    """Symbols and recommendation multipliers from config.yaml, with fallbacks."""
    try:
        with open(CONFIG_PATH) as f:
            cfg = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as e:
        print(f"⚠ Could not read config.yaml ({e}); using built-in defaults")
        cfg = {}
    rec = cfg.get('recommendation') or {}
    rec_cfg = {**DEFAULT_RECOMMENDATION,
               **{k: v for k, v in rec.items() if k in DEFAULT_RECOMMENDATION}}
    symbols = (cfg.get('monitored_stocks') or {}).get('symbols') or DEFAULT_STOCKS
    return list(symbols), rec_cfg


STOCKS, REC_CFG = load_config()

PE_URL = 'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/pedata.html'
PB_URL = 'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/pbvdata.html'

# Map Yahoo industry names onto Damodaran's industry naming
INDUSTRY_MAP = {
    'Semiconductors': 'Semiconductor',
    'Semiconductor Equipment & Materials': 'Semiconductor',
    'Software - Infrastructure': 'Software (System & Application)',
    'Information Technology Services': 'Software (System & Application)',
    'Consumer Electronics': 'Software (Entertainment)',
    'Internet Content & Information': 'Software (Internet)',
    'Internet Retail': 'Software (Internet)',
    'Confectioners': 'Food Processing',
    'Beverages - Non-Alcoholic': 'Beverage (Soft)',
    'Credit Services': 'Financial Svcs. (Non-bank & Insurance)',
    'Footwear & Accessories': 'Apparel',
}

VIX_THRESHOLD = 30
VIX_NEAR_THRESHOLD = 28
VIX_STRESS_LEVEL = 25
VIX_CRASH_LEVEL = 40
TERM_STRESS_RATIO = 0.9


# ---------------------------------------------------------------------------
# Shared numeric helpers
# ---------------------------------------------------------------------------

def is_num(value):
    """True for real numbers that are not NaN."""
    try:
        return value is not None and not math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def first_valid(*values, default=np.nan):
    """Return the first value that is not None/NaN."""
    for v in values:
        if is_num(v):
            return v
    return default


def fmt(value, spec=".2f", missing="N/A"):
    """Format a number, returning `missing` for None/NaN instead of raising."""
    return format(float(value), spec) if is_num(value) else missing


def normalize_dividend_yield(raw):
    """Return dividend yield in percent.

    Yahoo has flip-flopped between returning a fraction (0.0044) and a
    percent (0.44) for dividendYield, so detect the unit instead of
    blindly multiplying by 100.
    """
    if not is_num(raw):
        return np.nan
    if raw > 1:  # no fraction-style yield exceeds 100%, so this is already a percent
        return raw
    pct = raw * 100
    return raw if pct > 25 else pct  # >25% yield is implausible: raw was already a percent


def estimate_intrinsic_value(eps, growth_rate):
    """Graham intrinsic value: EPS x (8.5 + 2g), with g = expected growth in percent.

    Growth is clamped to [0, 25]% so one-off earnings swings don't distort
    the estimate. Returns NaN for missing data or non-positive EPS.
    """
    if not is_num(eps) or eps <= 0 or not is_num(growth_rate):
        return np.nan
    g_pct = min(max(growth_rate * 100, 0), 25)
    return eps * (8.5 + 2 * g_pct)


# ---------------------------------------------------------------------------
# Stock data
# ---------------------------------------------------------------------------

def get_stock_data(stock):
    t = Ticker(stock)

    # Extract data from different modules
    summary = t.summary_detail.get(stock, {})
    key_stats = t.key_stats.get(stock, {})
    fin_data = t.financial_data.get(stock, {})
    asset_profile = t.asset_profile.get(stock, {})

    # Prefer the live quote; fall back to the previous close
    stock_price = first_valid(
        summary.get('regularMarketPrice'),
        fin_data.get('currentPrice'),
        summary.get('regularMarketPreviousClose'),
    )

    # Check for 'trailingPE', then 'forwardPE', and fallback to NaN
    pe_ratio = first_valid(summary.get('trailingPE'), summary.get('forwardPE'))

    pb_ratio = first_valid(key_stats.get('priceToBook'))

    dividend_yield = normalize_dividend_yield(summary.get('dividendYield'))

    # Default industry to 'Unknown' if missing
    industry = asset_profile.get('industry', 'Unknown')

    # Get the mean and median analyst target prices
    mean_recommendation = first_valid(fin_data.get('targetMeanPrice'))
    median_recommendation = first_valid(fin_data.get('targetMedianPrice'))

    # Graham intrinsic value from EPS and expected earnings growth
    growth_rate = fin_data.get('earningsGrowth')
    eps = key_stats.get('trailingEps')
    financial_intrinsic_value = estimate_intrinsic_value(eps, growth_rate)

    return stock_price, pe_ratio, pb_ratio, dividend_yield, mean_recommendation, median_recommendation, financial_intrinsic_value, industry


# ---------------------------------------------------------------------------
# Telegram send helpers
# ---------------------------------------------------------------------------

def send_telegram_message(message, parse_mode=None):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    for attempt in range(2):
        try:
            response = requests.post(url, data=payload, timeout=TELEGRAM_TIMEOUT)
        except requests.RequestException as e:
            print(f"Failed to send message: {e}")
            return False
        if response.status_code == 200:
            print("Message sent successfully!")
            return True
        if response.status_code == 429 and attempt == 0:
            # Honour Telegram's rate-limit hint, then retry once
            try:
                retry_after = response.json()["parameters"]["retry_after"]
            except Exception:
                retry_after = 3
            time.sleep(retry_after)
            continue
        print(f"Failed to send message. Status code: {response.status_code}")
        return False
    return False


def send_in_batches(blocks, max_len=3500, pause=1.0):
    """Send text blocks packed into as few messages as possible.

    Telegram caps messages at 4096 chars, so pack greedily under
    `max_len` and pause between sends to stay clear of rate limits.
    """
    separator = "\n----------------\n"
    batch = ""
    for block in blocks:
        candidate = batch + (separator if batch else "") + block
        if batch and len(candidate) > max_len:
            send_telegram_message(batch)
            time.sleep(pause)
            batch = block
        else:
            batch = candidate
    if batch:
        send_telegram_message(batch)


def send_telegram_photo(message, chart_path):
    """Send a chart image with an HTML caption to Telegram."""
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    with open(chart_path, 'rb') as photo:
        payload = {
            'chat_id': CHAT_ID,
            'caption': message,
            'parse_mode': 'HTML'
        }
        files = {'photo': photo}
        try:
            r = requests.post(url, data=payload, files=files, timeout=30)
            if r.status_code == 200:
                print("✓ Chart and Message sent!")
            else:
                print(f"✗ Failed: {r.text}")
        except Exception as e:
            print(f"✗ Connection Error: {e}")


# ---------------------------------------------------------------------------
# Industry-average PE and PB benchmarks (Damodaran / NYU Stern)
# ---------------------------------------------------------------------------

def http_get(url, timeout=20, retries=3, backoff=2):
    """GET with retries; only falls back to verify=False on SSL errors."""
    last_error = None
    verify = True
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=timeout, verify=verify)
            response.raise_for_status()
            return response
        except requests.exceptions.SSLError as e:
            last_error = e
            verify = False  # Damodaran's cert chain is occasionally broken
        except requests.RequestException as e:
            last_error = e
        time.sleep(backoff ** attempt)
    raise last_error


def safe_float(text, default=np.nan):
    """'22.41' -> 22.41; 'NA', '', '-' -> default. Never raises."""
    if text is None:
        return default
    if isinstance(text, (int, float)):
        return float(text)
    try:
        return float(str(text).replace(',', '').replace('%', '').strip())
    except ValueError:
        return default


def parse_industry_table(html, header_keywords, fallback_col, min_rows=50):
    """Map industry name -> value from the first table on a Damodaran page.

    The value column is located by header name so a layout change can't
    silently shift us onto the wrong metric; `fallback_col` preserves the
    historical fixed index when no header matches. Values are coerced to
    float at parse time ('NA' and friends become NaN).
    """
    soup = BeautifulSoup(html, 'html.parser')
    rows = soup.find_all('table')[0].find_all('tr')

    header_cells = [c.get_text(' ', strip=True).lower() for c in rows[0].find_all(['td', 'th'])]
    value_col = fallback_col
    for i, header in enumerate(header_cells):
        if any(keyword in header for keyword in header_keywords):
            value_col = i
            break

    averages = {}
    for row in rows[1:]:
        items = row.find_all('td')
        if len(items) <= value_col:
            continue
        industry = re.sub(r'\s+', ' ', items[0].get_text(' ', strip=True)).strip()
        if industry:
            averages[industry] = safe_float(items[value_col].get_text(strip=True))

    if len(averages) < min_rows:
        raise ValueError(f"only parsed {len(averages)} industries - page layout may have changed")
    return averages


def get_industry_averages(url, header_keywords, fallback_col, label):
    try:
        return parse_industry_table(http_get(url).content, header_keywords, fallback_col)
    except Exception as e:
        print(f"⚠ Failed to load industry {label} benchmarks: {e}")
        send_telegram_message(
            f"⚠️ Industry {label} benchmark scrape failed ({e}). "
            "Recommendations will show 'Hold (benchmark unavailable)'."
        )
        return {}


def get_pe_average(industry, pe_averages):
    return pe_averages.get(industry, np.nan)


def get_pb_average(industry, pb_averages):
    return pb_averages.get(industry, np.nan)


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

def recommend(pe, pb, pe_avg, pb_avg):
    """Buy/Sell require a margin vs the industry average (see config.yaml)."""
    if not all(is_num(v) for v in (pe, pb, pe_avg, pb_avg)):
        return 'Hold (benchmark unavailable)'
    if pe < pe_avg * REC_CFG['buy_pe_multiplier'] and pb < pb_avg * REC_CFG['buy_pb_multiplier']:
        return 'Buy'
    if pe > pe_avg * REC_CFG['sell_pe_multiplier'] and pb > pb_avg * REC_CFG['sell_pb_multiplier']:
        return 'Sell'
    return 'Hold'


def run_stock_recommendations():
    """Fetch all monitored stocks, build recommendations, send to Telegram."""
    # Column 3 has historically been Trailing PE (matching the stocks'
    # trailingPE), column 2 on the PBV page the industry price/book ratio.
    pe_averages = get_industry_averages(PE_URL, ('trailing pe',), fallback_col=3, label='PE')
    pb_averages = get_industry_averages(PB_URL, ('pbv', 'price/book'), fallback_col=2, label='PB')
    print(f"Loaded {len(pe_averages)} PE averages and {len(pb_averages)} PB averages")

    # Get information for each stock; one bad ticker must not kill the run
    results = []
    failed_stocks = []
    for stock in STOCKS:
        try:
            stock_price, pe_ratio, pb_ratio, dividend_yield, mean_rec, median_rec, financial_iv, industry = get_stock_data(stock)
        except Exception as e:
            print(f"⚠ Failed to fetch {stock}: {e}")
            failed_stocks.append(f"{stock} ({e})")
            continue
        industry = INDUSTRY_MAP.get(industry, industry)
        pe_average = get_pe_average(industry, pe_averages)
        pb_average = get_pb_average(industry, pb_averages)
        results.append([stock, industry, stock_price, pe_ratio, pb_ratio, dividend_yield, pe_average, pb_average, mean_rec, median_rec, financial_iv])

    print(f"Collected data for {len(results)} stocks ({len(failed_stocks)} failed)")
    df = pd.DataFrame(results, columns=['Stock', 'Industry', 'Price', 'PE Ratio', 'PB Ratio', 'Dividend Yield', 'Industry PE', 'Industry PB', 'Target Mean Price', 'Target Median Price', 'Financial Intrinsic Value'])

    blocks = []
    for index, row in df.iterrows():
        message = f"Stock: {row['Stock']}\n"
        message += f"Industry: {row['Industry']}\n"
        message += f"Price: ${fmt(row['Price'])}\n"
        message += f"PE Ratio: {fmt(row['PE Ratio'])} (Industry Avg: {fmt(row['Industry PE'])})\n"
        message += f"PB Ratio: {fmt(row['PB Ratio'])} (Industry Avg: {fmt(row['Industry PB'])})\n"
        message += f"Dividend Yield: {fmt(row['Dividend Yield'])}%\n"
        message += f"Target Mean Price: ${fmt(row['Target Mean Price'])}\n"
        message += f"Target Median Price: ${fmt(row['Target Median Price'])}\n"
        message += f"Financial Intrinsic Value: ${fmt(row['Financial Intrinsic Value'])}\n"
        message += f"Recommendation: {recommend(row['PE Ratio'], row['PB Ratio'], row['Industry PE'], row['Industry PB'])}\n"
        print(message)
        blocks.append(message)

    send_in_batches(blocks)

    if failed_stocks:
        send_telegram_message("⚠️ Data fetch failed for: " + ", ".join(failed_stocks))


# ---------------------------------------------------------------------------
# McClellan Oscillator
# ---------------------------------------------------------------------------

def fetch_mcclellan_oscillator(days=60):
    """Fetch the McClellan Oscillator series, or None if unavailable.

    Never fabricates data: a missing, stale, or implausible feed returns
    None so callers announce the outage instead of alerting on noise.
    """
    url = "https://www.mcoscillator.com/data/osc_data/OSC-DATA.xls"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        # Load the XLS - the data usually starts around row 6
        df_mcc = pd.read_excel(response.content, engine='xlrd', skiprows=6)

        # Column 0 is Date, Column 9 is McClellan Oscillator
        df_mcc = df_mcc.iloc[:, [0, 9]]
        df_mcc.columns = ['Date', 'McClellan_Oscillator']
        df_mcc['Date'] = pd.to_datetime(df_mcc['Date'])
        df_mcc = df_mcc.dropna().set_index('Date')
        series = df_mcc['McClellan_Oscillator'].tail(days)
    except Exception as e:
        print(f"⚠ McClellan fetch error: {e}")
        return None

    if series.empty:
        print("⚠ McClellan data empty after parsing")
        return None
    if series.index[-1] < pd.Timestamp.today() - pd.Timedelta(days=10):
        print(f"⚠ McClellan data is stale (last point {series.index[-1]:%Y-%m-%d})")
        return None
    if series.abs().max() > 500:
        print("⚠ McClellan values out of plausible range - column layout may have changed")
        return None
    return series


def send_telegram_with_chart(message, series):
    if not bot_token or not CHAT_ID:
        print("⚠ Telegram credentials missing.")
        return

    chart_path = "temp_chart.png"
    try:
        plt.figure(figsize=(10, 5))
        plt.style.use('dark_background')

        series.plot(color='#00d1ff', linewidth=2, label='McClellan Oscillator')

        # Add overbought/oversold levels
        plt.axhline(100, color='red', linestyle='--', alpha=0.5)
        plt.axhline(-100, color='green', linestyle='--', alpha=0.5)
        plt.axhline(0, color='white', linewidth=0.8)

        plt.title(f"McClellan Oscillator Trend (Last {len(series)} Days)")
        plt.grid(alpha=0.1)

        plt.savefig(chart_path, bbox_inches='tight')
        plt.close()

        send_telegram_photo(message, chart_path)
    finally:
        plt.close()
        if os.path.exists(chart_path):
            os.remove(chart_path)


def detect_breadth_thrust(series, low=-70.0, high=70.0, window=10):
    """Zweig-style breadth thrust: oversold (< low) within the prior
    `window` sessions and overbought (> high) now."""
    if series is None or len(series) < 2:
        return False
    prior = series.iloc[-(window + 1):-1]
    return prior.min() < low and series.iloc[-1] > high


def run_mcclellan():
    """Fetch the McClellan Oscillator, detect breadth thrusts, send the report."""
    # 1. Fetch data (ensure at least 14 days for context)
    mcclellan_recent = fetch_mcclellan_oscillator(days=14)

    if mcclellan_recent is None or len(mcclellan_recent) < 2:
        send_telegram_message(
            "⚠️ McClellan Oscillator data unavailable today (mcoscillator.com fetch failed). "
            "Skipping breadth analysis."
        )
        return

    # 2. Extract values for the alert logic
    current_val = mcclellan_recent.iloc[-1]
    prior_val = mcclellan_recent.iloc[-2]
    recent_date = mcclellan_recent.index[-1].strftime('%Y-%m-%d')

    # 3. Detect an "Oversold to Overbought" thrust within the last 10 sessions
    thrust_alert = ""
    if detect_breadth_thrust(mcclellan_recent):
        min_recent = mcclellan_recent.iloc[-11:-1].min()
        thrust_alert = "\n\n🚀 <b>BREADTH THRUST ALERT</b>\n"
        thrust_alert += f"Extreme reversal within the last 10 sessions: {min_recent:+.1f} → {current_val:+.1f}\n"
        thrust_alert += "This rapid shift from oversold to overbought suggests a powerful surge in market participation."

    # 4. Build the final Telegram message
    msg = f"<b>📊 MCCLELLAN RECENT TREND</b>\n"
    msg += f"Date: {recent_date}\n\n"

    msg += "<b>Last 5 Sessions:</b>\n"
    for date, val in mcclellan_recent.tail(5).items():
        msg += f"• {date.strftime('%m-%d')}: {val:+.1f}\n"

    msg += thrust_alert

    msg += f"\n\n<b>Current Status:</b>\n"
    msg += f"• Oscillator: {current_val:+.1f}\n"
    msg += f"• Prior Day: {prior_val:+.1f}\n"
    msg += f"• 14D Change: {current_val - mcclellan_recent.iloc[0]:+.1f}"

    # Use the longer historical series for the chart
    historical_mcclellan = fetch_mcclellan_oscillator(days=90)
    if historical_mcclellan is not None:
        send_telegram_with_chart(msg, historical_mcclellan)
    else:
        # Chart data unavailable but the trend summary is - send it as text
        send_telegram_message(msg, parse_mode='HTML')


# ---------------------------------------------------------------------------
# VIX analysis
# ---------------------------------------------------------------------------

def get_vix_data():
    vix = Ticker('^VIX')
    vix_summary = vix.summary_detail.get('^VIX', {})

    # Prefer the live quote; fall back to the previous close
    vix_current = first_valid(
        vix_summary.get('regularMarketPrice'),
        vix_summary.get('regularMarketPreviousClose'),
    )
    vix_day_high = first_valid(vix_summary.get('regularMarketDayHigh'))
    vix_day_low = first_valid(vix_summary.get('regularMarketDayLow'))

    history = vix.history(period="1wk")

    if isinstance(history, pd.DataFrame) and not history.empty:
        history = history.reset_index()
        history['date'] = pd.to_datetime(history['date'])

        week_high = history['high'].max()
        week_low = history['low'].min()
        week_open = first_valid(history['open'].iloc[0] if 'open' in history else None,
                                history['close'].iloc[0])
        week_change_pct = ((vix_current - week_open) / week_open * 100) if is_num(week_open) and week_open != 0 and is_num(vix_current) else np.nan

        # Prior close: skip the last row only when it is today's (live) session
        last_is_today = history['date'].iloc[-1].date() == pd.Timestamp.now(tz='US/Eastern').date()
        if last_is_today and len(history) > 1:
            prior_close = history['close'].iloc[-2]
        else:
            prior_close = history['close'].iloc[-1]
    else:
        history = None
        week_high = week_low = week_open = week_change_pct = prior_close = np.nan

    return {
        'current': vix_current,
        'prior': prior_close,
        'day_high': vix_day_high,
        'day_low': vix_day_low,
        'week_high': week_high,
        'week_low': week_low,
        'week_change_pct': week_change_pct,
        'history': history
    }


def analyze_vix(vix_data):
    current = vix_data['current']
    prior = vix_data['prior']

    if not is_num(current):
        status = "⚪ DATA UNAVAILABLE"
        alert_type = None
    elif current >= VIX_THRESHOLD:
        status = "🔴 HIGH FEAR"
        alert_type = "extreme"
    elif current >= VIX_NEAR_THRESHOLD:
        status = "🟡 NEAR THRESHOLD"
        alert_type = "warning"
    else:
        status = "🟢 NORMAL"
        alert_type = None

    if is_num(current) and is_num(prior):
        trend = "📈 RISING" if current > prior else "📉 FALLING" if current < prior else "➡️ FLAT"
    else:
        trend = "N/A"

    message = f"<b>📊 VIX ANALYSIS (1 Week)</b>\n\n"
    message += f"<b>Current:</b> {fmt(current)}\n"
    message += f"<b>Prior:</b> {fmt(prior)}\n"
    message += f"<b>Day Range:</b> {fmt(vix_data['day_low'])} - {fmt(vix_data['day_high'])}\n"
    message += f"<b>Week Range:</b> {fmt(vix_data['week_low'])} - {fmt(vix_data['week_high'])}\n"
    message += f"<b>Week Change:</b> {fmt(vix_data['week_change_pct'], '+.2f')}%\n\n"
    message += f"<b>Status:</b> {status}\n"
    message += f"<b>Trend:</b> {trend}\n"

    if alert_type == "extreme":
        message += f"\n⚠️ <b>ALERT:</b> VIX has exceeded {VIX_THRESHOLD}! High market fear/volatility expected."
    elif alert_type == "warning":
        message += f"\n⚠️ <b>WARNING:</b> VIX is nearing {VIX_THRESHOLD}. Monitor closely."

    return message, alert_type


def send_vix_telegram_chart(message, vix_data):
    if not bot_token or not CHAT_ID:
        print("⚠ Telegram credentials missing.")
        return

    history_df = vix_data['history']
    chart_path = "vix_chart.png"
    try:
        plt.figure(figsize=(10, 5))
        plt.style.use('dark_background')

        if isinstance(history_df, pd.DataFrame) and not history_df.empty:
            history_df['date'] = pd.to_datetime(history_df['date'])
            plt.plot(history_df['date'], history_df['close'], color='#00d1ff', linewidth=2, label='VIX')
            plt.axhline(VIX_THRESHOLD, color='red', linestyle='--', linewidth=2, alpha=0.8, label=f'Threshold ({VIX_THRESHOLD})')
            plt.axhline(VIX_NEAR_THRESHOLD, color='orange', linestyle=':', linewidth=1.5, alpha=0.6, label=f'Near Threshold ({VIX_NEAR_THRESHOLD})')
            plt.fill_between(history_df['date'], history_df['close'], VIX_THRESHOLD,
                            where=history_df['close'] >= VIX_THRESHOLD, color='red', alpha=0.3)
        else:
            plt.text(0.5, 0.5, 'No historical data available', ha='center', va='center')

        plt.title(f"VIX - 1 Week Trend (Current: {fmt(vix_data['current'])})")
        plt.xlabel('Date')
        plt.ylabel('VIX')
        plt.legend(loc='upper right')
        plt.grid(alpha=0.1)
        plt.xticks(rotation=45)
        plt.tight_layout()

        plt.savefig(chart_path, bbox_inches='tight')
        plt.close()

        send_telegram_photo(message, chart_path)
    finally:
        plt.close()
        if os.path.exists(chart_path):
            os.remove(chart_path)


def run_vix():
    """Fetch VIX data, send the analysis chart, and return the data
    for the crash-protection section."""
    vix_data = get_vix_data()
    print(f"Current VIX: {vix_data['current']}")
    print(f"Week High: {vix_data['week_high']}, Week Low: {vix_data['week_low']}")
    print(f"Week Change: {fmt(vix_data['week_change_pct'])}%")

    vix_message, alert_type = analyze_vix(vix_data)
    print(vix_message)
    send_vix_telegram_chart(vix_message, vix_data)
    return vix_data


# ---------------------------------------------------------------------------
# Crash Protection Strategy - Daily Market Stress Check
# ---------------------------------------------------------------------------

def smooth_recent(history, column='close', window=3):
    """Mean of the last `window` closes, or NaN when no history exists."""
    if isinstance(history, pd.DataFrame) and not history.empty and column in history:
        closes = history[column].dropna()
        if not closes.empty:
            return float(closes.tail(window).mean())
    return np.nan


def compute_crash_signal(vix_data):
    """Compute crash_protection signals from VIX + VIX3M.

    Two-signal system (both legs 3-day smoothed for consistency):
      1. VIX level > 25
      2. VIX3M/VIX ratio < 0.9 (term structure approaching backwardation)

    When BOTH fire → STRESS (reduce to 30% position).
    When VIX > 40 → CRASH (exit all positions).
    Missing data degrades to an explicit UNKNOWN / level-only status
    instead of silently reading as "all clear".
    """
    # Fetch VIX3M data and smooth it the same way as VIX
    vix3m_ticker = Ticker('^VIX3M')
    vix3m_summary = vix3m_ticker.summary_detail.get('^VIX3M', {})
    vix3m_history = vix3m_ticker.history(period="5d")
    if isinstance(vix3m_history, pd.DataFrame):
        vix3m_history = vix3m_history.reset_index()
    vix3m_smooth = first_valid(
        smooth_recent(vix3m_history),
        vix3m_summary.get('regularMarketPrice'),
        vix3m_summary.get('regularMarketPreviousClose'),
    )

    # 3-day smoothed VIX (falls back to the current quote)
    vix_smooth = first_valid(smooth_recent(vix_data.get('history')), vix_data.get('current'))

    # Signal 1: VIX level stress (VIX > 25)
    level_stress = is_num(vix_smooth) and vix_smooth > VIX_STRESS_LEVEL

    # Signal 2: term structure stress; None when either leg is missing
    if is_num(vix_smooth) and vix_smooth > 0 and is_num(vix3m_smooth):
        ratio = vix3m_smooth / vix_smooth
        term_stress = ratio < TERM_STRESS_RATIO
    else:
        ratio = None
        term_stress = None

    # Combined stress: both signals must fire
    stress = level_stress and term_stress is True
    vix_extreme = is_num(vix_smooth) and vix_smooth > VIX_CRASH_LEVEL

    signals = {
        'vix_smoothed': vix_smooth,
        'vix3m': vix3m_smooth,
        'vix3m_vix_ratio': ratio,
        'level_stress': level_stress,
        'term_stress': term_stress,
        'combined_stress': stress,
        'vix_extreme': vix_extreme,
    }

    if not is_num(vix_smooth):
        return 'UNKNOWN', signals
    if vix_extreme:
        return 'CRASH', signals
    if stress:
        return 'STRESS', signals
    if level_stress:
        return 'WARNING', signals
    return 'NORMAL', signals


def build_crash_message(status, signals):
    """Build formatted Telegram message for crash protection alert."""
    status_labels = {
        'CRASH': '🔴🚨 CRASH MODE — EXIT ALL POSITIONS',
        'STRESS': '🟠 MARKET STRESS — REDUCE TO 30%',
        'WARNING': '🟡 VIX ELEVATED - Monitor',
        'NORMAL': '🟢 NORMAL - Stay invested',
        'UNKNOWN': '⚪ DATA UNAVAILABLE — could not evaluate',
    }

    msg = f"🛡️ CRASH PROTECTION\n\n"
    msg += f"Status: {status_labels.get(status, status)}\n\n"
    msg += "Key Metrics:\n"
    msg += f"• VIX (3d avg): {fmt(signals['vix_smoothed'])}\n"
    msg += f"• VIX3M (3d avg): {fmt(signals['vix3m'])}\n"
    msg += f"• VIX3M/VIX: {fmt(signals['vix3m_vix_ratio'], '.3f')}\n\n"
    msg += "Signals:\n"
    msg += f"• VIX > {VIX_STRESS_LEVEL}: {'✅ YES' if signals['level_stress'] else '❌ no'}\n"
    if signals['term_stress'] is None:
        msg += f"• Ratio < {TERM_STRESS_RATIO}: ⚪ N/A (term-structure data unavailable)\n"
    else:
        msg += f"• Ratio < {TERM_STRESS_RATIO}: {'✅ YES' if signals['term_stress'] else '❌ no'}\n"
    msg += f"• Combined: {'✅ ACTIVE' if signals['combined_stress'] else '❌ none'}\n\n"

    if status == 'CRASH':
        msg += f"🚨 ACTION: EXIT ALL SPY POSITIONS. VIX > {VIX_CRASH_LEVEL}."
    elif status == 'STRESS':
        msg += "⚠️ ACTION: Reduce SPY exposure to 30%. Both VIX level and term structure signal stress."
    elif status == 'WARNING':
        if signals['term_stress'] is None:
            msg += "📋 Monitor: VIX elevated; term-structure data unavailable — using VIX level only."
        else:
            msg += "📋 Monitor: VIX elevated but no backwardation. No action needed yet."
    elif status == 'UNKNOWN':
        msg += "⚠️ Could not fetch VIX data — no crash signal computed today."
    else:
        msg += "✅ All clear. Stay fully invested."

    return msg


def run_crash_protection(vix_data):
    status, signals = compute_crash_signal(vix_data)
    crash_msg = build_crash_message(status, signals)
    print(crash_msg)
    send_telegram_message(crash_msg)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

EMPTY_VIX_DATA = {
    'current': np.nan, 'prior': np.nan, 'day_high': np.nan, 'day_low': np.nan,
    'week_high': np.nan, 'week_low': np.nan, 'week_change_pct': np.nan,
    'history': None,
}


def main():
    missing = [name for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
               if not os.environ.get(name)]
    if missing:
        print(f"✗ Missing environment variables: {', '.join(missing)}. "
              "Set them as GitHub Actions repository secrets.", file=sys.stderr)
        return 2

    failed_sections = []

    def run_section(name, fn, *args):
        print(f"\n===== {name} =====")
        try:
            return fn(*args)
        except Exception:
            traceback.print_exc()
            failed_sections.append(name)
            return None

    run_section('Stock recommendations', run_stock_recommendations)
    run_section('McClellan Oscillator', run_mcclellan)
    vix_data = run_section('VIX analysis', run_vix)
    # Crash protection still runs (and reports UNKNOWN) if the VIX section failed
    run_section('Crash protection', run_crash_protection,
                vix_data if vix_data is not None else EMPTY_VIX_DATA)

    if failed_sections:
        print(f"\n✗ Sections failed: {', '.join(failed_sections)}", file=sys.stderr)
        return 1
    print("\n✓ All sections completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
