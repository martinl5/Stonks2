# Automated Stock Recommendation Bot

## 📈 Project Overview
The **Automated Stock Recommendation Bot** is a comprehensive platform that provides daily financial insights and actionable stock recommendations. Combining real-time financial data, calculated **intrinsic values**, and comparison with industry benchmarks, the bot offers clear guidance on whether to **buy**, **hold**, or **sell** specific stocks. The platform integrates a **Streamlit app** for interactive analysis and a **Telegram bot** for real-time notifications.

---

## 🚀 Features
- **Interactive Streamlit App**:
  - Displays stock data with color-coded recommendations.
  - Supports dynamic visualization of stock performance and technical indicators.
  - Allows users to explore detailed metrics by selecting stocks from a dropdown menu.
- **Telegram Bot Integration**:
  - Delivers financial summaries and recommendations directly to users.
- **Web Scraping**:
  - Dynamically gathers industry-specific benchmarks for P/E and P/B ratios using BeautifulSoup.
- **Yahoo Finance API**:
  - Fetches real-time stock data, including price, P/E ratio, P/B ratio, dividend yield, and industry classifications.
- **Technical Indicators**:
  - Includes moving averages like SMA and EMA for advanced stock trend analysis.
- **Recommendation Logic**:
  - Categorizes stocks as **Buy**, **Hold**, or **Sell** based on a comparison with industry benchmarks.
- **Data Cleaning and Validation**:
  - Leverages Regex for data standardization and pipelines for ensuring accuracy.
- **Scalability**:
  - Modular architecture supports additional financial metrics and multi-user capabilities.

---

## 📚 How It Works

### 1. **Streamlit App**
The Streamlit app provides an interactive dashboard where users can:
- View a table of stocks with metrics such as price, P/E ratio, P/B ratio, and dividend yield.
- Select a stock to view detailed metrics, performance trends, and technical indicators.
- Recommendations (Buy/Sell) are color-coded for ease of interpretation:
  - **Green**: Buy
  - **Red**: Sell
  - **Default**: Hold (no highlight).

### 2. **Telegram Bot**
- Sends a summary of stock data to users via Telegram.
- Includes recommendations, intrinsic values, and industry benchmarks.

### 3. **Data Workflow**
- **Stock Data Retrieval**:
  - Fetches real-time data from Yahoo Finance API.
  - Includes metrics like stock price, P/E ratio, P/B ratio, and industry classification.
- **Industry Benchmarking**:
  - Scrapes data for industry averages of P/E and P/B ratios.
- **Recommendation Logic** (thresholds configurable in `config.yaml`):
  - **Buy**: P/E and P/B ratios are both below 85% of the industry averages.
  - **Sell**: P/E and P/B ratios are both above 115% of the industry averages.
  - **Hold**: Metrics are near industry averages (or flagged as
    `Hold (benchmark unavailable)` when no industry benchmark could be loaded).
- **Intrinsic Value**:
  - Estimated with the Benjamin Graham formula `EPS × (8.5 + 2g)`, where `g`
    is the expected earnings growth in percent (clamped to 0–25%).

### 4. **Kaggle Daily Job** (`pe-pb-ratiotrigger.ipynb`)
A self-contained notebook scheduled to run daily on Kaggle. Each run sends to Telegram:
- Per-stock Buy/Hold/Sell recommendations (batched into a few messages).
- A McClellan Oscillator trend chart with Zweig-style breadth-thrust detection
  (oversold below −70 within the last 10 sessions, now above +70).
- A VIX analysis with thresholds at 28 (warning) and 30 (high fear).
- A crash-protection status from 3-day-smoothed VIX and the VIX3M/VIX term
  structure (STRESS when VIX > 25 and VIX3M/VIX < 0.9; CRASH when VIX > 40).

If a data source is unavailable, the notebook sends an explicit
"data unavailable" notice instead of guessing.

---

## ⚙️ Configuration
- **Streamlit App**:
  - Install dependencies: `pip install -r requirements.txt`
  - Run the app: `streamlit run app.py`
- **Telegram Bot**:
  - On Kaggle: store the credentials as Kaggle user secrets named
    `TELEGRAM_TOKEN` and `chat_id` (Add-ons → Secrets in the notebook editor).
  - Locally: see `.env.example` — never commit tokens or chat IDs to the repo.
- **Yahoo Finance API**:
  - Ensure internet access for fetching real-time data.
- **Web Scraping**:
  - Industry benchmarks are dynamically scraped from publicly available sources.

---

## 🛠️ Technologies Used
- **Streamlit**: For creating the interactive app.
- **Plotly**: For dynamic stock data visualization.
- **Python**: Core programming language.
- **BeautifulSoup**: Web scraping for industry-specific benchmarks.
- **Yahoo Finance API**: Real-time stock data.
- **Telegram API**: For notifications.
- **ta (Technical Analysis Library)**: To calculate SMA and EMA indicators.

---

## 📄 Example Outputs

### Streamlit App Dashboard
**Main Page**: Displays an overview of stocks with color-coded recommendations.
- ![Example Dashboard](streamlit_dashboard.png)

**Detailed Stock View**: Interactive visualization of stock metrics and performance trends.
- ![Detailed View](detailed_view.png)

### Telegram Bot Message
```
📊 Stock Analysis Report
Stock: AAPL
Industry: Consumer Electronics
Price: $150.00
PE Ratio: 20.50 (Industry Avg: 18.00)
PB Ratio: 5.50 (Industry Avg: 6.00)
Dividend Yield: 2.00%
Intrinsic Value: $170.00
Recommendation: Buy
```

---

## 📄 License
This project is licensed under the [MIT License](LICENSE).

---

## 👨‍💻 Author
**Martin Lim**  
For inquiries or collaboration, email: martin.lim511@gmail.com  

