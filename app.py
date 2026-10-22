import os
import io
import csv
import sqlite3
import secrets
from datetime import date, datetime
from functools import wraps

from flask import Flask, request, redirect, url_for, session, flash, render_template_string, send_file, abort
from werkzeug.security import generate_password_hash, check_password_hash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_RENDER = bool(os.environ.get("RENDER"))
SQLITE_PATH = os.environ.get("SQLITE_PATH", os.path.join(APP_DIR, "khosal_transactions.db"))
SECRET_KEY = os.environ.get("KHOSAL_SECRET_KEY", "")
DEFAULT_RATE = 64.20

if IS_RENDER and not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required on Render. Configure your Neon PostgreSQL connection string.")
if IS_RENDER and not SECRET_KEY:
    raise RuntimeError("KHOSAL_SECRET_KEY is required on Render. Set a long random secret in Environment.")

app = Flask(__name__)
app.secret_key = SECRET_KEY or "local-development-only-change-this"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_RENDER,
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)

def pg_enabled():
    return bool(DATABASE_URL)

def connect():
    if pg_enabled():
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
        except ImportError as exc:
            raise RuntimeError("psycopg2-binary is required for Neon PostgreSQL.") from exc
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return psycopg2.connect(url, sslmode="require", cursor_factory=RealDictCursor)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def sql_for_db(sql):
    if pg_enabled():
        return sql.replace("?", "%s")
    return sql

def execute(sql, params=()):
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(sql_for_db(sql), params)
        conn.commit()
        return cur
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def query_all(sql, params=()):
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(sql_for_db(sql), params)
        return cur.fetchall()
    finally:
        conn.close()

def query_one(sql, params=()):
    rows = query_all(sql, params)
    return rows[0] if rows else None

def db_now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def init_db():
    if pg_enabled():
        statements = [
            """CREATE TABLE IF NOT EXISTS companies (
                id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, base_currency TEXT NOT NULL DEFAULT 'AFN',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'accountant', company_id INTEGER, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY, company_id INTEGER, txn_date DATE NOT NULL, txn_type TEXT NOT NULL,
                description TEXT NOT NULL, amount NUMERIC(16,2) NOT NULL, currency TEXT NOT NULL DEFAULT 'AFN',
                exchange_rate NUMERIC(16,4) NOT NULL DEFAULT 64.20, amount_usd NUMERIC(16,2) NOT NULL DEFAULT 0,
                category TEXT, party TEXT, bill_status TEXT, bill_number TEXT, payment_method TEXT,
                reference TEXT, notes TEXT, created_by INTEGER, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS accounts (
                id SERIAL PRIMARY KEY, company_id INTEGER, code TEXT NOT NULL, name TEXT NOT NULL,
                account_type TEXT NOT NULL, normal_balance TEXT NOT NULL DEFAULT 'debit',
                is_active INTEGER NOT NULL DEFAULT 1, UNIQUE(company_id, code))""",
            """CREATE TABLE IF NOT EXISTS journal_entries (
                id SERIAL PRIMARY KEY, company_id INTEGER, entry_date DATE NOT NULL, description TEXT NOT NULL,
                reference TEXT, status TEXT NOT NULL DEFAULT 'posted', created_by INTEGER,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS journal_lines (
                id SERIAL PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
                account_id INTEGER NOT NULL REFERENCES accounts(id), description TEXT,
                debit NUMERIC(16,2) NOT NULL DEFAULT 0, credit NUMERIC(16,2) NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'AFN', exchange_rate NUMERIC(16,4) NOT NULL DEFAULT 1,
                amount_afn NUMERIC(16,2) NOT NULL DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY, user_id INTEGER, action TEXT NOT NULL, detail TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
        ]
    else:
        statements = [
            """CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, base_currency TEXT NOT NULL DEFAULT 'AFN',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'accountant', company_id INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, txn_date TEXT NOT NULL, txn_type TEXT NOT NULL,
                description TEXT NOT NULL, amount NUMERIC NOT NULL, currency TEXT NOT NULL DEFAULT 'AFN',
                exchange_rate NUMERIC NOT NULL DEFAULT 64.20, amount_usd NUMERIC NOT NULL DEFAULT 0,
                category TEXT, party TEXT, bill_status TEXT, bill_number TEXT, payment_method TEXT,
                reference TEXT, notes TEXT, created_by INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, code TEXT NOT NULL, name TEXT NOT NULL,
                account_type TEXT NOT NULL, normal_balance TEXT NOT NULL DEFAULT 'debit',
                is_active INTEGER NOT NULL DEFAULT 1, UNIQUE(company_id, code))""",
            """CREATE TABLE IF NOT EXISTS journal_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, entry_date TEXT NOT NULL, description TEXT NOT NULL,
                reference TEXT, status TEXT NOT NULL DEFAULT 'posted', created_by INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
            """CREATE TABLE IF NOT EXISTS journal_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT, entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
                account_id INTEGER NOT NULL REFERENCES accounts(id), description TEXT,
                debit NUMERIC NOT NULL DEFAULT 0, credit NUMERIC NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'AFN', exchange_rate NUMERIC NOT NULL DEFAULT 1,
                amount_afn NUMERIC NOT NULL DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT NOT NULL, detail TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
        ]
    for statement in statements:
        execute(statement)
    # Idempotent starter data: does not delete or overwrite existing records.
    execute("INSERT INTO companies (name, base_currency) VALUES (?, ?) ON CONFLICT (name) DO NOTHING", ("Khosal Khan Tower", "AFN"))
    company = query_one("SELECT id FROM companies WHERE name = ?", ("Khosal Khan Tower",))
    company_id = company["id"]
    execute("UPDATE users SET company_id = ? WHERE company_id IS NULL", (company_id,))
    execute("UPDATE transactions SET company_id = ? WHERE company_id IS NULL", (company_id,))
    execute("UPDATE accounts SET company_id = ? WHERE company_id IS NULL", (company_id,))
    execute("UPDATE journal_entries SET company_id = ? WHERE company_id IS NULL", (company_id,))
    # Default accounts are inserted only when their codes do not already exist.
    defaults = [
        ("1000", "Cash on Hand", "Asset", "debit"),
        ("1010", "Bank", "Asset", "debit"),
        ("1100", "Accounts Receivable", "Asset", "debit"),
        ("2000", "Accounts Payable", "Liability", "credit"),
        ("3000", "Owner's Equity", "Equity", "credit"),
        ("4000", "Revenue", "Income", "credit"),
        ("5000", "Operating Expenses", "Expense", "debit"),
        ("5100", "Rent Expense", "Expense", "debit"),
    ]
    for code, name, typ, normal in defaults:
        if not query_one("SELECT id FROM accounts WHERE company_id = ? AND code = ?", (company_id, code)):
            execute("INSERT INTO accounts (company_id, code, name, account_type, normal_balance) VALUES (?, ?, ?, ?, ?)",
                    (company_id, code, name, typ, normal))

def audit(action, detail=""):
    uid = session.get("user_id")
    execute("INSERT INTO audit_log (user_id, action, detail) VALUES (?, ?, ?)", (uid, action, str(detail)[:500]))

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)
    return wrapped

def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapped

def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(24)
    return session["_csrf"]

@app.before_request
def csrf_protect():
    if request.method == "POST":
        sent = request.form.get("_csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
            abort(400, "Invalid or missing form security token. Refresh the page and try again.")

@app.context_processor
def inject_globals():
    return {"csrf_token": csrf_token, "today": date.today().isoformat(), "company_name": "Khosal Khan Tower"}

STYLE = """
:root{--navy:#142b4a;--blue:#2864dc;--bg:#f3f6fb;--text:#1e293b;--muted:#64748b;--line:#e2e8f0;--green:#12805c;--red:#c2413b}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 Inter,system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--text)}
a{color:var(--blue);text-decoration:none}.layout{display:flex;min-height:100vh}.side{width:245px;background:var(--navy);color:white;padding:22px 15px;flex-shrink:0}
.brand{font-size:19px;font-weight:800;padding:8px 10px 24px;line-height:1.25}.brand small{display:block;font-size:11px;color:#b9c7dc;font-weight:500;margin-top:7px;letter-spacing:.08em}
.nav a{display:block;color:#d5dfed;padding:11px 12px;border-radius:9px;margin:4px 0}.nav a:hover,.nav a.active{background:#284568;color:white}
.main{flex:1;min-width:0}.top{background:white;border-bottom:1px solid var(--line);padding:17px 28px;display:flex;align-items:center;justify-content:space-between;gap:12px}
.top strong{font-size:16px}.content{padding:26px;max-width:1500px;margin:auto}.titlebar{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:20px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:0 0 14px}.muted,.sub{color:var(--muted)}.sub{margin:0}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-bottom:22px}.card{background:white;border:1px solid var(--line);border-radius:14px;padding:19px;box-shadow:0 2px 6px #142b4a06;min-width:0}
.metric{font-size:27px;font-weight:800;margin-top:8px;overflow-wrap:anywhere}.metric-label{color:var(--muted);font-size:13px}.section-grid{display:grid;grid-template-columns:1.25fr 1fr;gap:18px}
.btn,button{display:inline-block;border:0;border-radius:8px;background:var(--blue);color:white;padding:10px 14px;font:inherit;font-weight:650;cursor:pointer}.btn.secondary{background:#e8eef8;color:#234267}.btn.danger{background:#b42318}.btn.small{padding:6px 9px;font-size:12px}
input,select,textarea{width:100%;padding:10px 11px;border:1px solid #ccd5e2;border-radius:8px;background:white;color:var(--text);font:inherit}
label{display:block;font-weight:650;font-size:13px;margin:0 0 6px}.form-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:15px}.field{min-width:0}.field.wide{grid-column:span 2}.field.full{grid-column:1/-1}
form .actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:18px}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}th,td{text-align:left;padding:12px 10px;border-bottom:1px solid var(--line)}th{color:var(--muted);font-weight:700;background:#f8fafc}tr:last-child td{border-bottom:0}
.flash{padding:12px 14px;border-radius:9px;background:#e5f5ed;color:#145c3c;margin-bottom:12px}.flash.error{background:#fff0ef;color:#982b25}
.filters{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-bottom:15px}.filters .field{min-width:130px;flex:1}.pill{display:inline-block;border-radius:30px;padding:3px 8px;background:#eaf0fa;color:#355177;font-size:12px}.pill.green{background:#e3f6ed;color:#13704e}.pill.red{background:#fff0ef;color:#b42318}
.auth{max-width:430px;margin:8vh auto;padding:24px}.auth .card{padding:28px}.auth h1{font-size:24px;margin-bottom:6px}
.mobile-menu{display:none}
@media(max-width:1000px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.section-grid{grid-template-columns:1fr}.side{width:210px}.form-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:700px){.layout{display:block}.side{width:100%;padding:12px}.brand{padding:5px 8px 10px}.nav{display:flex;gap:5px;overflow-x:auto;padding-bottom:4px}.nav a{white-space:nowrap;margin:0;padding:8px 10px;font-size:13px}.top{padding:13px 16px}.content{padding:16px}.grid{gap:10px}.card{padding:14px}.metric{font-size:22px}.form-grid{grid-template-columns:1fr}.field.wide{grid-column:span 1}h1{font-size:22px}.top .muted{display:none}}
"""

BASE = """
<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{{ title }} · Khosal Tower ERP</title><style>""" + STYLE + """</style></head><body>
<div class="layout"><aside class="side"><div class="brand">KHOSAL TOWER<small>ERP · FINANCE</small></div>
{% if session.get('user_id') %}<nav class="nav">
<a href="{{ url_for('dashboard') }}">Dashboard</a><a href="{{ url_for('transactions') }}">Transactions</a><a href="{{ url_for('new_transaction') }}">＋ New Transaction</a><a href="{{ url_for('accounts') }}">Chart of Accounts</a><a href="{{ url_for('journals') }}">Journal Entries</a><a href="{{ url_for('trial_balance') }}">Trial Balance</a><a href="{{ url_for('reports') }}">Reports & Export</a>{% if session.get('role')=='admin' %}<a href="{{ url_for('users') }}">User Management</a><a href="{{ url_for('audit_log') }}">Audit Log</a>{% endif %}<a href="{{ url_for('change_password') }}">Change Password</a><a href="{{ url_for('logout') }}">Log out</a></nav>{% endif %}</aside>
<div class="main"><header class="top"><strong>{{ company_name }}</strong><span class="muted">{% if session.get('username') %}{{ session.get('username') }} · {{ session.get('role')|title }}{% else %}Accounting & Operations{% endif %}</span></header>
<main class="content">{% with messages=get_flashed_messages(with_categories=true) %}{% for category,message in messages %}<div class="flash {{ 'error' if category=='error' else '' }}">{{ message }}</div>{% endfor %}{% endwith %}{{ body|safe }}</main></div></div></body></html>
"""

def page(title, body_template, **ctx):
    body = render_template_string(body_template, **ctx)
    return render_template_string(BASE, title=title, body=body)

def current_company_id():
    row = query_one("SELECT id FROM companies WHERE name = ?", ("Khosal Khan Tower",))
    return row["id"] if row else 1

@app.route("/")
def index():
    return redirect(url_for("dashboard") if session.get("user_id") else url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        row = query_one("SELECT * FROM users WHERE username = ?", (username,))
        if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
            session.clear()
            session["user_id"] = row["id"]
            session["username"] = row["username"]
            session["role"] = row["role"]
            session["company_id"] = row["company_id"] or current_company_id()
            csrf_token()
            audit("login", username)
            return redirect(url_for("dashboard"))
        flash("Incorrect username or password.", "error")
    return page("Login", """
    <div class="auth"><div class="card"><div class="brand" style="color:#142b4a;padding:0 0 18px">KHOSAL TOWER<small style="color:#64748b">ERP · FINANCE</small></div><h1>Welcome back</h1><p class="sub" style="margin-bottom:20px">Sign in to your accounting workspace.</p>
    <form method="post"><input type="hidden" name="_csrf" value="{{ csrf_token() }}"><div style="margin-bottom:14px"><label>Username</label><input name="username" required autocomplete="username"></div><div><label>Password</label><input type="password" name="password" required autocomplete="current-password"></div><div class="actions"><button style="width:100%">Sign in</button></div></form></div></div>""")

@app.route("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    cid = session.get("company_id") or current_company_id()
    month = date.today().strftime("%Y-%m")
    count = query_one("SELECT COUNT(*) AS n FROM transactions WHERE company_id = ?", (cid,))["n"]
    monthly = query_one("SELECT COALESCE(SUM(CASE WHEN txn_type='Receipt' THEN amount ELSE 0 END),0) AS receipts, COALESCE(SUM(CASE WHEN txn_type='Expense' THEN amount ELSE 0 END),0) AS expenses FROM transactions WHERE company_id = ? AND CAST(txn_date AS TEXT) LIKE ?", (cid, month + "%"))
    recent = query_all("SELECT id, txn_date, txn_type, description, amount, currency, party FROM transactions WHERE company_id = ? ORDER BY txn_date DESC, id DESC LIMIT 8", (cid,))
    breakdown = query_all("SELECT txn_type, COUNT(*) AS n FROM transactions WHERE company_id = ? GROUP BY txn_type ORDER BY n DESC", (cid,))
    return page("Dashboard", """
    <div class="titlebar"><div><h1>Dashboard</h1><p class="sub">Your finance overview at a glance.</p></div><a class="btn" href="{{ url_for('new_transaction') }}">＋ New Transaction</a></div>
    <div class="grid"><div class="card"><div class="metric-label">All transactions</div><div class="metric">{{ count }}</div><div class="muted">Recorded entries</div></div><div class="card"><div class="metric-label">Monthly receipts</div><div class="metric">{{ '{:,.2f}'.format(monthly['receipts'] or 0) }}</div><div class="muted">Current month · source currency amounts mixed</div></div><div class="card"><div class="metric-label">Monthly expenses</div><div class="metric">{{ '{:,.2f}'.format(monthly['expenses'] or 0) }}</div><div class="muted">Current month · source currency amounts mixed</div></div><div class="card"><div class="metric-label">Exchange rate</div><div class="metric">{{ default_rate }}</div><div class="muted">AFN per USD default</div></div></div>
    <div class="section-grid"><div class="card"><h2>Recent transactions</h2><div class="table-wrap"><table><thead><tr><th>Date</th><th>Type</th><th>Description</th><th>Amount</th></tr></thead><tbody>{% for t in recent %}<tr><td>{{ t['txn_date'] }}</td><td><span class="pill">{{ t['txn_type'] }}</span></td><td>{{ t['description'] }}</td><td>{{ '{:,.2f}'.format(t['amount']) }} {{ t['currency'] }}</td></tr>{% else %}<tr><td colspan="4" class="muted">No transactions yet.</td></tr>{% endfor %}</tbody></table></div></div>
    <div class="card"><h2>Transaction mix</h2>{% for b in breakdown %}<div style="display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #e2e8f0"><span>{{ b['txn_type'] }}</span><strong>{{ b['n'] }}</strong></div>{% else %}<p class="muted">Your transaction types will appear here.</p>{% endfor %}<p class="muted" style="font-size:12px;margin-top:14px">Receipt and expense totals above may include AFN and USD amounts together; they are activity indicators, not a reconciled cash balance.</p></div></div>
    """, count=count, monthly=monthly, recent=recent, breakdown=breakdown, default_rate=DEFAULT_RATE)

@app.route("/transactions")
@login_required
def transactions():
    cid = session.get("company_id") or current_company_id()
    search = request.args.get("q", "").strip()
    typ = request.args.get("type", "").strip()
    start = request.args.get("start", "").strip()
    end = request.args.get("end", "").strip()
    sql = "SELECT * FROM transactions WHERE company_id = ?"
    params = [cid]
    if search:
        sql += " AND (description LIKE ? OR party LIKE ? OR reference LIKE ? OR bill_number LIKE ?)"
        term = "%" + search + "%"
        params.extend([term, term, term, term])
    if typ:
        sql += " AND txn_type = ?"; params.append(typ)
    if start:
        sql += " AND txn_date >= ?"; params.append(start)
    if end:
        sql += " AND txn_date <= ?"; params.append(end)
    sql += " ORDER BY txn_date DESC, id DESC LIMIT 500"
    rows = query_all(sql, tuple(params))
    return page("Transactions", """
    <div class="titlebar"><div><h1>Transactions</h1><p class="sub">Search, filter and manage your transaction register.</p></div><a class="btn" href="{{ url_for('new_transaction') }}">＋ Add transaction</a></div>
    <div class="card"><form class="filters" method="get"><div class="field"><label>Search</label><input name="q" value="{{ search }}" placeholder="Description, party, reference"></div><div class="field"><label>Type</label><select name="type"><option value="">All types</option>{% for t in types %}<option {{ 'selected' if typ==t }}>{{ t }}</option>{% endfor %}</select></div><div class="field"><label>From</label><input type="date" name="start" value="{{ start }}"></div><div class="field"><label>To</label><input type="date" name="end" value="{{ end }}"></div><button>Filter</button><a class="btn secondary" href="{{ url_for('transactions') }}">Reset</a></form>
    <div class="table-wrap"><table><thead><tr><th>Date</th><th>Type</th><th>Description</th><th>Party</th><th>Amount</th><th>AFN/USD equivalent</th><th>Actions</th></tr></thead><tbody>{% for t in rows %}<tr><td>{{ t['txn_date'] }}</td><td><span class="pill">{{ t['txn_type'] }}</span></td><td>{{ t['description'] }}</td><td>{{ t['party'] or '—' }}</td><td>{{ '{:,.2f}'.format(t['amount']) }} {{ t['currency'] }}</td><td>{{ '{:,.2f}'.format(t['amount_usd'] or 0) }} USD</td><td><a class="btn small secondary" href="{{ url_for('edit_transaction', txn_id=t['id']) }}">Edit</a> {% if session.get('role')=='admin' %}<form method="post" action="{{ url_for('delete_transaction', txn_id=t['id']) }}" style="display:inline" onsubmit="return confirm('Delete this transaction permanently?')"><input type="hidden" name="_csrf" value="{{ csrf_token() }}"><button class="btn small danger">Delete</button></form>{% endif %}</td></tr>{% else %}<tr><td colspan="7" class="muted">No matching transactions.</td></tr>{% endfor %}</tbody></table></div><p class="muted" style="margin-top:12px">Showing up to 500 entries.</p></div>
    """, rows=rows, search=search, typ=typ, start=start, end=end, types=["Receipt","Expense","Transfer","Exchange","Adjustment"])

@app.route("/transactions/new", methods=["GET", "POST"])
@login_required
def new_transaction():
    return transaction_form(None)

@app.route("/transactions/<int:txn_id>/edit", methods=["GET", "POST"])
@login_required
def edit_transaction(txn_id):
    row = query_one("SELECT * FROM transactions WHERE id = ? AND company_id = ?", (txn_id, session.get("company_id") or current_company_id()))
    if not row: abort(404)
    return transaction_form(row)

def transaction_form(row):
    is_edit = row is not None
    if request.method == "POST":
        f = request.form
        try:
            txn_date = f.get("txn_date") or date.today().isoformat()
            txn_type = f.get("txn_type", "Expense")
            if txn_type not in ["Receipt","Expense","Transfer","Exchange","Adjustment"]:
                raise ValueError("Select a valid transaction type.")
            description = f.get("description","").strip()
            amount = float(f.get("amount","0"))
            currency = f.get("currency","AFN")
            rate = float(f.get("exchange_rate") or DEFAULT_RATE)
            if not description or amount <= 0 or currency not in ["AFN","USD"] or rate <= 0:
                raise ValueError("Enter a description, positive amount, valid currency and positive exchange rate.")
            amount_usd = amount / rate if currency == "AFN" else amount
            fields = (txn_date, txn_type, description, amount, currency, rate, amount_usd, f.get("category","").strip(), f.get("party","").strip(), f.get("bill_status",""), f.get("bill_number","").strip(), f.get("payment_method",""), f.get("reference","").strip(), f.get("notes","").strip())
            cid = session.get("company_id") or current_company_id()
            if is_edit:
                execute("""UPDATE transactions SET txn_date=?,txn_type=?,description=?,amount=?,currency=?,exchange_rate=?,amount_usd=?,category=?,party=?,bill_status=?,bill_number=?,payment_method=?,reference=?,notes=? WHERE id=? AND company_id=?""", fields + (row["id"], cid))
                audit("transaction_updated", row["id"])
                flash("Transaction updated.")
            else:
                execute("""INSERT INTO transactions (company_id,txn_date,txn_type,description,amount,currency,exchange_rate,amount_usd,category,party,bill_status,bill_number,payment_method,reference,notes,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (cid,) + fields + (session["user_id"],))
                audit("transaction_created", description)
                flash("Transaction saved.")
            return redirect(url_for("transactions"))
        except (ValueError, TypeError) as exc:
            flash(str(exc) or "Please check the amount and exchange rate.", "error")
    defaults = dict(row) if row else {"txn_date":date.today().isoformat(),"txn_type":"Expense","description":"","amount":"","currency":"AFN","exchange_rate":DEFAULT_RATE,"category":"","party":"","bill_status":"Pending","bill_number":"","payment_method":"Cash","reference":"","notes":""}
    return page("Edit Transaction" if is_edit else "New Transaction", """
    <div class="titlebar"><div><h1>{{ 'Edit transaction' if is_edit else 'New transaction' }}</h1><p class="sub">Record a financial transaction for {{ company_name }}.</p></div><a class="btn secondary" href="{{ url_for('transactions') }}">Back to transactions</a></div>
    <div class="card"><form method="post"><input type="hidden" name="_csrf" value="{{ csrf_token() }}"><div class="form-grid">
    <div class="field"><label>Date *</label><input type="date" name="txn_date" value="{{ v['txn_date'] }}" required></div>
    <div class="field"><label>Transaction type *</label><select name="txn_type">{% for t in types %}<option {{ 'selected' if v['txn_type']==t }}>{{ t }}</option>{% endfor %}</select></div>
    <div class="field"><label>Currency *</label><select name="currency"><option {{ 'selected' if v['currency']=='AFN' }}>AFN</option><option {{ 'selected' if v['currency']=='USD' }}>USD</option></select></div>
    <div class="field wide"><label>Description *</label><input name="description" value="{{ v['description'] }}" required maxlength="250"></div>
    <div class="field"><label>Amount *</label><input type="number" name="amount" min="0.01" step="0.01" value="{{ v['amount'] }}" required></div>
    <div class="field"><label>AFN per USD exchange rate</label><input type="number" name="exchange_rate" min="0.0001" step="0.0001" value="{{ v['exchange_rate'] or default_rate }}" required></div>
    <div class="field"><label>Category</label><input name="category" value="{{ v['category'] or '' }}"></div><div class="field"><label>Party / Supplier / Customer</label><input name="party" value="{{ v['party'] or '' }}"></div>
    <div class="field"><label>Bill status</label><select name="bill_status">{% for s in ['Not applicable','Pending','Paid','Partially paid','Received'] %}<option {{ 'selected' if v['bill_status']==s }}>{{ s }}</option>{% endfor %}</select></div>
    <div class="field"><label>Bill number</label><input name="bill_number" value="{{ v['bill_number'] or '' }}"></div><div class="field"><label>Payment method</label><select name="payment_method">{% for s in ['Cash','Bank transfer','Card','Cheque','Mobile money','Other'] %}<option {{ 'selected' if v['payment_method']==s }}>{{ s }}</option>{% endfor %}</select></div>
    <div class="field"><label>Voucher / Reference</label><input name="reference" value="{{ v['reference'] or '' }}"></div><div class="field full"><label>Notes</label><textarea name="notes" rows="3">{{ v['notes'] or '' }}</textarea></div></div><div class="actions"><button>Save transaction</button><a class="btn secondary" href="{{ url_for('transactions') }}">Cancel</a></div></form></div>
    """, is_edit=is_edit, v=defaults, types=["Receipt","Expense","Transfer","Exchange","Adjustment"], default_rate=DEFAULT_RATE)

@app.route("/transactions/<int:txn_id>/delete", methods=["POST"])
@admin_required
def delete_transaction(txn_id):
    execute("DELETE FROM transactions WHERE id = ? AND company_id = ?", (txn_id, session.get("company_id") or current_company_id()))
    audit("transaction_deleted", txn_id)
    flash("Transaction deleted.")
    return redirect(url_for("transactions"))

@app.route("/accounts", methods=["GET","POST"])
@login_required
def accounts():
    cid = session.get("company_id") or current_company_id()
    if request.method == "POST":
        code, name, typ = request.form.get("code","").strip(), request.form.get("name","").strip(), request.form.get("account_type","")
        normal = request.form.get("normal_balance","debit")
        if not code or not name or typ not in ["Asset","Liability","Equity","Income","Expense"] or normal not in ["debit","credit"]:
            flash("Please enter a valid account code, name, type and normal balance.", "error")
        else:
            try:
                execute("INSERT INTO accounts (company_id,code,name,account_type,normal_balance) VALUES (?,?,?,?,?)", (cid,code,name,typ,normal))
                audit("account_created", code + " " + name)
                flash("Account created.")
                return redirect(url_for("accounts"))
            except Exception:
                flash("That account code may already exist. Check the chart of accounts.", "error")
    rows = query_all("SELECT * FROM accounts WHERE company_id = ? ORDER BY code", (cid,))
    return page("Chart of Accounts", """
    <div class="titlebar"><div><h1>Chart of Accounts</h1><p class="sub">Account list used by manual journal entries.</p></div></div><div class="section-grid"><div class="card"><h2>Add account</h2><form method="post"><input type="hidden" name="_csrf" value="{{ csrf_token() }}"><div style="margin-bottom:12px"><label>Account code</label><input name="code" required></div><div style="margin-bottom:12px"><label>Account name</label><input name="name" required></div><div style="margin-bottom:12px"><label>Account type</label><select name="account_type">{% for t in ['Asset','Liability','Equity','Income','Expense'] %}<option>{{ t }}</option>{% endfor %}</select></div><div><label>Normal balance</label><select name="normal_balance"><option value="debit">Debit</option><option value="credit">Credit</option></select></div><div class="actions"><button>Add account</button></div></form></div><div class="card"><h2>Accounts ({{ rows|length }})</h2><div class="table-wrap"><table><thead><tr><th>Code</th><th>Name</th><th>Type</th><th>Normal</th></tr></thead><tbody>{% for a in rows %}<tr><td>{{ a['code'] }}</td><td>{{ a['name'] }}</td><td>{{ a['account_type'] }}</td><td>{{ a['normal_balance']|title }}</td></tr>{% endfor %}</tbody></table></div></div></div>
    """, rows=rows)

@app.route("/journals", methods=["GET","POST"])
@login_required
def journals():
    cid = session.get("company_id") or current_company_id()
    accts = query_all("SELECT id,code,name,account_type FROM accounts WHERE company_id = ? AND is_active=1 ORDER BY code", (cid,))
    if request.method == "POST":
        try:
            entry_date = request.form.get("entry_date") or date.today().isoformat()
            description = request.form.get("description","").strip()
            debit_id = int(request.form.get("debit_account",""))
            credit_id = int(request.form.get("credit_account",""))
            amount = float(request.form.get("amount","0"))
            if not description or debit_id == credit_id or amount <= 0:
                raise ValueError("Enter a description, choose two different accounts and use a positive amount.")
            valid = {int(a["id"]) for a in accts}
            if debit_id not in valid or credit_id not in valid:
                raise ValueError("Choose accounts from this company's chart of accounts.")
            conn = connect()
            try:
                cur = conn.cursor()
                cur.execute(sql_for_db("INSERT INTO journal_entries (company_id,entry_date,description,reference,status,created_by) VALUES (?,?,?,?,?,?)"), (cid,entry_date,description,request.form.get("reference","").strip(),"posted",session["user_id"]))
                entry_id = cur.lastrowid if not pg_enabled() else None
                if pg_enabled():
                    cur.execute("SELECT LASTVAL() AS id")
                    entry_id = cur.fetchone()["id"]
                for account_id, debit, credit in [(debit_id,amount,0),(credit_id,0,amount)]:
                    cur.execute(sql_for_db("INSERT INTO journal_lines (entry_id,account_id,description,debit,credit,currency,exchange_rate,amount_afn) VALUES (?,?,?,?,?,?,?,?)"), (entry_id,account_id,description,debit,credit,"AFN",1,amount))
                conn.commit()
                audit("journal_posted", f"Entry {entry_id}: {description}")
                flash("Balanced journal entry posted.")
                return redirect(url_for("journals"))
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except (ValueError, TypeError) as exc:
            flash(str(exc) or "Unable to post journal entry.", "error")
    entries = query_all("""SELECT e.id,e.entry_date,e.description,e.reference,COALESCE(SUM(l.debit),0) AS debit_total,COALESCE(SUM(l.credit),0) AS credit_total
        FROM journal_entries e LEFT JOIN journal_lines l ON l.entry_id=e.id WHERE e.company_id=? GROUP BY e.id,e.entry_date,e.description,e.reference ORDER BY e.entry_date DESC,e.id DESC LIMIT 100""", (cid,))
    return page("Journal Entries", """
    <div class="titlebar"><div><h1>Journal Entries</h1><p class="sub">Post balanced, manual double-entry journals in AFN.</p></div></div><div class="section-grid"><div class="card"><h2>New journal</h2><form method="post"><input type="hidden" name="_csrf" value="{{ csrf_token() }}"><div style="margin-bottom:12px"><label>Date</label><input type="date" name="entry_date" value="{{ today }}" required></div><div style="margin-bottom:12px"><label>Description</label><input name="description" required></div><div style="margin-bottom:12px"><label>Debit account</label><select name="debit_account" required>{% for a in accts %}<option value="{{ a['id'] }}">{{ a['code'] }} — {{ a['name'] }}</option>{% endfor %}</select></div><div style="margin-bottom:12px"><label>Credit account</label><select name="credit_account" required>{% for a in accts %}<option value="{{ a['id'] }}">{{ a['code'] }} — {{ a['name'] }}</option>{% endfor %}</select></div><div style="margin-bottom:12px"><label>Amount (AFN)</label><input type="number" name="amount" min="0.01" step="0.01" required></div><div><label>Reference</label><input name="reference"></div><div class="actions"><button>Post journal</button></div></form></div><div class="card"><h2>Recent journals</h2><div class="table-wrap"><table><thead><tr><th>Date</th><th>Description</th><th>Debit</th><th>Credit</th></tr></thead><tbody>{% for e in entries %}<tr><td>{{ e['entry_date'] }}</td><td>{{ e['description'] }}</td><td>{{ '{:,.2f}'.format(e['debit_total']) }}</td><td>{{ '{:,.2f}'.format(e['credit_total']) }}</td></tr>{% else %}<tr><td colspan="4" class="muted">No journal entries yet.</td></tr>{% endfor %}</tbody></table></div></div></div>
    """, accts=accts, entries=entries)

@app.route("/trial-balance")
@login_required
def trial_balance():
    cid = session.get("company_id") or current_company_id()
    rows = query_all("""SELECT a.code,a.name,a.account_type,COALESCE(SUM(l.debit),0) AS debit,COALESCE(SUM(l.credit),0) AS credit
      FROM accounts a LEFT JOIN journal_lines l ON l.account_id=a.id LEFT JOIN journal_entries e ON e.id=l.entry_id AND e.company_id=a.company_id
      WHERE a.company_id=? GROUP BY a.id,a.code,a.name,a.account_type ORDER BY a.code""", (cid,))
    total_debit = sum(float(r["debit"] or 0) for r in rows)
    total_credit = sum(float(r["credit"] or 0) for r in rows)
    return page("Trial Balance", """
    <div class="titlebar"><div><h1>Trial Balance</h1><p class="sub">Totals from manual journal lines only.</p></div><a class="btn secondary" href="{{ url_for('journals') }}">Journal entries</a></div><div class="card"><div class="table-wrap"><table><thead><tr><th>Code</th><th>Account</th><th>Type</th><th>Debit (AFN)</th><th>Credit (AFN)</th></tr></thead><tbody>{% for r in rows %}<tr><td>{{ r['code'] }}</td><td>{{ r['name'] }}</td><td>{{ r['account_type'] }}</td><td>{{ '{:,.2f}'.format(r['debit']) }}</td><td>{{ '{:,.2f}'.format(r['credit']) }}</td></tr>{% endfor %}<tr><th colspan="3">Total</th><th>{{ '{:,.2f}'.format(total_debit) }}</th><th>{{ '{:,.2f}'.format(total_credit) }}</th></tr></tbody></table></div>{% if (total_debit-total_credit)|abs < 0.005 %}<p class="flash" style="margin-top:14px">Debits and credits balance.</p>{% else %}<p class="flash error" style="margin-top:14px">Debits and credits do not balance. Review posted journals.</p>{% endif %}<p class="muted">This report excludes transactions that have not been posted to journals. It is not a complete financial statement.</p></div>
    """, rows=rows, total_debit=total_debit, total_credit=total_credit)

@app.route("/reports")
@login_required
def reports():
    cid = session.get("company_id") or current_company_id()
    rows = query_all("SELECT * FROM transactions WHERE company_id=? ORDER BY txn_date DESC,id DESC", (cid,))
    return page("Reports", """
    <div class="titlebar"><div><h1>Reports & Export</h1><p class="sub">Review activity and download transaction data.</p></div><a class="btn" href="{{ url_for('export_csv') }}">Export CSV</a></div><div class="grid"><div class="card"><div class="metric-label">Rows included</div><div class="metric">{{ rows|length }}</div></div><div class="card"><div class="metric-label">Receipt entries</div><div class="metric">{{ counts.get('Receipt',0) }}</div></div><div class="card"><div class="metric-label">Expense entries</div><div class="metric">{{ counts.get('Expense',0) }}</div></div><div class="card"><div class="metric-label">Other entries</div><div class="metric">{{ rows|length-counts.get('Receipt',0)-counts.get('Expense',0) }}</div></div></div><div class="card"><h2>Reporting notes</h2><p>CSV files can be opened in Excel. Transaction reports and manual-journal reports are separate at this stage.</p><p class="muted">For reliable financial statements, transaction-to-ledger posting, opening balances, bank reconciliation, and review of account mappings must be implemented before using this system for formal reporting.</p></div>
    """, rows=rows, counts={typ:sum(1 for r in rows if r["txn_type"]==typ) for typ in ["Receipt","Expense"]})

@app.route("/export.csv")
@login_required
def export_csv():
    cid = session.get("company_id") or current_company_id()
    rows = query_all("SELECT id,txn_date,txn_type,description,amount,currency,exchange_rate,amount_usd,category,party,bill_status,bill_number,payment_method,reference,notes,created_at FROM transactions WHERE company_id=? ORDER BY txn_date DESC,id DESC", (cid,))
    output = io.StringIO()
    writer = csv.writer(output)
    headers = list(rows[0].keys()) if rows else ["id","txn_date","txn_type","description","amount","currency","exchange_rate","amount_usd","category","party","bill_status","bill_number","payment_method","reference","notes","created_at"]
    writer.writerow(headers)
    for row in rows: writer.writerow([row[h] for h in headers])
    mem = io.BytesIO(("\ufeff" + output.getvalue()).encode("utf-8"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv; charset=utf-8", as_attachment=True, download_name="khosal_transactions.csv")

@app.route("/users", methods=["GET","POST"])
@admin_required
def users():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        role = request.form.get("role","accountant")
        if len(username) < 3 or len(password) < 12 or role not in ["admin","accountant"]:
            flash("Username must be at least 3 characters; password at least 12 characters; select a valid role.", "error")
        else:
            try:
                execute("INSERT INTO users (username,password_hash,role,company_id) VALUES (?,?,?,?)", (username,generate_password_hash(password),role,current_company_id()))
                audit("user_created", username)
                flash("User created.")
                return redirect(url_for("users"))
            except Exception:
                flash("That username already exists.", "error")
    rows = query_all("SELECT id,username,role,created_at FROM users ORDER BY username")
    return page("User Management", """
    <div class="titlebar"><div><h1>User Management</h1><p class="sub">Create login accounts for your team.</p></div></div><div class="section-grid"><div class="card"><h2>Create user</h2><form method="post"><input type="hidden" name="_csrf" value="{{ csrf_token() }}"><div style="margin-bottom:12px"><label>Username</label><input name="username" minlength="3" required></div><div style="margin-bottom:12px"><label>Temporary password (12+ characters)</label><input type="password" name="password" minlength="12" required></div><div><label>Role</label><select name="role"><option value="accountant">Accountant</option><option value="admin">Admin</option></select></div><div class="actions"><button>Create user</button></div></form></div><div class="card"><h2>Current users</h2><div class="table-wrap"><table><thead><tr><th>Username</th><th>Role</th><th>Created</th></tr></thead><tbody>{% for u in rows %}<tr><td>{{ u['username'] }}</td><td>{{ u['role'] }}</td><td>{{ u['created_at'] }}</td></tr>{% endfor %}</tbody></table></div></div></div>
    """, rows=rows)

@app.route("/change-password", methods=["GET","POST"])
@login_required
def change_password():
    if request.method == "POST":
        old = request.form.get("old_password","")
        new = request.form.get("new_password","")
        row = query_one("SELECT password_hash FROM users WHERE id=?", (session["user_id"],))
        if not row or not check_password_hash(row["password_hash"], old):
            flash("Current password is incorrect.", "error")
        elif len(new) < 12:
            flash("New password must be at least 12 characters.", "error")
        else:
            execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new),session["user_id"]))
            audit("password_changed", session.get("username",""))
            flash("Password changed successfully.")
            return redirect(url_for("dashboard"))
    return page("Change Password", """
    <div class="titlebar"><div><h1>Change Password</h1><p class="sub">Use a unique password with at least 12 characters.</p></div></div><div class="card" style="max-width:560px"><form method="post"><input type="hidden" name="_csrf" value="{{ csrf_token() }}"><div style="margin-bottom:14px"><label>Current password</label><input type="password" name="old_password" required></div><div><label>New password</label><input type="password" name="new_password" minlength="12" required></div><div class="actions"><button>Update password</button></div></form></div>
    """)

@app.route("/audit-log")
@admin_required
def audit_log():
    rows = query_all("SELECT a.created_at,a.action,a.detail,u.username FROM audit_log a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 200")
    return page("Audit Log", """
    <div class="titlebar"><div><h1>Audit Log</h1><p class="sub">Recent account and transaction actions.</p></div></div><div class="card"><div class="table-wrap"><table><thead><tr><th>Date</th><th>User</th><th>Action</th><th>Details</th></tr></thead><tbody>{% for r in rows %}<tr><td>{{ r['created_at'] }}</td><td>{{ r['username'] or 'System' }}</td><td>{{ r['action'] }}</td><td>{{ r['detail'] or '' }}</td></tr>{% else %}<tr><td colspan="4">No activity recorded.</td></tr>{% endfor %}</tbody></table></div></div>
    """, rows=rows)

@app.errorhandler(403)
def forbidden(error):
    return page("Access denied", "<div class='card'><h1>Access denied</h1><p>You do not have permission to open this page.</p><a class='btn' href='{{ url_for(\"dashboard\") }}'>Back to dashboard</a></div>"), 403

@app.errorhandler(400)
def bad_request(error):
    return page("Request error", "<div class='card'><h1>Request could not be accepted</h1><p>{{ error.description }}</p><p>Refresh the page and try again.</p><a class='btn' href='{{ url_for(\"dashboard\") }}'>Dashboard</a></div>", error=error), 400

@app.errorhandler(500)
def server_error(error):
    app.logger.exception("Unhandled server error")
    return page("Server error", "<div class='card'><h1>Something went wrong</h1><p>The request could not be completed. Check the Render logs for technical details.</p><a class='btn' href='{{ url_for(\"dashboard\") }}'>Dashboard</a></div>"), 500

# Create tables and seed only missing reference records; no existing rows are dropped.
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
