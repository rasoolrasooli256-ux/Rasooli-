"""Create the first administrator for a fresh database.
Run this only from a trusted terminal, not through a public web endpoint:
    python bootstrap_admin.py
"""
import getpass
from werkzeug.security import generate_password_hash
import app

username = input("New administrator username (at least 3 characters): ").strip()
if len(username) < 3:
    raise SystemExit("Username must be at least 3 characters.")
password = getpass.getpass("New administrator password (at least 12 characters): ")
confirm = getpass.getpass("Confirm password: ")
if len(password) < 12:
    raise SystemExit("Password must be at least 12 characters.")
if password != confirm:
    raise SystemExit("Passwords do not match.")

existing = app.query_one("SELECT id FROM users WHERE username = ?", (username,))
if existing:
    raise SystemExit("That username already exists. Choose another username.")

company = app.query_one("SELECT id FROM companies WHERE name = ?", ("Khosal Khan Tower",))
company_id = company["id"] if company else None
app.execute(
    "INSERT INTO users (username, password_hash, role, company_id) VALUES (?, ?, ?, ?)",
    (username, generate_password_hash(password), "admin", company_id),
)
print("Administrator created. Sign in through /login.")
print("Keep your password private and remove access to this terminal when finished.")
