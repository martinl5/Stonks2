# CLAUDE.md

This file provides guidance for Claude Code when working with the Stonks2 project.

## Project Overview

### Description
Stonks2 is a stock market analysis and visualization application built with Streamlit. It provides interactive dashboards for tracking stock prices, analyzing financial data, and displaying real-time market information. The application includes a main dashboard interface (app.py) and a daily alerting job (daily_job.py) that runs on GitHub Actions (.github/workflows/daily-job.yml, 08:00 SGT daily) and sends Telegram notifications.

### Tech Stack
- Python (app.py, daily_job.py)
- Streamlit (dashboard)
- GitHub Actions (daily job scheduling)
- Git (version control)

### Important Notes
- `daily_job.py` reads its stock symbols and recommendation multipliers from
  `config.yaml` (with hardcoded fallbacks). `app.py` still hardcodes the same
  symbol list — keep the two in sync.
- The daily job's Telegram credentials come from the `TELEGRAM_BOT_TOKEN` and
  `TELEGRAM_CHAT_ID` environment variables (GitHub Actions repository secrets).
- Its dependencies live in `requirements-job.txt` (slim, installed by the
  workflow); keep it updated when daily_job.py gains imports.

## Development Workflow

### Running the Application
```bash
# Install dependencies
pip install -r requirements.txt

# Run Streamlit app
streamlit run app.py
```

### Testing
```bash
# Unit tests for the daily job's pure logic
python -m pytest tests/ -q

# Syntax checks
python -m py_compile app.py daily_job.py
```

## Important Conventions

### Commit Messages
Use the format: `[CLAUDE-xxx] "message-description: timestamp_sgt"`
- CLAUDE-xxx: Ticket/issue identifier (replace xxx with actual number)
- message-description: Brief description of changes
- timestamp_sgt: Singapore time (e.g., 14:30_SGT)

Example: `[CLAUDE-001] "Add stock price chart: 14:30_SGT"`

### Code Style
(Pending: Define style guide)

## Environment Configuration

### Required Files
- `.env` (if applicable)
- Configuration files

### Dependencies
See requirements.txt

---

*This file was created to provide context for Claude Code operations in this project.*