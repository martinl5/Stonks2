import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import ta
import re
from bs4 import BeautifulSoup
import requests


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
    if data.index.tzinfo is None:
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
    
    # Retrieve stock data with fallback to NaN
    stock_price = stock_info.get('regularMarketPreviousClose', np.nan)  # Default to NaN if missing
    
    # Check for 'trailingPE', then 'forwardPE', and fallback to NaN
    pe_ratio = stock_info.get('trailingPE') if stock_info.get('trailingPE') is not None else stock_info.get('forwardPE', np.nan)
    
    pb_ratio = stock_info.get('priceToBook', np.nan)  # Default to NaN if missing
    
    # Handle dividend yield (convert to percentage if available)
    dividend_yield = stock_info.get('dividendYield', 0)  # Default to 0 if missing
    if dividend_yield is not None:
        dividend_yield *= 100
    
    # Default industry to 'Unknown' if missing
    industry = stock_info.get('industry', 'Unknown')
    
    #Get the mean recommendation of the stock
    mean_recommendation = stock_info.get('targetMeanPrice', np.nan)
    #Get the median recommendation of the stock
    median_recommendation = stock_info.get('targetMedianPrice', np.nan)
    # calculate financial intrinsic value of the stock using the financials Intrinsic value = Earnings per share (EPS) x (1 + r) x P/E ratio
    # where r is the expected growth rate of the company
    # calculate the growth rate of the company
    growth_rate = stock_info.get('earningsGrowth', np.nan)
    # calculate the earnings per share
    eps = stock_info.get('trailingEps', np.nan)
    # calculate the financial intrinsic value, if growth rate and eps is not available, set intrinsic value to NaN
    if growth_rate is not None and eps is not None:
        financial_intrinsic_value = eps * (1 + growth_rate) * pe_ratio
    else:
        financial_intrinsic_value = np.nan
    
    
    return stock_price, pe_ratio, pb_ratio, dividend_yield, mean_recommendation, median_recommendation, financial_intrinsic_value, industry



url = 'http://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/pedata.html'

def get_pe_averages():
    # Disable SSL verification
    response = requests.get(url, verify=False)
    soup = BeautifulSoup(response.content, 'html.parser')
    table = soup.find_all('table')[0]  # Find the first table
    rows = table.find_all('tr')
    pe_averages = {}
    for row in rows[1:]:  # Skip the header row
        items = row.find_all('td')
        industry = items[0].text.strip()
        pe = items[3].text.strip()
        pe_averages[industry] = pe
    return pe_averages

def get_pe_average(industry, pe_averages):
    return pe_averages.get(industry, np.nan)

# Get the PE averages
pe_averages = get_pe_averages()

#get the pb ratios of the industries
url = 'https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/pbvdata.html'
def get_pb_averages():
    # Disable SSL verification
    response = requests.get(url, verify=False)
    soup = BeautifulSoup(response.content, 'html.parser')
    table = soup.find_all('table')[0]  # Find the first table
    rows = table.find_all('tr')
    pb_averages = {}
    for row in rows[1:]:  # Skip the header row
        items = row.find_all('td')
        industry = items[0].text.strip()
        pb = items[2].text.strip()
        pb_averages[industry] = pb
    return pb_averages

def get_pb_average(industry, pb_averages):
    return pb_averages.get(industry, np.nan)

#try to get the pb ratio of the industry
pb_averages = get_pb_averages()

# Clean the keys in pe_averages using regex
pe_averages = {re.sub(r'\s+', ' ', re.sub(r'\n\t\t', '', industry)).strip(): pe for industry, pe in pe_averages.items()}

pb_averages = {re.sub(r'\s+', ' ', re.sub(r'\n\t\t', '', industry)).strip(): pb for industry, pb in pb_averages.items()}

# List of stocks to analyze
stocks = ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'HSY', 'KO', 'PEP', 'NKE', 'V', 'INTC', 'NVDA', 'AMD', 'IBM', 'ORCL', 'ASML']

# Get information for each stock
results = []
for stock in stocks:
    stock_price, pe_ratio, pb_ratio, dividend_yield, mean_rec, median_rec, financial_iv, industry = get_stock_data(stock)
    if industry == 'Semiconductors' or industry == 'Semiconductor Equipment & Materials':
        industry = 'Semiconductor'
    #map Software-Infrastructure to Software (System & Application)
    if industry == 'Software - Infrastructure' or industry == 'Information Technology Services':
        industry = 'Software (System & Application)'
    #map Consumer Electronics to Software (Entertainment)
    if industry == 'Consumer Electronics':
        industry = 'Software (Entertainment)'
    #map Internet Content & Information to Software (Internet)
    if industry == 'Internet Content & Information' or industry == 'Internet Retail':
        industry = 'Software (Internet)'
    #map Confectioners to Food Processing
    if industry == 'Confectioners':
        industry = 'Food Processing'
    #map Beverages - Non-Alcoholic to Beverages (Soft)
    if industry == 'Beverages - Non-Alcoholic':
        industry = 'Beverage (Soft)'
    #map Credit Services to Financial Svcs. (Non-bank & Insurance)	
    if industry == 'Credit Services':
        industry = 'Financial Svcs. (Non-bank & Insurance)'
    #map Footwear & Accessories to Apparel
    if industry == 'Footwear & Accessories':
        industry = 'Apparel'
    pe_average = get_pe_average(industry, pe_averages)
    pb_average = get_pb_average(industry, pb_averages)
    results.append([stock, industry, stock_price, pe_ratio, pb_ratio, dividend_yield, pe_average, pb_average, mean_rec, median_rec, financial_iv])


# Create a DataFrame from the results
columns = ['Stock', 'Industry', 'Price', 'PE Ratio', 'PB Ratio', 'Dividend Yield', 'Industry PE', 'Industry PB', 'Target Mean Price', 'Target Median Price', 'Financial Intrinsic Value']
overview_df = pd.DataFrame(results, columns=columns)

# Apply Recommendation Logic to DataFrame
def label_recommendations(row):
    if row['PE Ratio'] < float(row['Industry PE']) and row['PB Ratio'] < float(row['Industry PB']):
        return 'Buy'
    elif row['PE Ratio'] > float(row['Industry PE']) and row['PB Ratio'] > float(row['Industry PB']):
        return 'Sell'
    else:
        return 'Hold'

overview_df['Recommendation'] = overview_df.apply(label_recommendations, axis=1)

# Add color coding
def highlight_rows(row):
    if row['Recommendation'] == 'Buy':
        return ['background-color: rgba(0, 255, 0, 0.2)'] * len(row)  # Soft green
    elif row['Recommendation'] == 'Sell':
        return ['background-color: rgba(255, 0, 0, 0.2)'] * len(row)  # Soft red
    else:
        return [''] * len(row)  # No background color for "Hold"# No background color for "Hold"


# PART 4: Streamlit app logic
st.set_page_config(layout="wide")
# Check if selected_stock exists in session state
if "selected_stock" not in st.session_state:
    st.session_state.selected_stock = None

# Display the main dashboard or navigate based on selected stock
if st.session_state.selected_stock is None:
    # Main Dashboard
    st.title("Stock Overview Dashboard")

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

