# AI Finance Assistant

A beginner-friendly personal finance tracker built from the SRS with Flask, SQLite, and a lightweight explainable expense categorizer.

## Features

- Register, log in, and log out
- Add, edit, and delete income and expense transactions
- Keyword-based category prediction with confidence and explanation
- Monthly dashboard with balance, spending breakdown, trends, and budget progress
- Monthly budgets with category limits
- Educational financial insights and a simple next-month estimate

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000.

The SQLite database is created automatically at `finance.db`. This is an educational project and does not provide professional financial advice.
