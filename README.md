# Khosal Khan Tower ERP · Finance

A mobile-friendly Flask accounting starter application for **Khosal Khan Tower**. It supports AFN/USD transaction recording, basic reports, CSV export, users/roles, a chart of accounts, manual balanced journal entries, and a trial balance based on those manual journals.

## Important data safety notice

- This app creates tables with `CREATE TABLE IF NOT EXISTS` and adds missing starter/reference records. It does not drop tables or intentionally delete existing transaction rows.
- SQLite and Neon PostgreSQL are separate databases. Setting `DATABASE_URL` switches the app to PostgreSQL; it does **not** automatically copy transactions from a previous SQLite database into Neon. Before switching, back up and migrate any existing data you need.
- Keep a verified backup before deploying a replacement app. Test with a small sample first.
- The trial balance includes manual journal entries only. Transactions are not automatically posted to the ledger. This is not yet a complete statutory accounting package: opening balances, transaction-to-ledger posting, bank reconciliation, financial statements, and review of accounting mappings still need to be implemented and tested.

## Files

- `app.py` — application
- `requirements.txt` — dependencies
- `render.yaml` — Render deployment blueprint
- `.python-version` — Python version pin

## Local run

Requires Python 3.12.

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
```

Set a strong secret key before running:

```bash
# macOS/Linux
export KHOSAL_SECRET_KEY="replace-with-a-long-random-secret"
python app.py
```

On Windows PowerShell:

```powershell
$env:KHOSAL_SECRET_KEY="replace-with-a-long-random-secret"
python app.py
```

Without `DATABASE_URL`, the app uses a local SQLite file `khosal_transactions.db`. Keep that file backed up.

## Deploy to Render + Neon

1. Back up the current application and database before replacing any files.
2. Upload/commit these package files to your GitHub repository, replacing the old app only after the backup is verified.
3. In Neon, copy the PostgreSQL connection string. In Render, open your Web Service → **Environment** and set:
   - `DATABASE_URL` = Neon connection string
   - `KHOSAL_SECRET_KEY` = a long random secret (Render's Blueprint can generate one if you deploy from `render.yaml`)
4. Ensure the database connection string is private. Never paste it into public source code, chat, screenshots, or GitHub.
5. Use build command `pip install -r requirements.txt` and start command `gunicorn app:app`.
6. Deploy and inspect Render logs. Visit `/login`.
7. If the selected database is fresh and has no users, run `python bootstrap_admin.py` from a trusted terminal where the same `DATABASE_URL` and `KHOSAL_SECRET_KEY` environment variables are set. It prompts for an administrator username and password without putting the password in the command history. Do not expose this script through a public web route. If your existing database already has an admin user, use that account instead.
8. Test creating a sample transaction, refresh the site, then check whether it remains. Test with non-sensitive sample data before normal use.

## Migration reminder

A new Neon database will not contain records from the old SQLite database automatically. Export the old transactions as CSV for a backup and use a planned migration process to import records, preserve IDs/references, and verify row counts before considering the migration complete. Do not assume a successful deployment means old data has been migrated.

## Security

- Set a unique `KHOSAL_SECRET_KEY` in Render.
- Use strong unique passwords of at least 12 characters.
- Keep Render and Neon credentials private.
- Limit access to trusted users and maintain backups.
