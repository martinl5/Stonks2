# CLAUDE.md

This file provides guidance for Claude Code when working with the Stonks2 project.

## Project Overview

### Description
Stonks2 is a stock market analysis and visualization application built with Streamlit. It provides interactive dashboards for tracking stock prices, analyzing financial data, and displaying real-time market information. The application includes a main dashboard interface (app.py) and a daily alerting job (pe-pb-ratiotrigger.ipynb) that runs on Kaggle and sends Telegram notifications.

### Tech Stack
- Python (app.py, pe-pb-ratiotrigger.ipynb)
- Streamlit (dashboard)
- Jupyter Notebook (Kaggle daily job)
- Git (version control)

### Important Constraint
`pe-pb-ratiotrigger.ipynb` must stay **self-contained**: Kaggle runs only the
uploaded .ipynb, so it cannot import from other repo files or read
config.yaml. Constants duplicated from config.yaml (e.g. the 0.85/1.15
recommendation multipliers) must be kept in sync manually.

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
# Unit tests for the notebook's pure logic (loads functions from the .ipynb with stubs)
python -m pytest tests/ -q

# Syntax checks
python -m py_compile app.py
python -c "import json; json.load(open('pe-pb-ratiotrigger.ipynb'))"
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