from __future__ import annotations

import calendar
import os
import re
import sqlite3
from datetime import date, datetime
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "finance.db"
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")

CATEGORIES = ["Food", "Transport", "Shopping", "Bills", "Entertainment", "Health", "Education", "Other"]
CATEGORY_KEYWORDS = {
    "Food": ["food", "dinner", "lunch", "breakfast", "swiggy", "zomato", "restaurant", "grocery", "groceries", "cafe"],
    "Transport": ["uber", "ola", "taxi", "bus", "metro", "train", "fuel", "petrol", "parking", "ride"],
    "Shopping": ["amazon", "flipkart", "clothes", "shopping", "market", "shoes", "electronics"],
    "Bills": ["rent", "electricity", "water", "internet", "phone", "mobile", "bill", "insurance"],
    "Entertainment": ["movie", "netflix", "spotify", "concert", "game", "gaming", "theatre"],
    "Health": ["doctor", "medicine", "pharmacy", "hospital", "health", "gym"],
    "Education": ["course", "book", "tuition", "school", "college", "education"],
}


def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                transaction_date TEXT NOT NULL,
                description TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                transaction_type TEXT NOT NULL CHECK(transaction_type IN ('income', 'expense')),
                category TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                budget_month TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Overall',
                limit_amount REAL NOT NULL CHECK(limit_amount > 0),
                UNIQUE(user_id, budget_month, category),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "Authentication required"}), 401
        return view(*args, **kwargs)

    return wrapped


def predict_category(description):
    text = description.lower()
    scores = {category: sum(bool(re.search(r"\b" + re.escape(word) + r"\b", text)) for word in words) for category, words in CATEGORY_KEYWORDS.items()}
    category, score = max(scores.items(), key=lambda item: item[1])
    if score == 0:
        return "Other", 0.35
    return category, min(0.96, 0.62 + score * 0.12)


def current_month():
    return request.args.get("month") or date.today().strftime("%Y-%m")


def month_range(month):
    year, month_number = map(int, month.split("-"))
    last_day = calendar.monthrange(year, month_number)[1]
    return f"{month}-01", f"{month}-{last_day:02d}"


def transaction_payload(row):
    return {key: row[key] for key in row.keys()}


@app.route("/")
def index():
    return render_template("index.html", categories=CATEGORIES)


@app.post("/api/register")
def register():
    data = request.get_json() or {}
    name, email, password = data.get("name", "").strip(), data.get("email", "").strip().lower(), data.get("password", "")
    if not name or not email or len(password) < 6:
        return jsonify({"error": "Name, email, and a password of at least 6 characters are required."}), 400
    try:
        with get_db() as db:
            cursor = db.execute("INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)", (name, email, generate_password_hash(password), datetime.utcnow().isoformat()))
            session["user_id"] = cursor.lastrowid
            session["user_name"] = name
    except sqlite3.IntegrityError:
        return jsonify({"error": "An account with that email already exists."}), 409
    return jsonify({"name": name})


@app.post("/api/login")
def login():
    data = request.get_json() or {}
    email, password = data.get("email", "").strip().lower(), data.get("password", "")
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password."}), 401
    session["user_id"], session["user_name"] = user["id"], user["name"]
    return jsonify({"name": user["name"]})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/session")
def session_info():
    return jsonify({"authenticated": "user_id" in session, "name": session.get("user_name")})


@app.post("/api/predict-category")
def predict():
    description = (request.get_json() or {}).get("description", "").strip()
    if not description:
        return jsonify({"error": "Description is required."}), 400
    category, confidence = predict_category(description)
    return jsonify({"category": category, "confidence": confidence})


@app.route("/api/transactions", methods=["GET", "POST"])
@login_required
def transactions():
    if request.method == "GET":
        month = current_month()
        start, end = month_range(month)
        with get_db() as db:
            rows = db.execute("SELECT * FROM transactions WHERE user_id = ? AND transaction_date BETWEEN ? AND ? ORDER BY transaction_date DESC, id DESC", (session["user_id"], start, end)).fetchall()
        return jsonify({"transactions": [transaction_payload(row) for row in rows]})

    data = request.get_json() or {}
    description = data.get("description", "").strip()
    transaction_type = data.get("transaction_type", "expense")
    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0
    if not description or amount <= 0 or transaction_type not in {"income", "expense"} or not data.get("transaction_date"):
        return jsonify({"error": "Enter a valid date, description, positive amount, and transaction type."}), 400
    category = data.get("category") or (predict_category(description)[0] if transaction_type == "expense" else "Income")
    confidence = predict_category(description)[1] if transaction_type == "expense" else 1
    with get_db() as db:
        cursor = db.execute("INSERT INTO transactions (user_id, transaction_date, description, amount, transaction_type, category, confidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (session["user_id"], data["transaction_date"], description, amount, transaction_type, category, confidence, datetime.utcnow().isoformat()))
    return jsonify({"id": cursor.lastrowid, "category": category, "confidence": confidence}), 201


@app.delete("/api/transactions/<int:transaction_id>")
@login_required
def delete_transaction(transaction_id):
    with get_db() as db:
        db.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?", (transaction_id, session["user_id"]))
    return jsonify({"ok": True})


@app.route("/api/budgets", methods=["GET", "POST"])
@login_required
def budgets():
    month = current_month()
    if request.method == "GET":
        with get_db() as db:
            rows = db.execute("SELECT * FROM budgets WHERE user_id = ? AND budget_month = ? ORDER BY category", (session["user_id"], month)).fetchall()
        return jsonify({"budgets": [transaction_payload(row) for row in rows]})
    data = request.get_json() or {}
    category, limit = data.get("category", "Overall"), float(data.get("limit_amount", 0) or 0)
    if limit <= 0:
        return jsonify({"error": "Budget limit must be greater than zero."}), 400
    with get_db() as db:
        db.execute("INSERT INTO budgets (user_id, budget_month, category, limit_amount) VALUES (?, ?, ?, ?) ON CONFLICT(user_id, budget_month, category) DO UPDATE SET limit_amount = excluded.limit_amount", (session["user_id"], month, category, limit))
    return jsonify({"ok": True}), 201


@app.get("/api/dashboard")
@login_required
def dashboard():
    month = current_month()
    start, end = month_range(month)
    with get_db() as db:
        rows = db.execute("SELECT * FROM transactions WHERE user_id = ? AND transaction_date BETWEEN ? AND ? ORDER BY transaction_date DESC, id DESC", (session["user_id"], start, end)).fetchall()
        budgets_rows = db.execute("SELECT * FROM budgets WHERE user_id = ? AND budget_month = ?", (session["user_id"], month)).fetchall()
    transactions_data = [transaction_payload(row) for row in rows]
    income = sum(row["amount"] for row in rows if row["transaction_type"] == "income")
    expenses = sum(row["amount"] for row in rows if row["transaction_type"] == "expense")
    by_category = {category: round(sum(row["amount"] for row in rows if row["category"] == category and row["transaction_type"] == "expense"), 2) for category in CATEGORIES}
    overall_budget = next((row["limit_amount"] for row in budgets_rows if row["category"] == "Overall"), 0)
    recent_expenses = [row["amount"] for row in rows if row["transaction_type"] == "expense"]
    forecast = round(sum(recent_expenses) / len(recent_expenses) * 1.05, 2) if recent_expenses else 0
    top_category = max(by_category, key=by_category.get) if expenses else None
    insights = []
    if top_category and by_category[top_category] > 0:
        insights.append(f"{top_category} is your highest spending category this month at ${by_category[top_category]:,.2f}.")
    if overall_budget and expenses >= overall_budget:
        insights.append("You have reached or exceeded your overall monthly budget. Review non-essential spending.")
    elif overall_budget and expenses >= overall_budget * 0.8:
        insights.append("You are close to your monthly budget limit. A small adjustment now can keep you on track.")
    if not insights:
        insights.append("Add a few transactions to unlock more personalized spending insights.")
    return jsonify({"month": month, "income": round(income, 2), "expenses": round(expenses, 2), "balance": round(income - expenses, 2), "by_category": by_category, "transactions": transactions_data, "budgets": [transaction_payload(row) for row in budgets_rows], "forecast": forecast, "insights": insights})


init_db()

if __name__ == "__main__":
    app.run(debug=True)
