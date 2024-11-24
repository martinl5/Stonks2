---

# Automated Stock Recommendation Bot

## 📈 Project Overview
This project is an **Automated Stock Recommendation Bot** designed to assist investors by providing daily financial insights and recommendations. The bot sends key financial metrics, such as **P/E ratios**, **P/B ratios**, and **dividend yields**, via Telegram, along with calculated **intrinsic values** for listed stocks. It compares these metrics against industry benchmarks to recommend whether to **buy**, **hold**, or **sell** specific stocks.

---

## 🚀 Features
- **Telegram Bot Integration**: Sends financial metrics and recommendations directly to users for quick decision-making.
- **Web Scraping**: Gathers industry-specific **P/E** and **P/B averages** using Python's BeautifulSoup library.
- **Yahoo Finance API**: Fetches real-time stock data, including price, financial ratios, and industry details.
- **Financial Modeling**: Implements intrinsic value calculations based on financial metrics and growth assumptions.
- **Data Cleaning and Validation**: Leverages Regex for data standardization and pipelines for ensuring accuracy.
- **Scalability**: Designed with a modular architecture to support additional metrics and multi-user functionality.

---

## 📚 How It Works
1. **Stock Data Retrieval**:
   - Fetches real-time stock data using the Yahoo Finance API.
   - Includes metrics like **stock price**, **P/E ratio**, **P/B ratio**, **dividend yield**, and industry type.

2. **Industry Benchmarking**:
   - Scrapes industry-specific P/E and P/B averages from publicly available data sources.
   - Compares stock-specific metrics against these benchmarks.

3. **Recommendation Logic**:
   - Determines whether a stock is a **Buy**, **Hold**, or **Sell** based on its financial performance relative to industry averages.

4. **Telegram Notifications**:
   - Sends formatted financial summaries and recommendations to users via a Telegram bot.

---

## 📦 Installation

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/martinl5/Stonks2.git
   cd Stonks2
   ```

2. **Install Dependencies**:
   Ensure you have Python 3.8+ installed. Then, run:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set Up Your Telegram Bot**:
   - Create a Telegram bot and obtain its API token.
   - Replace `YOUR_BOT_TOKEN` and `YOUR_CHAT_ID` in the `bot.py` script with your Telegram bot token and chat ID.

4. **Run the Bot**:
   ```bash
   python bot.py
   ```

---

## ⚙️ Configuration
- **Yahoo Finance API**: Ensure that you have internet access for API calls to fetch stock data.
- **Industry Benchmark Source**: The bot uses publicly available data for industry averages, scraped dynamically via BeautifulSoup.
- **Threshold Customization**: Modify the recommendation logic in `bot.py` to adjust buy/hold/sell criteria.

---

## 🛠️ Technologies Used
- **Python**: Core programming language for all functionalities.
- **BeautifulSoup**: Web scraping for industry-specific benchmarks.
- **Yahoo Finance API**: Real-time stock data retrieval.
- **Telegram API**: Sending messages and notifications.
- **Regex**: Cleaning and standardizing financial data.

---

## 📄 Example Output
### Telegram Bot Message
```
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

## 📊 Future Enhancements
- Add support for multi-user functionality with unique preferences.
- Integrate additional financial metrics, such as EV/EBITDA or PEG ratio.
- Provide visualization of stock performance trends and benchmarks.
- Schedule automated daily updates to run on a cloud server.

---

## 🤝 Contributing
Contributions are welcome! Please follow these steps:
1. Fork the repository.
2. Create a new branch for your feature (`git checkout -b feature-name`).
3. Commit your changes (`git commit -m 'Add feature'`).
4. Push to your branch (`git push origin feature-name`).
5. Open a pull request.

---

## 📄 License
This project is licensed under the [MIT License](LICENSE).

---

## 👨‍💻 Author
**Martin**  
Feel free to connect at martin.lim511@gmail.com

