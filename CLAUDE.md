# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Finanzas Local" — a personal finance tracker (income, expenses, savings, bank statement imports) for a single user, in Spanish (Quetzales/GTQ currency). It's a local-first web app: no build step, no frontend framework, no ORM. Runs from a single Python file plus static HTML/CSS/JS.

## Running

```bat
scripts\start_windows.bat
```

This creates `.venv`, installs `requirements.txt`, and starts the server at `http://127.0.0.1:8765`. On macOS/Linux use `scripts/start_unix.sh`.

Manual run (venv already set up):

```bash
.venv\Scripts\python.exe server.py      # Windows
./.venv/bin/python server.py            # macOS/Linux
```

Demo mode (isolated fake data, resets on every run) via `scripts\start_demo_windows.bat` — sets `FINANZAS_DEMO=1` and points `FINANZAS_DATA_DIR` at `data_demo/` instead of `data/`.

There is no lint/build/test-runner config (no pytest, no package.json). The one check available:

```bash
python scripts/smoke_test.py
```

It seeds example data into a temp dir and asserts `build_dashboard()` totals — the closest thing to a regression test. Run it after touching dashboard/report calculation logic.

## Architecture

**Backend (`server.py`, ~3300 lines, single file, stdlib only):**

- `App(BaseHTTPRequestHandler)` is the entire HTTP layer — no framework. Routing is a manual if/elif chain over `self.path` inside `do_GET`/`do_POST`/`do_PUT`/`do_DELETE`, dispatching to `handle_api_get` for `GET /api/*`. Follow this same pattern (add an `elif parsed.path == "..."` branch) when adding endpoints, rather than introducing a router/framework.
- `wsgi.py` wraps the same `App` class to run under a real WSGI server (used for PythonAnywhere deployment) by monkeypatching `send_response`/`send_header`/`end_headers` to buffer into a WSGI response instead of writing to a live socket. `server.py` and `wsgi.py` must stay in sync — changes to `App`'s response-writing behavior affect both entry points.
- Persistence is raw `sqlite3` (no ORM). `init_db()` creates all tables with `CREATE TABLE IF NOT EXISTS`, and schema changes to existing installs go through `ensure_column()` / small `migrate_*` functions called from `init_db()` — there are no numbered migration files. When changing the schema, add an `ensure_column` call or a `migrate_*` function rather than assuming a fresh DB.
- `db_connection()` is a context manager wrapping `sqlite3.connect`; use it for all queries so commits/rollbacks stay consistent.
- Config is entirely environment variables read at module load (`FINANZAS_DATA_DIR`, `FINANZAS_AUTH`, `FINANZAS_USER`, `FINANZAS_PASSWORD` / `FINANZAS_PASSWORD_HASH`, `FINANZAS_SESSION_SECRET`, `FINANZAS_HOST`, `PORT`/`FINANZAS_PORT`, `FINANZAS_DEMO`, `FINANZAS_SECURE_COOKIE`). See `README.md` "Login Y Seguridad" and "Subir A PythonAnywhere" for the full list and hosting setup.
- Auth is a from-scratch cookie session (`make_session_token`/`read_session_token`, HMAC-signed with `SESSION_SECRET`) gated by `AUTH_ENABLED`. Note `AUTH_ENABLED = False` is hardcoded in `server.py` (auth is effectively off locally) while `static/app.js` has its own `AUTH_DISABLED = true` — both flags must be flipped together to re-enable login, and PythonAnywhere deploys override this via `FINANZAS_AUTH=1` env var (check how that env var actually reaches `AUTH_ENABLED` before assuming it works, since the constant is currently hardcoded).
- Bank statement import is format-specific parsing: separate `parse_<bank>_pdf()` functions (GYT, Banrural, BI, plus a generic fallback) and `parse_csv_upload()`, all funneling into `save_imports()` → the `imports` staging table. Rows sit in `imports` for manual review (`/api/imports`, action = Ingreso/Gasto/Ignorar/etc.) before `commit_imports()` promotes them into `transactions`. When adding support for a new bank's PDF format, follow the existing `parse_*_pdf` pattern and register it in `detect_pdf_bank`/`parse_pdf_upload`.
- Domain modules beyond core transactions live as parallel sets of tables + handlers in the same file: wedding budget (`wedding_*`), house payments (`house_*`), recurring monthly expenses (`recurring_*`), monthly savings "funds" (`monthly_budgets` / fund logic in `app.js`). Each has its own CRUD endpoints and its own attachment-file handling (`save_*_attachment`/`delete_*_attachment`), storing uploads under `data/wedding_files`, `data/house_files`, `data/transaction_files`.
- Report/export generation (`build_reports`, `build_report_xlsx`, `build_report_pdf`) writes XLSX and PDF byte streams by hand (manual OOXML zip / PDF object construction) — no `openpyxl`/`reportlab` dependency. Be careful with the manual `xlsx_cell`/`xlsx_sheet`/`pdf_escape_text` string building if you touch these; it's easy to produce a corrupt file.

**Frontend (`static/app.js`, ~1800 lines, vanilla JS, no build step, no framework):**

- Single global `state` object holds all client-side data (meta, imports, dashboard, wedding, house, recurring, reports, theme, etc.). Mutating `state` then calling the matching `render*()` function (e.g. `renderDashboard`, `renderWedding`, `renderReports`) is the update pattern — there's no reactive framework doing this automatically.
- `api(path, options)` wraps `fetch` against the `/api/*` endpoints defined in `server.py`; keep frontend request shapes in sync with the backend's manual routing/body parsing (no shared schema/types between them).
- `static/index.html` and `static/styles.css` are hand-written (no templating, no CSS framework/preprocessor). `index.html` is served directly by `App.serve_static`.
- Theme (dark/light) is persisted to `localStorage` and toggled via `document.documentElement.dataset.theme`.

**Data directory (`data/`, gitignored except `.gitkeep`):** holds `finanzas.db` (SQLite) and per-domain attachment folders. Real financial data must never be committed — the `.gitignore` also blanket-excludes `*.pdf`/`*.csv`/`*.xlsx`/image files repo-wide for this reason. Demo mode uses a sibling `data_demo/` directory instead so real data is never touched.

## Notes

- Everything is in Spanish, including category names, account names, error messages sent to the client, and UI text — match that when adding strings.
- `ACCOUNTS`, `INCOME_CATEGORIES`, `EXPENSE_CATEGORIES`, `SAVINGS_CATEGORIES`, `TRANSFER_CATEGORIES`, `TRANSACTION_TYPES` near the top of `server.py` are the canonical domain vocabulary (also exposed via `GET /api/meta`) — the frontend and importers key off these exact strings, so treat renames as breaking changes across both files.
- The account model is one specific person's real bank setup (GYT, BAC, Banrural accounts) described in `README.md` under "Modelo De Uso" — read that section before changing account/category semantics, since the dashboard's Ingreso/Gasto/Ahorro/Venta USD/Transferencia split depends on it.
