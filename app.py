import math
import re
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
import ta
import yaml
import yfinance as yf
from bs4 import BeautifulSoup


# PART 0: Configuration and shared helpers
DEFAULT_RECOMMENDATION = {
    'buy_pe_multiplier': 0.85,
    'buy_pb_multiplier': 0.85,
    'sell_pe_multiplier': 1.15,
    'sell_pb_multiplier': 1.15,
}


def load_recommendation_config():
    try:
        with open('config.yaml') as f:
            cfg = yaml.safe_load(f) or {}
        rec = cfg.get('recommendation') or {}
    except (OSError, yaml.YAMLError):
        rec = {}
    return {**DEFAULT_RECOMMENDATION, **{k: v for k, v in rec.items() if k in DEFAULT_RECOMMENDATION}}


REC_CFG = load_recommendation_config()


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


# PART 1: Functions for pulling, processing, and creating technical indicators
def fetch_stock_data(ticker, period, interval):
    end_date = datetime.now()
    if period == '1wk':
        start_date = end_date - timedelta(days=7)
        data = yf.download(ticker, start=start_date, end=end_date, interval=interval)
    else:
        data = yf.download(ticker, period=period, interval=interval)
    return data


def process_data(data):
    # Newer yfinance versions return MultiIndex columns (field, ticker)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    if data.index.tz is None:
        data.index = data.index.tz_localize('UTC')
    data.index = data.index.tz_convert('US/Eastern')
    data.reset_index(inplace=True)
    data.rename(columns={'Date': 'Datetime'}, inplace=True)
    return data


def calculate_metrics(data):
    last_close = data['Close'].iloc[-1]
    prev_close = data['Close'].iloc[0]
    change = last_close - prev_close
    pct_change = (change / prev_close) * 100
    high = data['High'].max()
    low = data['Low'].min()
    volume = data['Volume'].sum()
    return last_close, change, pct_change, high, low, volume


def add_technical_indicators(data):
    data['SMA_20'] = ta.trend.sma_indicator(data['Close'], window=20)
    data['EMA_20'] = ta.trend.ema_indicator(data['Close'], window=20)
    return data


def get_stock_data(stock):
    stock_data = yf.Ticker(stock)
    stock_info = stock_data.info

    # Prefer the live quote; fall back to the previous close
    stock_price = first_valid(
        stock_info.get('regularMarketPrice'),
        stock_info.get('currentPrice'),
        stock_info.get('regularMarketPreviousClose'),
    )

    # Check for 'trailingPE', then 'forwardPE', and fallback to NaN
    pe_ratio = first_valid(stock_info.get('trailingPE'), stock_info.get('forwardPE'))

    pb_ratio = first_valid(stock_info.get('priceToBook'))

    dividend_yield = normalize_dividend_yield(stock_info.get('dividendYield'))

    # Default industry to 'Unknown' if missing
    industry = stock_info.get('industry', 'Unknown')

    # Mean and median analyst target prices
    mean_recommendation = first_valid(stock_info.get('targetMeanPrice'))
    median_recommendation = first_valid(stock_info.get('targetMedianPrice'))

    # Graham intrinsic value from EPS and expected earnings growth
    growth_rate = stock_info.get('earningsGrowth')
    eps = stock_info.get('trailingEps')
    financial_intrinsic_value = estimate_intrinsic_value(eps, growth_rate)

    return stock_price, pe_ratio, pb_ratio, dividend_yield, mean_recommendation, median_recommendation, financial_intrinsic_value, industry


# PART 2: Industry-average PE and PB benchmarks (Damodaran / NYU Stern)
PE_URL = 'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/pedata.html'
PB_URL = 'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/pbvdata.html'


def http_get(url, timeout=20, retries=3, backoff=2):
    """GET with retries; only falls back to verify=False on SSL errors."""
    import time as _time
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
        _time.sleep(backoff ** attempt)
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


@st.cache_data(ttl=7 * 24 * 3600)  # config.yaml: cache industry benchmarks for 7 days
def get_industry_averages(url, header_keywords, fallback_col):
    try:
        return parse_industry_table(http_get(url).content, header_keywords, fallback_col)
    except Exception as e:
        st.warning(f"Industry benchmark fetch failed for {url}: {e}")
        return {}


def get_pe_average(industry, pe_averages):
    return pe_averages.get(industry, np.nan)


def get_pb_average(industry, pb_averages):
    return pb_averages.get(industry, np.nan)


# PART 3: Overview table with recommendations
# List of stocks to analyze
stocks = ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'HSY', 'KO', 'PEP', 'NKE', 'V', 'INTC', 'NVDA', 'AMD', 'IBM', 'ORCL', 'ASML']

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


def recommend(pe, pb, pe_avg, pb_avg):
    """Buy/Sell require a margin vs the industry average (see config.yaml)."""
    if not all(is_num(v) for v in (pe, pb, pe_avg, pb_avg)):
        return 'Hold (benchmark unavailable)'
    if pe < pe_avg * REC_CFG['buy_pe_multiplier'] and pb < pb_avg * REC_CFG['buy_pb_multiplier']:
        return 'Buy'
    if pe > pe_avg * REC_CFG['sell_pe_multiplier'] and pb > pb_avg * REC_CFG['sell_pb_multiplier']:
        return 'Sell'
    return 'Hold'


@st.cache_data(ttl=15 * 60)  # config.yaml: update_interval_minutes
def build_overview():
    # Column 3 has historically been Trailing PE (matching the stocks'
    # trailingPE), column 2 on the PBV page the industry price/book ratio.
    pe_averages = get_industry_averages(PE_URL, ('trailing pe',), 3)
    pb_averages = get_industry_averages(PB_URL, ('pbv', 'price/book'), 2)

    results = []
    for stock in stocks:
        try:
            stock_price, pe_ratio, pb_ratio, dividend_yield, mean_rec, median_rec, financial_iv, industry = get_stock_data(stock)
        except Exception as e:
            st.warning(f"Failed to fetch {stock}: {e}")
            continue
        industry = INDUSTRY_MAP.get(industry, industry)
        pe_average = get_pe_average(industry, pe_averages)
        pb_average = get_pb_average(industry, pb_averages)
        results.append([stock, industry, stock_price, pe_ratio, pb_ratio, dividend_yield, pe_average, pb_average, mean_rec, median_rec, financial_iv])

    columns = ['Stock', 'Industry', 'Price', 'PE Ratio', 'PB Ratio', 'Dividend Yield', 'Industry PE', 'Industry PB', 'Target Mean Price', 'Target Median Price', 'Financial Intrinsic Value']
    overview_df = pd.DataFrame(results, columns=columns)
    overview_df['Recommendation'] = overview_df.apply(
        lambda row: recommend(row['PE Ratio'], row['PB Ratio'], row['Industry PE'], row['Industry PB']), axis=1
    )
    return overview_df


# Add color coding
def highlight_rows(row):
    if row['Recommendation'] == 'Buy':
        return ['background-color: rgba(0, 255, 0, 0.2)'] * len(row)  # Soft green
    elif row['Recommendation'] == 'Sell':
        return ['background-color: rgba(255, 0, 0, 0.2)'] * len(row)  # Soft red
    else:
        return [''] * len(row)  # No background color for "Hold"


# PART 4: Streamlit app logic
st.set_page_config(layout="wide")
# Check if selected_stock exists in session state
if "selected_stock" not in st.session_state:
    st.session_state.selected_stock = None

# Display the main dashboard or navigate based on selected stock
if st.session_state.selected_stock is None:
    # Main Dashboard
    st.title("Stock Overview Dashboard")

    overview_df = build_overview()

    # Dropdown to select a stock
    selected_stock = st.selectbox("Select a stock for detailed analysis:", overview_df["Stock"].unique())

    # Update the session state when a stock is selected
    st.session_state.selected_stock = selected_stock

    # Display the overview dataframe with recommendations
    st.dataframe(
        overview_df.style.apply(highlight_rows, axis=1)
    )
else:
    # Detailed Stock Analysis
    selected_stock = st.session_state.selected_stock
    st.sidebar.header(f"Details for {selected_stock}")
    if st.sidebar.button("Go Back"):
        st.session_state.selected_stock = None

    st.title(f"Stock Details for {selected_stock}")

    # Sidebar for parameters
    time_period = st.sidebar.selectbox("Time Period", ['1d', '1wk', '1mo', '1y', 'max'])
    chart_type = st.sidebar.selectbox("Chart Type", ['Candlestick', 'Line'])
    indicators = st.sidebar.multiselect("Technical Indicators", ['SMA 20', 'EMA 20'])

    interval_mapping = {
        '1d': '1m',
        '1wk': '30m',
        '1mo': '1d',
        '1y': '1wk',
        'max': '1wk'
    }

    # Fetch and process stock data
    data = fetch_stock_data(selected_stock, time_period, interval_mapping[time_period])
    data = process_data(data)
    data = add_technical_indicators(data)

    # Calculate metrics
    last_close, change, pct_change, high, low, volume = calculate_metrics(data)

    # Display main metrics
    st.metric(label=f"{selected_stock} Last Price", value=f"${last_close:.2f}", delta=f"{change:.2f} ({pct_change:.2f}%)")
    col1, col2, col3 = st.columns(3)
    col1.metric("High", f"${high:.2f}")
    col2.metric("Low", f"${low:.2f}")
    col3.metric("Volume", f"{volume:,} Shares")

    # Plot the stock price chart
    fig = go.Figure()
    if chart_type == 'Candlestick':
        fig.add_trace(go.Candlestick(x=data['Datetime'],
                                     open=data['Open'],
                                     high=data['High'],
                                     low=data['Low'],
                                     close=data['Close']))
    else:
        fig = px.line(data, x='Datetime', y='Close')

    # Add selected technical indicators to the chart
    for indicator in indicators:
        if indicator == 'SMA 20':
            fig.add_trace(go.Scatter(x=data['Datetime'], y=data['SMA_20'], name='SMA 20'))
        elif indicator == 'EMA 20':
            fig.add_trace(go.Scatter(x=data['Datetime'], y=data['EMA_20'], name='EMA 20'))

    # Format graph
    fig.update_layout(title=f'{selected_stock} {time_period.upper()} Chart',
                      xaxis_title='Time',
                      yaxis_title='Price (USD)',
                      height=600)
    st.plotly_chart(fig, use_container_width=True)

    # Display historical data and technical indicators
    st.subheader("Historical Data")
    st.dataframe(data[['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume']])
