from __future__ import annotations

import csv
import base64
import hashlib
import hmac
import io
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import tempfile
import time
import zipfile
from http import cookies
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape as xml_escape
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
from contextlib import contextmanager

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None


ROOT = Path(__file__).parent
STATIC = ROOT / "static"
DATA = Path(os.environ.get("FINANZAS_DATA_DIR", ROOT / "data"))
DB = DATA / "finanzas.db"
WEDDING_FILES = DATA / "wedding_files"
HOUSE_FILES = DATA / "house_files"
TRANSACTION_FILES = DATA / "transaction_files"
DEBT_FILES = DATA / "debt_files"
DEMO_MODE = os.environ.get("FINANZAS_DEMO", "").lower() in {"1", "true", "yes", "demo"}
EXCHANGE_RATE_URL = "https://open.er-api.com/v6/latest/USD"
DEFAULT_USD_GTQ_RATE = 7.8
LEGACY_WEDDING_DB = ROOT.parent / "Control-de-gastos-de-boda" / "data" / "boda.db"
APP_HOST = os.environ.get("FINANZAS_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("PORT", os.environ.get("FINANZAS_PORT", "8765")))
AUTH_ENABLED = os.environ.get("FINANZAS_AUTH", "1").lower() not in {"0", "false", "no", "off"}
AUTH_USER = os.environ.get("FINANZAS_USER", "ErickTest")
AUTH_PASSWORD = os.environ.get("FINANZAS_PASSWORD", "cambiar-esta-clave")
AUTH_PASSWORD_HASH = os.environ.get("FINANZAS_PASSWORD_HASH", "")
SESSION_SECRET_FROM_ENV = bool(os.environ.get("FINANZAS_SESSION_SECRET"))
# Sin secreto explicito generamos uno aleatorio por proceso: los tokens no son
# falsificables aunque no se configure. Contrapartida: las sesiones no sobreviven
# a un reinicio, algo aceptable para una app de un solo usuario.
SESSION_SECRET = os.environ.get("FINANZAS_SESSION_SECRET") or secrets.token_hex(32)
SESSION_COOKIE = "finanzas_session"
SESSION_TTL_SECONDS = int(os.environ.get("FINANZAS_SESSION_TTL", str(60 * 60 * 12)))
SECURE_COOKIE = os.environ.get("FINANZAS_SECURE_COOKIE", "").lower() in {"1", "true", "yes", "on"}


def password_matches(password: str) -> bool:
    if AUTH_PASSWORD_HASH:
        digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(digest, AUTH_PASSWORD_HASH)
    return hmac.compare_digest(password, AUTH_PASSWORD)


def make_session_token(username: str) -> str:
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    payload = f"{username}|{expires_at}|{secrets.token_hex(8)}"
    signature = hmac.new(SESSION_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    token = f"{payload}|{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(token).decode("ascii")


def read_session_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        username, expires_at_text, nonce, signature = decoded.rsplit("|", 3)
        payload = f"{username}|{expires_at_text}|{nonce}"
        expected = hmac.new(SESSION_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        if int(expires_at_text) < int(time.time()):
            return None
        return username
    except Exception:
        return None

SAVINGS_ACCOUNT = "Banrural - Cuenta ahorro"
FUND_ACCOUNT = "GYT - Cuenta ahorro sueldo"
FUND_CATEGORY = "Fondo mensual"
FUND_MONTHLY_AMOUNT = 500
FUND_INITIAL_BALANCE = 6129.74

ACCOUNTS = [
    "GYT - Cuenta ahorro sueldo",
    "GYT - Tarjeta debito",
    "GYT - Tarjeta credito",
    "BAC - Cuenta ahorro USD",
    SAVINGS_ACCOUNT,
    "Banco Industrial - Cuenta ahorro",
    "Efectivo",
    "Otro banco",
    "Otro",
]

INCOME_CATEGORIES = ["Sueldo GYT", "Sueldo BAC USD", "Venta USD", "Trabajo extra", "Otros ingresos"]
EXPENSE_CATEGORIES = [
    "Alquiler / vivienda",
    "Servicios",
    "Supermercado",
    "Transporte",
    "Comida fuera",
    "Salud",
    "Educacion",
    "Deudas",
    "Entretenimiento",
    "Ropa",
    "Ahorro / inversion",
    "Emergencias",
    "Otros gastos",
]
SAVINGS_CATEGORIES = ["Ahorro Banrural", "Ahorro extra", "Ahorro", "Salida ahorro"]
AHORRO_CATEGORY_IN = "Ahorro"
AHORRO_CATEGORY_OUT = "Salida ahorro"
AHORRO_TYPES = ["Ahorro", "Fondo"]
TRANSFER_CATEGORIES = ["Pago tarjeta", "Transferencia entre cuentas", "Retiro efectivo", "Fondo mensual"]
CATEGORIES = INCOME_CATEGORIES + EXPENSE_CATEGORIES + SAVINGS_CATEGORIES + TRANSFER_CATEGORIES
TRANSACTION_TYPES = ["Ingreso", "Gasto", "Ahorro", "Venta USD", "Transferencia"]
WEDDING_CATEGORIES = [
    "Lugar",
    "Comida",
    "Decoracion",
    "Musica",
    "Fotografia",
    "Vestuario",
    "Invitaciones",
    "Otro",
]
DEBT_TYPES = ["Tarjeta de credito", "Prestamo", "Otro pago"]
DEBT_BANKS = ["Banrural", "GYT", "BAC", "Banco Industrial", "Banco Promerica"]
DEBT_PAYMENT_CATEGORY = "Pago tarjeta"
WEDDING_SAMPLE_EXPENSES = [
    {
        "date": "2026-08-15",
        "description": "Reserva de salon",
        "category": "Lugar",
        "vendor": "Jardin Las Flores",
        "amount": 15000,
        "initialPayment": 5000,
        "paymentDate": "2026-08-15",
    },
    {
        "date": "2026-08-20",
        "description": "Cena para invitados",
        "category": "Comida",
        "vendor": "Banquetes Aurora",
        "amount": 22000,
        "initialPayment": 22000,
        "paymentDate": "2026-06-15",
    },
    {
        "date": "2026-09-01",
        "description": "Fotografia y video",
        "category": "Fotografia",
        "vendor": "Luz Studio",
        "amount": 6800,
        "initialPayment": 3500,
        "paymentDate": "2026-09-01",
    },
]
RECURRING_CATEGORIES = [
    "Vivienda",
    "Servicios",
    "Suscripciones",
    "Salud y bienestar",
    "Ahorro",
    "Otro",
]
RECURRING_SAVINGS_ACCOUNT = "Banrural - Cuenta ahorro"
RECURRING_PAYMENT_METHODS = ["TC", "Tarjeta de debito", "Efectivo"]
DEMO_RECURRING_SAMPLE_EXPENSES = [
    ("Internet casa", "Servicios", "TC", 325.00, "Mensual"),
    ("Streaming familiar", "Suscripciones", "TC", 89.00, "Mensual"),
    ("Gimnasio", "Salud y bienestar", "Tarjeta de debito", 180.00, "Mensual"),
    ("Cuota vivienda", "Vivienda", "Efectivo", 1200.00, "Mensual"),
    ("Respaldo nube", "Suscripciones", "TC", 240.00, "Anual"),
]

DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d+)\s+(.*)$")
AMOUNT_RE = re.compile(r"(-?Q[\d,]+\.\d{2})\s+(Q[\d,]+\.\d{2})$")
CARD_ENTRY_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\S+)\s+(.*?)\s+(-?(?:QTZ|DOL))\s+([\d,]+\.\d{2})(?:\s*\d{1,3})?$")
PDF_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4})\b")
PDF_MONEY_RE = re.compile(r"-?\s*Q?\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})|-?\s*Q?\s*\d+\.\d{2}")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_connection():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    WEDDING_FILES.mkdir(parents=True, exist_ok=True)
    HOUSE_FILES.mkdir(parents=True, exist_ok=True)
    TRANSACTION_FILES.mkdir(parents=True, exist_ok=True)
    DEBT_FILES.mkdir(parents=True, exist_ok=True)
    with db_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS imports (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source_name TEXT NOT NULL,
              bank TEXT NOT NULL,
              product TEXT NOT NULL,
              account TEXT NOT NULL,
              document TEXT,
              date TEXT NOT NULL,
              description TEXT NOT NULL,
              suggested_type TEXT NOT NULL,
              suggested_category TEXT NOT NULL,
              amount REAL NOT NULL,
              balance REAL,
              action TEXT NOT NULL DEFAULT 'Pendiente',
              notes TEXT,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              date TEXT NOT NULL,
              type TEXT NOT NULL,
              category TEXT NOT NULL,
              description TEXT NOT NULL,
              account TEXT NOT NULL,
              amount REAL NOT NULL,
              source_import_id INTEGER,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS wedding_settings (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS wedding_expenses (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              date TEXT NOT NULL,
              description TEXT NOT NULL,
              category TEXT NOT NULL,
              vendor TEXT NOT NULL DEFAULT '',
              amount REAL NOT NULL CHECK (amount >= 0),
              legacy_id INTEGER UNIQUE,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS wedding_payments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              expense_id INTEGER NOT NULL,
              date TEXT NOT NULL,
              amount REAL NOT NULL CHECK (amount > 0),
              note TEXT NOT NULL DEFAULT '',
              legacy_id INTEGER UNIQUE,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (expense_id) REFERENCES wedding_expenses(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS debts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              type TEXT NOT NULL,
              name TEXT NOT NULL,
              bank TEXT NOT NULL,
              current_balance REAL NOT NULL DEFAULT 0,
              credit_limit REAL,
              original_amount REAL,
              interest_rate REAL,
              statement_day INTEGER,
              due_day INTEGER,
              min_payment REAL,
              monthly_payment REAL,
              balance_usd REAL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS debt_payments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              debt_id INTEGER NOT NULL,
              date TEXT NOT NULL,
              amount REAL NOT NULL CHECK (amount > 0),
              note TEXT NOT NULL DEFAULT '',
              origin_account TEXT,
              transaction_id INTEGER,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY (debt_id) REFERENCES debts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ahorros (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              type TEXT NOT NULL DEFAULT 'Ahorro',
              name TEXT NOT NULL,
              bank TEXT NOT NULL,
              account TEXT NOT NULL,
              initial_balance REAL NOT NULL DEFAULT 0,
              monthly_target REAL NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS fondos (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              bank TEXT NOT NULL,
              account TEXT NOT NULL,
              initial_balance REAL NOT NULL DEFAULT 0,
              monthly_target REAL NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS house_payments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              payment_date TEXT NOT NULL,
              description TEXT NOT NULL,
              amount REAL NOT NULL CHECK (amount > 0),
              attachment_name TEXT,
              attachment_path TEXT,
              attachment_mime TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS recurring_expenses (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              category TEXT NOT NULL,
              account TEXT NOT NULL,
              amount REAL NOT NULL CHECK (amount > 0),
              frequency TEXT NOT NULL CHECK (frequency IN ('Mensual', 'Anual')),
              next_due_date TEXT,
              active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS recurring_payments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              recurring_expense_id INTEGER NOT NULL,
              month TEXT NOT NULL,
              paid_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(recurring_expense_id, month),
              FOREIGN KEY (recurring_expense_id) REFERENCES recurring_expenses(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monthly_budgets (
                month TEXT PRIMARY KEY,
                amount REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO wedding_settings (key, value) VALUES ('budget', '60000')"
        )
        ensure_column(conn, "wedding_expenses", "attachment_name", "TEXT")
        ensure_column(conn, "wedding_expenses", "attachment_path", "TEXT")
        ensure_column(conn, "wedding_expenses", "attachment_mime", "TEXT")
        ensure_column(conn, "wedding_payments", "attachment_name", "TEXT")
        ensure_column(conn, "wedding_payments", "attachment_path", "TEXT")
        ensure_column(conn, "wedding_payments", "attachment_mime", "TEXT")
        ensure_column(conn, "transactions", "attachment_name", "TEXT")
        ensure_column(conn, "transactions", "attachment_path", "TEXT")
        ensure_column(conn, "transactions", "attachment_mime", "TEXT")
        ensure_column(conn, "transactions", "usd_amount", "REAL")
        ensure_column(conn, "debt_payments", "attachment_name", "TEXT")
        ensure_column(conn, "debt_payments", "attachment_path", "TEXT")
        ensure_column(conn, "debt_payments", "attachment_mime", "TEXT")
        ensure_column(conn, "imports", "debt_id", "INTEGER")
        ensure_column(conn, "transactions", "debt_id", "INTEGER")
        ensure_column(conn, "debts", "balance_usd", "REAL")
        ensure_column(conn, "debts", "credit_limit_usd", "REAL")
        ensure_column(conn, "debts", "start_date", "TEXT")
        ensure_column(conn, "debts", "end_date", "TEXT")
        ensure_column(conn, "transactions", "ahorro_id", "INTEGER")
        ensure_column(conn, "transactions", "fund_id", "INTEGER")
        ensure_column(conn, "ahorros", "type", "TEXT NOT NULL DEFAULT 'Ahorro'")
        ensure_column(conn, "ahorros", "monthly_target", "REAL NOT NULL DEFAULT 0")
        migrate_existing_data(conn)
        migrate_usd_amount_backfill(conn)
        if not DEMO_MODE:
            migrate_wedding_data(conn)
        migrate_recurring_accounts(conn)
        migrate_savings_and_funds(conn)
        migrate_fondos_into_ahorros(conn)
        if DEMO_MODE:
            seed_recurring_expenses(conn)
            seed_demo_data(conn)


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def seed_recurring_expenses(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS count FROM recurring_expenses").fetchone()["count"]
    if count:
        return
    now = datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        """
        INSERT INTO recurring_expenses
        (name, category, account, amount, frequency, next_due_date, active, created_at)
        VALUES (?, ?, ?, ?, ?, NULL, 1, ?)
        """,
        [(*expense, now) for expense in DEMO_RECURRING_SAMPLE_EXPENSES],
    )


def seed_demo_data(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) AS count FROM transactions").fetchone()["count"]:
        return
    now = datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        """
        INSERT INTO transactions
        (date, type, category, description, account, amount, source_import_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
        """,
        [
            ("2026-06-01", "Ingreso", "Sueldo GYT", "Deposito de salario principal", "GYT - Cuenta ahorro sueldo", 6500.00, now),
            ("2026-06-05", "Ingreso", "Trabajo extra", "Pago de proyecto freelance", "Banco Industrial - Cuenta ahorro", 3500.00, now),
            ("2026-06-08", "Gasto", "Supermercado", "Compra de despensa", "GYT - Tarjeta credito", 620.35, now),
            ("2026-06-10", "Gasto", "Servicios", "Pago de internet residencial", "Banco Industrial - Cuenta ahorro", 325.00, now),
            ("2026-06-12", "Gasto", "Comida fuera", "Cena familiar", "GYT - Tarjeta credito", 185.75, now),
            ("2026-06-15", "Ahorro", "Ahorro Banrural", "Ahorro quincenal", "Banrural - Cuenta ahorro", 1200.00, now),
            ("2026-06-18", "Gasto", "Otros gastos", "Compra de emergencia", "Banrural - Cuenta ahorro", 250.00, now),
            ("2026-06-20", "Venta USD", "Venta USD", "Venta de dolares demo (USD 200, TC 7.80)", "BAC - Cuenta ahorro USD", 1560.00, now),
            ("2026-06-25", "Transferencia", "Fondo mensual", "Aporte mensual a fondo", "GYT - Cuenta ahorro sueldo", 500.00, now),
        ],
    )
    conn.execute(
        """
        INSERT INTO wedding_settings (key, value)
        VALUES ('budget', '60000')
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """
    )
    wedding_count = conn.execute("SELECT COUNT(*) AS count FROM wedding_expenses").fetchone()["count"]
    if not wedding_count:
        for expense in WEDDING_SAMPLE_EXPENSES:
            cursor = conn.execute(
                """
                INSERT INTO wedding_expenses
                (date, description, category, vendor, amount, legacy_id, created_at)
                VALUES (?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    expense["date"],
                    expense["description"],
                    expense["category"],
                    expense["vendor"],
                    float(expense["amount"]),
                    now,
                ),
            )
            initial_payment = float(expense.get("initialPayment") or 0)
            if initial_payment > 0:
                conn.execute(
                    """
                    INSERT INTO wedding_payments
                    (expense_id, date, amount, note, legacy_id, created_at)
                    VALUES (?, ?, ?, 'Abono inicial demo', NULL, ?)
                    """,
                    (cursor.lastrowid, expense.get("paymentDate") or expense["date"], initial_payment, now),
                )
    house_count = conn.execute("SELECT COUNT(*) AS count FROM house_payments").fetchone()["count"]
    if not house_count:
        conn.executemany(
            """
            INSERT INTO house_payments
            (payment_date, description, amount, created_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("2026-06-17", "Segundo abono de casa", 100000.00, now),
                ("2026-06-30", "Enganche de la casa", 200000.00, now),
            ],
        )


def migrate_recurring_accounts(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE recurring_expenses SET account='TC' WHERE account='Credito Cash'")
    conn.execute(
        "UPDATE recurring_expenses SET account='Tarjeta de debito' WHERE account='Debito GYT'"
    )
    conn.execute("UPDATE recurring_expenses SET account='Efectivo' WHERE account='Otro'")


def migrate_savings_and_funds(conn: sqlite3.Connection) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    ahorro = conn.execute(
        "SELECT id FROM ahorros WHERE type='Ahorro' AND account=?", (SAVINGS_ACCOUNT,)
    ).fetchone()
    if not ahorro:
        cur = conn.execute(
            "INSERT INTO ahorros (type, name, bank, account, initial_balance, created_at) VALUES ('Ahorro', ?, ?, ?, 0, ?)",
            ("Ahorro Banrural", "Banrural", SAVINGS_ACCOUNT, now),
        )
        ahorro_id = cur.lastrowid
    else:
        ahorro_id = ahorro["id"]
    conn.execute(
        "UPDATE transactions SET ahorro_id=? WHERE account=? AND ahorro_id IS NULL",
        (ahorro_id, SAVINGS_ACCOUNT),
    )

    fondo = conn.execute(
        "SELECT id FROM ahorros WHERE type='Fondo' AND account=? AND name=?", (FUND_ACCOUNT, "Fondo mensual")
    ).fetchone()
    if not fondo:
        cur = conn.execute(
            """
            INSERT INTO ahorros (type, name, bank, account, initial_balance, monthly_target, created_at)
            VALUES ('Fondo', ?, ?, ?, ?, ?, ?)
            """,
            ("Fondo mensual", "GYT", FUND_ACCOUNT, FUND_INITIAL_BALANCE, FUND_MONTHLY_AMOUNT, now),
        )
        fondo_id = cur.lastrowid
    else:
        fondo_id = fondo["id"]
    conn.execute(
        """
        UPDATE transactions SET ahorro_id=?
        WHERE account=? AND type='Transferencia' AND category=? AND ahorro_id IS NULL
        """,
        (fondo_id, FUND_ACCOUNT, FUND_CATEGORY),
    )


def migrate_fondos_into_ahorros(conn: sqlite3.Connection) -> None:
    fondo_rows = conn.execute("SELECT * FROM fondos").fetchall()
    for fondo in fondo_rows:
        existing = conn.execute(
            "SELECT id FROM ahorros WHERE type='Fondo' AND name=? AND account=?",
            (fondo["name"], fondo["account"]),
        ).fetchone()
        if existing:
            ahorro_id = existing["id"]
        else:
            cur = conn.execute(
                """
                INSERT INTO ahorros (type, name, bank, account, initial_balance, monthly_target, created_at)
                VALUES ('Fondo', ?, ?, ?, ?, ?, ?)
                """,
                (
                    fondo["name"], fondo["bank"], fondo["account"],
                    fondo["initial_balance"], fondo["monthly_target"], fondo["created_at"],
                ),
            )
            ahorro_id = cur.lastrowid
        conn.execute(
            "UPDATE transactions SET ahorro_id=?, fund_id=NULL WHERE fund_id=?",
            (ahorro_id, fondo["id"]),
        )
        conn.execute("DELETE FROM fondos WHERE id=?", (fondo["id"],))


def migrate_existing_data(conn: sqlite3.Connection) -> None:
    replacements = [
        ("GYT - Cuenta sueldo", "GYT - Cuenta ahorro sueldo"),
        ("BAM - Cuenta sueldo", "BAC - Cuenta ahorro USD"),
        ("BAM", "BAC"),
    ]
    for old, new in replacements:
        conn.execute("UPDATE transactions SET account=? WHERE account=?", (new, old))
        conn.execute("UPDATE imports SET account=? WHERE account=?", (new, old))
        conn.execute("UPDATE imports SET bank=? WHERE bank=?", (new, old))
    conn.execute(
        """
        UPDATE transactions
        SET category='Sueldo GYT'
        WHERE type='Ingreso' AND category='Salario' AND account='GYT - Cuenta ahorro sueldo'
        """
    )
    conn.execute(
        """
        UPDATE transactions
        SET category='Sueldo BAC USD'
        WHERE type='Ingreso' AND category='Salario' AND account='BAC - Cuenta ahorro USD'
        """
    )
    conn.execute(
        """
        UPDATE transactions
        SET description=REPLACE(description, 'BAM', 'BAC')
        WHERE description LIKE '%BAM%'
        """
    )
    migrate_import_bank_accounts(conn)


def migrate_usd_amount_backfill(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT id, description FROM transactions WHERE type='Venta USD' AND usd_amount IS NULL"
    ).fetchall()
    for row in rows:
        match = re.search(r"USD\s+([\d,]+(?:\.\d+)?)", row["description"] or "")
        if not match:
            continue
        usd_amount = float(match.group(1).replace(",", ""))
        conn.execute(
            "UPDATE transactions SET usd_amount=? WHERE id=?", (usd_amount, row["id"])
        )


def bank_from_source_name(source_name: str) -> str:
    name = source_name.upper()
    if "BANRURAL" in name or name.startswith("MOVS_"):
        return "Banrural"
    if "BANCO INDUSTRIAL" in name or re.search(r"(^|[-_\s])BI($|[-_\s.])", name):
        return "Banco Industrial"
    if "BAC" in name:
        return "BAC"
    if "GYT" in name or "G&T" in name or "CONTINENTAL" in name:
        return "GYT"
    return ""


def migrate_import_bank_accounts(conn: sqlite3.Connection) -> None:
    for row in conn.execute("SELECT id, source_name FROM imports").fetchall():
        detected_bank = bank_from_source_name(row["source_name"])
        if not detected_bank:
            continue
        account = account_for_bank(detected_bank, "GYT - Cuenta ahorro sueldo")
        product = infer_product(account)
        conn.execute(
            "UPDATE imports SET bank=?, product=?, account=? WHERE id=?",
            (detected_bank, product, account, row["id"]),
        )
        conn.execute(
            """
            UPDATE transactions
            SET account=?
            WHERE source_import_id=?
            """,
            (account, row["id"]),
        )


def migrate_wedding_data(conn: sqlite3.Connection) -> None:
    if not LEGACY_WEDDING_DB.exists():
        return
    already_migrated = conn.execute(
        "SELECT value FROM wedding_settings WHERE key='legacy_migrated'"
    ).fetchone()
    if already_migrated:
        return
    legacy = sqlite3.connect(LEGACY_WEDDING_DB)
    legacy.row_factory = sqlite3.Row
    try:
        budget_row = legacy.execute("SELECT value FROM settings WHERE key='budget'").fetchone()
        if budget_row:
            conn.execute(
                """
                INSERT INTO wedding_settings (key, value)
                VALUES ('budget', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (budget_row["value"],),
            )

        id_map: dict[int, int] = {}
        for row in legacy.execute("SELECT * FROM expenses ORDER BY id").fetchall():
            existing = conn.execute(
                "SELECT id FROM wedding_expenses WHERE legacy_id=?",
                (row["id"],),
            ).fetchone()
            if existing:
                id_map[row["id"]] = existing["id"]
                continue
            cursor = conn.execute(
                """
                INSERT INTO wedding_expenses
                (date, description, category, vendor, amount, legacy_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["date"],
                    row["description"],
                    row["category"],
                    row["vendor"],
                    float(row["amount"]),
                    row["id"],
                    row["created_at"],
                ),
            )
            id_map[row["id"]] = cursor.lastrowid

        for row in legacy.execute("SELECT * FROM payments ORDER BY id").fetchall():
            expense_id = id_map.get(row["expense_id"])
            if not expense_id:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO wedding_payments
                (expense_id, date, amount, note, legacy_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    expense_id,
                    row["date"],
                    float(row["amount"]),
                    row["note"],
                    row["id"],
                    row["created_at"],
                ),
            )
        conn.execute(
            "INSERT INTO wedding_settings (key, value) VALUES ('legacy_migrated', '1') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
    finally:
        legacy.close()


def seed_examples(conn: sqlite3.Connection) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    ahorro = conn.execute(
        "SELECT id FROM ahorros WHERE type='Ahorro' AND account=?", (SAVINGS_ACCOUNT,)
    ).fetchone()
    ahorro_id = ahorro["id"] if ahorro else None
    rows = [
        ("2026-06-01", "Ingreso", "Sueldo GYT", "Sueldo depositado en GYT", "GYT - Cuenta ahorro sueldo", 4500, None, None, now),
        ("2026-06-15", "Ingreso", "Sueldo BAC USD", "Sueldo depositado en BAC USD", "BAC - Cuenta ahorro USD", 2500, None, None, now),
        ("2026-06-20", "Ahorro", "Ahorro Banrural", "Sobrante movido a Banrural", "Banrural - Cuenta ahorro", 1000, None, ahorro_id, now),
        ("2026-06-22", "Venta USD", "Venta USD", "Venta manual de dolares", "Banrural - Cuenta ahorro", 1500, None, ahorro_id, now),
        ("2026-06-02", "Gasto", "Alquiler / vivienda", "Renta", "GYT - Cuenta ahorro sueldo", 1500, None, None, now),
        ("2026-06-03", "Gasto", "Supermercado", "Compra semanal", "GYT - Tarjeta credito", 420, None, None, now),
        ("2026-06-05", "Gasto", "Transporte", "Gasolina / bus", "Efectivo", 180, None, None, now),
    ]
    conn.executemany(
        """
        INSERT INTO transactions
        (date, type, category, description, account, amount, source_import_id, ahorro_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def money_to_number(value: str | float | int | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    negative = text.startswith("-") or text.startswith("(")
    cleaned = (
        text.replace("Q", "")
        .replace(",", "")
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )
    try:
        amount = float(cleaned)
    except ValueError:
        return 0.0
    return -amount if negative else amount


def normalize_date(value: str) -> str:
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return text


def parse_id_segment(text: str) -> int | None:
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def optional_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def optional_day(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        day = int(float(value))
    except (TypeError, ValueError):
        return None
    return day if 1 <= day <= 31 else None


def infer_product(account: str) -> str:
    account_upper = account.upper()
    if "TARJETA CREDITO" in account_upper:
        return "Tarjeta de credito"
    if "USD" in account_upper or "BAC" in account_upper:
        return "Cuenta ahorro USD"
    if "BANRURAL" in account_upper:
        return "Cuenta ahorro Banrural"
    if "BANCO INDUSTRIAL" in account_upper:
        return "Cuenta ahorro Banco Industrial"
    return "Cuenta ahorro / debito"


def account_for_bank(bank: str, fallback: str = "GYT - Cuenta ahorro sueldo") -> str:
    bank_upper = bank.upper()
    if "BANRURAL" in bank_upper:
        return "Banrural - Cuenta ahorro"
    if "INDUSTRIAL" in bank_upper or bank_upper == "BI":
        return "Banco Industrial - Cuenta ahorro"
    if "BAC" in bank_upper:
        return "BAC - Cuenta ahorro USD"
    if "GYT" in bank_upper or "G&T" in bank_upper:
        return "GYT - Cuenta ahorro sueldo"
    return fallback


def bank_from_account(account: str) -> str:
    account_upper = account.upper()
    if "BANRURAL" in account_upper:
        return "Banrural"
    if "INDUSTRIAL" in account_upper:
        return "Banco Industrial"
    if "BAC" in account_upper:
        return "BAC"
    if "GYT" in account_upper or "G&T" in account_upper:
        return "GYT"
    if "EFECTIVO" in account_upper:
        return "Efectivo"
    return "Otro"


def suggest_category(description: str, amount: float) -> str:
    desc = description.upper()
    if amount > 0:
        if any(token in desc for token in ("PLANILLA", "SALARIO", "SUELDO")):
            return "Sueldo GYT"
        if "CREDITO ACH" in desc:
            return "Otros ingresos"
        return "Otros ingresos"
    if any(token in desc for token in ("PAGO TARJETA", "MASTER CARD", "VISA")):
        return "Pago tarjeta"
    if any(token in desc for token in ("TIGO", "CLARO", "EEGSA", "ENERGUATE", "AGUA")):
        return "Servicios"
    if any(token in desc for token in ("SUPER", "WALMART", "DESPENSA", "PAIZ")):
        return "Supermercado"
    if any(token in desc for token in ("MCDONALD", "RESTAUR", "CAFE", "POLLO")):
        return "Comida fuera"
    if any(token in desc for token in ("GYM", "FARMA", "MEDIC")):
        return "Salud"
    if any(token in desc for token in ("UDEMY", "UNIVERS", "COLEG")):
        return "Educacion"
    if any(token in desc for token in ("TARJETA", "MASTER", "VISA")):
        return "Pago tarjeta"
    if any(token in desc for token in ("UBER", "GAS", "SHELL", "UNO ")):
        return "Transporte"
    return "Otros gastos"


def suggest_type(description: str, signed_amount: float, product: str = "") -> str:
    desc = description.upper()
    product_upper = product.upper()
    if signed_amount > 0:
        if "USD" in product_upper or "DOLAR" in product_upper:
            return "Ingreso"
        return "Ingreso"
    if any(token in desc for token in ("PAGO TARJETA", "MASTER CARD", "VISA")):
        return "Transferencia"
    if any(token in desc for token in ("BANRURAL", "AHORRO")):
        # "Ahorro" solo debe crearse desde el modulo de Ahorros (que vincula ahorro_id);
        # clasificar aqui dejaria un movimiento sin cuenta asociada.
        return "Transferencia"
    return "Gasto"


def default_category_for_type(tx_type: str, account: str = "") -> str:
    if tx_type == "Venta USD":
        return "Venta USD"
    if tx_type == "Ahorro":
        return "Ahorro Banrural" if "Banrural" in account else "Ahorro extra"
    if tx_type == "Transferencia":
        return "Transferencia entre cuentas"
    if tx_type == "Ingreso":
        if "BAC" in account:
            return "Sueldo BAC USD"
        if "GYT" in account:
            return "Sueldo GYT"
        return "Otros ingresos"
    return "Otros gastos"


def parse_gyt_pdf(path: Path, source_name: str, exchange_rate: float = DEFAULT_USD_GTQ_RATE) -> list[dict]:
    if PdfReader is None:
        raise RuntimeError("pypdf no esta disponible")

    reader = PdfReader(str(path))
    full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if "Cuenta: TCR" in full_text:
        return parse_gyt_credit_card_text(full_text, source_name, exchange_rate)

    raw_entries: list[str] = []
    current = ""
    for page in reader.pages:
        text = page.extract_text() or ""
        for raw_line in text.splitlines():
            line = " ".join(raw_line.strip().split())
            if not line or re.match(r"^\d{1,3}(\s+\d{1,3}){0,4}$", line):
                continue
            if line.startswith(("Nombre cuenta:", "Cuenta:", "Saldo inicial", "No. de", "Valor ", "Fecha Doc")):
                continue
            if "|" in line and re.search(r"\d{2}-\d{2}-\d{4}", line):
                continue
            if re.match(r"^\d{2}-\d{2}-\d{4}$", line) or re.match(r"^\d{2}:\d{2}:\d{2}$", line):
                continue
            if DATE_RE.match(line):
                if current:
                    raw_entries.append(current)
                current = line
            elif current:
                current += " " + line
    if current:
        raw_entries.append(current)

    rows = []
    for entry in raw_entries:
        start = DATE_RE.match(entry)
        amounts = AMOUNT_RE.search(entry)
        if not start or not amounts:
            continue
        fecha, doc, remainder = start.groups()
        amount_text, saldo_text = amounts.groups()
        description = remainder[: amounts.start() - start.end(2) - 1].strip()
        signed_amount = money_to_number(amount_text)
        tipo = suggest_type(description, signed_amount, "Cuenta monetaria / debito")
        rows.append(
            {
                "source_name": source_name,
                "bank": "GYT",
                "product": "Cuenta ahorro / debito",
                "account": "GYT - Cuenta ahorro sueldo",
                "document": doc,
                "date": normalize_date(fecha),
                "description": description,
                "suggested_type": tipo,
                "suggested_category": suggest_category(description, signed_amount),
                "amount": abs(signed_amount),
                "balance": money_to_number(saldo_text),
                "action": "Pendiente",
                "notes": "Extraido de PDF",
            }
        )
    return rows


def parse_gyt_credit_card_text(
    text: str,
    source_name: str,
    exchange_rate: float = DEFAULT_USD_GTQ_RATE,
) -> list[dict]:
    rows = []
    for raw_line in text.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line or re.match(r"^\d{1,3}(\s+\d{1,3}){0,4}$", line):
            continue
        match = CARD_ENTRY_RE.match(line)
        if not match:
            continue
        fecha, doc, description, currency, amount_text = match.groups()
        original_amount = money_to_number(amount_text)
        is_usd = currency.endswith("DOL")
        amount = round(original_amount * exchange_rate, 2) if is_usd else original_amount
        desc_upper = description.upper()
        is_adjustment = "AJUSTE" in desc_upper
        signed_amount = -amount if currency.startswith("-") else amount
        tx_type = "Ingreso" if signed_amount > 0 else "Gasto"
        if not is_adjustment and any(token in desc_upper for token in ("PAGO TARJETA", "MASTER CARD", "VISA")):
            tx_type = "Transferencia"
        category = "Pago tarjeta" if tx_type == "Transferencia" else suggest_category(description, signed_amount)
        notes = "Extraido de PDF tarjeta GYT"
        display_description = f"{description} {currency}"
        if is_usd:
            display_description = f"{description} {currency} {original_amount:.2f} (TC {exchange_rate:.4f})"
            notes += f" - USD {original_amount:.2f} convertido a GTQ con TC {exchange_rate:.4f}"
        rows.append(
            {
                "source_name": source_name,
                "bank": "GYT",
                "product": "Tarjeta de credito",
                "account": "GYT - Tarjeta credito",
                "document": doc,
                "date": normalize_date(fecha),
                "description": display_description[:120],
                "suggested_type": tx_type,
                "suggested_category": category,
                "amount": abs(signed_amount),
                "balance": None,
                "action": "Pendiente",
                "notes": notes,
            }
        )
    return rows


def extract_pdf_text(path: Path) -> str:
    if PdfReader is None:
        raise RuntimeError("pypdf no esta disponible")
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def detect_pdf_bank(path: Path, source_name: str) -> str:
    name = source_name.upper()
    if "BANRURAL" in name:
        return "Banrural"
    if "BAC" in name:
        return "BAC"
    if "INDUSTRIAL" in name or re.search(r"(^|[-_\s])BI($|[-_\s.])", name):
        return "Banco Industrial"
    if "GYT" in name or "G&T" in name:
        return "GYT"

    text = extract_pdf_text(path).upper()
    if "BANCO INDUSTRIAL" in text:
        return "Banco Industrial"
    if "BANRURAL" in text or "MOVIMIENTOS DE LA CUENTA" in text:
        return "Banrural"
    if "G&T" in text or "MONETARIO QTZ" in text or "NOMBRE CUENTA:" in text:
        return "GYT"
    if "BAC" in text:
        return "BAC"
    return ""


def pdf_entries_by_date(text: str) -> list[str]:
    entries: list[str] = []
    current = ""
    for raw_line in text.splitlines():
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        if PDF_DATE_RE.search(line):
            if current:
                entries.append(current)
            current = line
        elif current:
            current += " " + line
    if current:
        entries.append(current)
    return entries


def signed_amount_from_description(amount_text: str, description: str) -> float:
    amount = money_to_number(amount_text)
    if amount < 0:
        return amount
    desc = description.upper()
    negative_tokens = (
        "DEBITO",
        "DÃ‰BITO",
        "RETIRO",
        "COMPRA",
        "CONSUMO",
        "PAGO",
        "CARGO",
        "COMISION",
        "COMISIÃ“N",
    )
    positive_tokens = (
        "CREDITO",
        "CRÃ‰DITO",
        "DEPOSITO",
        "DEPÃ“SITO",
        "ABONO",
        "PLANILLA",
        "TRANSFERENCIA RECIBIDA",
    )
    if any(token in desc for token in positive_tokens):
        return amount
    if any(token in desc for token in negative_tokens):
        return -amount
    return amount


def parse_banrural_pdf(path: Path, source_name: str, account: str) -> list[dict]:
    text = extract_pdf_text(path)
    rows = []
    for entry in pdf_entries_by_date(text):
        date_match = PDF_DATE_RE.search(entry)
        amounts = list(PDF_MONEY_RE.finditer(entry))
        if not date_match or len(amounts) < 4:
            continue

        debit_match, credit_match, balance_match = amounts[-4], amounts[-3], amounts[-2]
        debit = money_to_number(debit_match.group())
        credit = money_to_number(credit_match.group())
        if debit == 0 and credit == 0:
            continue
        signed_amount = credit if credit > 0 else -abs(debit)
        description = entry[date_match.end() : debit_match.start()].strip(" -|")
        description = re.sub(r"\s{2,}", " ", description) or "Movimiento Banrural"
        rows.append(
            {
                "source_name": source_name,
                "bank": "Banrural",
                "product": "Cuenta ahorro Banrural",
                "account": account,
                "document": "",
                "date": normalize_date(date_match.group(1)),
                "description": description[:120],
                "suggested_type": suggest_type(description, signed_amount, "Cuenta ahorro Banrural"),
                "suggested_category": suggest_category(description, signed_amount),
                "amount": abs(signed_amount),
                "balance": money_to_number(balance_match.group()),
                "action": "Pendiente",
                "notes": "Extraido de PDF Banrural",
            }
        )
    return rows


def parse_bi_pdf(path: Path, source_name: str, account: str) -> list[dict]:
    text = extract_pdf_text(path)
    previous_balance = None
    previous_match = re.search(r"SALDO ANTERIOR\*+\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
    if previous_match:
        previous_balance = money_to_number(previous_match.group(1))

    rows = []
    for entry in pdf_entries_by_date(text):
        date_match = PDF_DATE_RE.search(entry)
        amounts = list(PDF_MONEY_RE.finditer(entry))
        if not date_match or not amounts:
            continue

        balance_match = amounts[1] if len(amounts) > 1 else amounts[0]
        balance = money_to_number(balance_match.group())
        if previous_balance is not None:
            signed_amount = round(balance - previous_balance, 2)
        else:
            movement_match = amounts[0]
            signed_amount = signed_amount_from_description(movement_match.group(), entry)
        previous_balance = balance
        if signed_amount == 0:
            continue

        movement_start = amounts[0].start()
        description = entry[date_match.end() : movement_start].strip(" -|")
        description = re.sub(r"\s{2,}", " ", description) or "Movimiento Banco Industrial"
        rows.append(
            {
                "source_name": source_name,
                "bank": "Banco Industrial",
                "product": "Cuenta ahorro Banco Industrial",
                "account": account,
                "document": "",
                "date": normalize_date(date_match.group(1)),
                "description": description[:120],
                "suggested_type": suggest_type(description, signed_amount, "Cuenta ahorro Banco Industrial"),
                "suggested_category": suggest_category(description, signed_amount),
                "amount": abs(signed_amount),
                "balance": balance,
                "action": "Pendiente",
                "notes": "Extraido de PDF Banco Industrial",
            }
        )
    return rows


def parse_generic_pdf(path: Path, source_name: str, bank: str, product: str, account: str) -> list[dict]:
    text = extract_pdf_text(path)
    rows = []
    for entry in pdf_entries_by_date(text):
        date_match = PDF_DATE_RE.search(entry)
        amounts = list(PDF_MONEY_RE.finditer(entry))
        if not date_match or not amounts:
            continue

        if len(amounts) >= 4:
            debit_match, credit_match, balance_match = amounts[-4], amounts[-3], amounts[-2]
            debit = money_to_number(debit_match.group())
            credit = money_to_number(credit_match.group())
            movement_match = credit_match if credit else debit_match
            signed_amount = credit if credit else -abs(debit)
        else:
            amount_candidates = amounts[:-1] if len(amounts) > 1 else amounts
            movement_match = next((match for match in amount_candidates if money_to_number(match.group()) != 0), amount_candidates[0])
            balance_match = amounts[-1] if len(amounts) > 1 else None
            signed_amount = signed_amount_from_description(movement_match.group(), entry)
        description = entry[date_match.end() : movement_match.start()].strip(" -|")
        description = re.sub(r"\s{2,}", " ", description) or "Movimiento importado"
        rows.append(
            {
                "source_name": source_name,
                "bank": bank,
                "product": product,
                "account": account,
                "document": "",
                "date": normalize_date(date_match.group(1)),
                "description": description[:120],
                "suggested_type": suggest_type(description, signed_amount, product),
                "suggested_category": suggest_category(description, signed_amount),
                "amount": abs(signed_amount),
                "balance": money_to_number(balance_match.group()) if balance_match else None,
                "action": "Pendiente",
                "notes": "Extraido de PDF",
            }
        )
    return rows


def parse_pdf_upload(
    path: Path,
    source_name: str,
    bank: str,
    product: str,
    account: str,
    exchange_rate: float = DEFAULT_USD_GTQ_RATE,
) -> list[dict]:
    detected_bank = detect_pdf_bank(path, source_name) or bank
    detected_account = account_for_bank(detected_bank, account)
    detected_product = infer_product(detected_account) if detected_account != account else product

    if detected_bank.upper() == "BANRURAL":
        return parse_banrural_pdf(path, source_name, detected_account)
    if "INDUSTRIAL" in detected_bank.upper():
        return parse_bi_pdf(path, source_name, detected_account)
    if detected_bank.upper() == "GYT":
        rows = parse_gyt_pdf(path, source_name, exchange_rate)
        if rows:
            return rows
    return parse_generic_pdf(path, source_name, detected_bank, detected_product, detected_account)


def parse_csv_upload(data: bytes, source_name: str, bank: str, product: str, account: str) -> list[dict]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Excel en Guatemala suele exportar CSV en Windows-1252 en vez de UTF-8;
        # cp1252 decodifica cualquier byte sin fallar, asi que es un fallback seguro.
        text = data.decode("cp1252", errors="replace")
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample)
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = []
    for item in reader:
        lowered = {str(k).strip().lower(): v for k, v in item.items() if k is not None}
        fecha = first(lowered, "fecha", "date", "fecha transaccion", "fecha operacion")
        desc = first(lowered, "descripcion", "descripciÃ³n", "descripcion_banco", "detalle", "concepto", "comercio")
        doc = first(lowered, "documento", "doc", "referencia", "no documento")
        saldo = money_to_number(first(lowered, "saldo", "balance"))
        monto = money_to_number(first(lowered, "monto", "amount", "importe", "valor"))
        if monto == 0:
            credito = money_to_number(first(lowered, "credito", "crÃ©dito", "creditos", "crÃ©ditos", "abono"))
            debito = money_to_number(first(lowered, "debito", "dÃ©bito", "debitos", "dÃ©bitos", "cargo"))
            monto = credito if credito else -abs(debito)
        if not fecha or not desc or monto == 0:
            continue
        tipo = suggest_type(desc, monto, product)
        rows.append(
            {
                "source_name": source_name,
                "bank": first(lowered, "banco") or bank,
                "product": first(lowered, "producto") or product,
                "account": first(lowered, "cuenta") or account,
                "document": doc,
                "date": normalize_date(fecha),
                "description": desc,
                "suggested_type": tipo,
                "suggested_category": first(lowered, "categoria", "categorÃ­a") or suggest_category(desc, monto),
                "amount": abs(monto),
                "balance": saldo,
                "action": "Pendiente",
                "notes": f"Importado desde CSV: {source_name}",
            }
        )
    return rows


def first(data: dict, *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def save_imports(rows: list[dict]) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    inserted = 0
    with db_connection() as conn:
        for row in rows:
            if row.get("document"):
                # Con numero de documento disponible, dos filas del mismo dia/monto/descripcion
                # solo son duplicado si ademas comparten el mismo documento (ej. dos "DEBITO ACH"
                # identicos el mismo dia son movimientos distintos si su documento difiere).
                exists = conn.execute(
                    """
                    SELECT 1 FROM imports
                    WHERE source_name=? AND date=? AND account=? AND description=? AND amount=? AND document=?
                    LIMIT 1
                    """,
                    (row["source_name"], row["date"], row["account"], row["description"], row["amount"], row["document"]),
                ).fetchone()
            else:
                exists = conn.execute(
                    """
                    SELECT 1 FROM imports
                    WHERE source_name=? AND date=? AND account=? AND description=? AND amount=?
                    LIMIT 1
                    """,
                    (row["source_name"], row["date"], row["account"], row["description"], row["amount"]),
                ).fetchone()
            if exists:
                continue
            conn.execute(
                """
                INSERT INTO imports
                (source_name, bank, product, account, document, date, description, suggested_type,
                 suggested_category, amount, balance, action, notes, debt_id, created_at)
                VALUES
                (:source_name, :bank, :product, :account, :document, :date, :description,
                 :suggested_type, :suggested_category, :amount, :balance, :action, :notes, :debt_id, :created_at)
                """,
                {**row, "created_at": now, "debt_id": row.get("debt_id")},
            )
            inserted += 1
    return inserted


def rowdict(row: sqlite3.Row) -> dict:
    return dict(row)


def latest_transaction_month() -> str | None:
    with db_connection() as conn:
        row = conn.execute(
            "SELECT MAX(substr(date,1,7)) AS month FROM transactions"
        ).fetchone()
    return row["month"] if row and row["month"] else None


def fetch_usd_gtq_rate() -> dict:
    try:
        with urlopen(EXCHANGE_RATE_URL, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        rate = float(payload["rates"]["GTQ"])
        return {
            "ok": True,
            "base": "USD",
            "target": "GTQ",
            "rate": rate,
            "updatedAt": payload.get("time_last_update_utc"),
            "provider": payload.get("provider"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "base": "USD",
            "target": "GTQ",
            "rate": None,
            "message": f"No se pudo obtener el tipo de cambio: {exc}",
        }


def serialize_wedding_expense(row: sqlite3.Row) -> dict:
    amount = float(row["amount"])
    paid_amount = min(float(row["paid_amount"]), amount)
    pending_amount = max(amount - paid_amount, 0)
    if paid_amount >= amount and amount > 0:
        status = "Pagado"
    elif paid_amount > 0:
        status = "Abonado"
    else:
        status = "Pendiente"
    return {
        "id": row["id"],
        "date": row["date"],
        "description": row["description"],
        "category": row["category"],
        "vendor": row["vendor"],
        "amount": amount,
        "paid_amount": paid_amount,
        "pending_amount": pending_amount,
        "status": status,
        "attachment_name": row["attachment_name"],
        "attachment_mime": row["attachment_mime"],
        "has_attachment": bool(row["attachment_path"]),
    }


def serialize_wedding_payment(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "date": row["date"],
        "amount": float(row["amount"]),
        "note": row["note"],
        "attachment_name": row["attachment_name"],
        "attachment_mime": row["attachment_mime"],
        "has_attachment": bool(row["attachment_path"]),
    }


def serialize_house_payment(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "paymentDate": row["payment_date"],
        "description": row["description"],
        "amount": float(row["amount"]),
        "attachment_name": row["attachment_name"],
        "attachment_mime": row["attachment_mime"],
        "has_attachment": bool(row["attachment_path"]),
        "created_at": row["created_at"],
    }


def build_house_state(month: str) -> dict:
    month = month if re.match(r"^\d{4}-\d{2}$", month or "") else datetime.now().strftime("%Y-%m")
    with db_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM house_payments
            WHERE substr(payment_date, 1, 7)=?
            ORDER BY payment_date DESC, id DESC
            """,
            (month,),
        ).fetchall()
    payments = [serialize_house_payment(row) for row in rows]
    total = sum(payment["amount"] for payment in payments)
    return {
        "month": month,
        "total": round(total, 2),
        "count": len(payments),
        "payments": payments,
    }


def build_wedding_state() -> dict:
    with db_connection() as conn:
        budget_row = conn.execute(
            "SELECT value FROM wedding_settings WHERE key='budget'"
        ).fetchone()
        rows = conn.execute(
            """
            SELECT
              e.id,
              e.date,
              e.description,
              e.category,
              e.vendor,
              e.amount,
              e.attachment_name,
              e.attachment_path,
              e.attachment_mime,
              COALESCE(SUM(p.amount), 0) AS paid_amount
            FROM wedding_expenses e
            LEFT JOIN wedding_payments p ON p.expense_id = e.id
            GROUP BY e.id
            ORDER BY e.created_at DESC, e.id DESC
            """
        ).fetchall()
        payment_rows = conn.execute(
            "SELECT * FROM wedding_payments ORDER BY date DESC, id DESC"
        ).fetchall()
    payments_by_expense: dict[int, list[dict]] = {}
    for payment_row in payment_rows:
        payments_by_expense.setdefault(payment_row["expense_id"], []).append(
            serialize_wedding_payment(payment_row)
        )
    expenses = [serialize_wedding_expense(row) for row in rows]
    for expense, row in zip(expenses, rows):
        expense["payments"] = payments_by_expense.get(row["id"], [])
    budget = float(budget_row["value"]) if budget_row else 0
    spent = sum(expense["amount"] for expense in expenses)
    paid = sum(expense["paid_amount"] for expense in expenses)
    pending = sum(expense["pending_amount"] for expense in expenses)
    return {
        "budget": budget,
        "spent": spent,
        "paid": paid,
        "pending": pending,
        "available": budget - spent,
        "progress": spent / budget if budget else 0,
        "categories": WEDDING_CATEGORIES,
        "expenses": expenses,
    }


def serialize_debt(row: sqlite3.Row) -> dict:
    is_card = row["type"] == "Tarjeta de credito"
    is_other = row["type"] == "Otro pago"
    balance = float(row["current_balance"] or 0)
    limit = float(row["credit_limit"]) if row["credit_limit"] is not None else None
    limit_usd = float(row["credit_limit_usd"]) if row["credit_limit_usd"] is not None else None
    balance_usd = float(row["balance_usd"]) if row["balance_usd"] is not None else None
    original = float(row["original_amount"]) if row["original_amount"] is not None else None
    available = max(limit - balance, 0) if is_card and limit else None
    utilization = min(balance / limit, 1) if is_card and limit else None
    available_usd = max(limit_usd - (balance_usd or 0), 0) if is_card and limit_usd else None
    utilization_usd = min((balance_usd or 0) / limit_usd, 1) if is_card and limit_usd else None
    paid = max(original - balance, 0) if not is_card and original else None
    progress = min(paid / original, 1) if not is_card and original else None
    return {
        "id": row["id"],
        "type": row["type"],
        "name": row["name"],
        "bank": row["bank"],
        "current_balance": balance,
        "credit_limit": limit,
        "credit_limit_usd": limit_usd,
        "original_amount": original,
        "interest_rate": float(row["interest_rate"]) if row["interest_rate"] is not None else None,
        "statement_day": row["statement_day"],
        "due_day": row["due_day"],
        "min_payment": float(row["min_payment"]) if row["min_payment"] is not None else None,
        "monthly_payment": float(row["monthly_payment"]) if row["monthly_payment"] is not None else None,
        "balance_usd": balance_usd,
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "available": available,
        "utilization": utilization,
        "available_usd": available_usd,
        "utilization_usd": utilization_usd,
        "paid": paid,
        "progress": progress,
        "is_other": is_other,
        "created_at": row["created_at"],
    }


def serialize_debt_payment(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "date": row["date"],
        "amount": float(row["amount"]),
        "note": row["note"],
        "origin_account": row["origin_account"],
        "attachment_name": row["attachment_name"],
        "attachment_mime": row["attachment_mime"],
        "has_attachment": bool(row["attachment_path"]),
    }


def build_debts_state() -> dict:
    with db_connection() as conn:
        rows = conn.execute("SELECT * FROM debts ORDER BY created_at DESC, id DESC").fetchall()
        payment_rows = conn.execute(
            "SELECT * FROM debt_payments ORDER BY date DESC, id DESC"
        ).fetchall()
    payments_by_debt: dict[int, list[dict]] = {}
    for payment_row in payment_rows:
        payments_by_debt.setdefault(payment_row["debt_id"], []).append(
            serialize_debt_payment(payment_row)
        )
    debts = [serialize_debt(row) for row in rows]
    for debt in debts:
        debt["payments"] = payments_by_debt.get(debt["id"], [])
    total_debt = sum(debt["current_balance"] for debt in debts)
    total_available = sum(debt["available"] or 0 for debt in debts if debt["type"] == "Tarjeta de credito")
    min_payment_total = sum(debt["min_payment"] or 0 for debt in debts if debt["type"] == "Tarjeta de credito")
    return {
        "types": DEBT_TYPES,
        "banks": DEBT_BANKS,
        "accounts": ACCOUNTS,
        "debts": debts,
        "totalDebt": total_debt,
        "totalAvailable": total_available,
        "minPaymentTotal": min_payment_total,
        "count": len(debts),
    }


def serialize_ahorro(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "name": row["name"],
        "bank": row["bank"],
        "account": row["account"],
        "initial_balance": float(row["initial_balance"]),
        "monthly_target": float(row["monthly_target"]),
        "current_balance": float(row["initial_balance"]) + float(row["net_movement"]),
        "created_at": row["created_at"],
    }


def build_ahorros_state() -> dict:
    with db_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.*, COALESCE(SUM(
              CASE
                WHEN a.type='Fondo' AND t.type='Transferencia' THEN t.amount
                WHEN a.type='Ahorro' AND t.type='Ahorro' THEN t.amount
                WHEN a.type='Ahorro' AND t.type='Gasto' THEN -t.amount
                ELSE 0
              END
            ), 0) AS net_movement
            FROM ahorros a
            LEFT JOIN transactions t ON t.ahorro_id = a.id
            GROUP BY a.id
            ORDER BY a.created_at DESC, a.id DESC
            """
        ).fetchall()
        tx_rows = conn.execute(
            "SELECT * FROM transactions WHERE ahorro_id IS NOT NULL ORDER BY date DESC, id DESC"
        ).fetchall()
    movements_by_ahorro: dict[int, list[dict]] = {}
    for tx in tx_rows:
        movements_by_ahorro.setdefault(tx["ahorro_id"], []).append(rowdict(tx))
    ahorros = [serialize_ahorro(row) for row in rows]
    for ahorro in ahorros:
        ahorro["movements"] = movements_by_ahorro.get(ahorro["id"], [])
    return {
        "types": AHORRO_TYPES,
        "banks": DEBT_BANKS,
        "accounts": ACCOUNTS,
        "ahorros": ahorros,
        "totalBalance": sum(ahorro["current_balance"] for ahorro in ahorros),
        "count": len(ahorros),
    }


def build_recurring_state(month: str) -> dict:
    month = month if re.match(r"^\d{4}-\d{2}$", month or "") else datetime.now().strftime("%Y-%m")
    with db_connection() as conn:
        rows = conn.execute(
            """
            SELECT r.*,
                   CASE WHEN p.id IS NULL THEN 0 ELSE 1 END AS paid
            FROM recurring_expenses r
            LEFT JOIN recurring_payments p
              ON p.recurring_expense_id = r.id AND p.month = ?
            ORDER BY r.active DESC, r.category, r.name
            """,
            (month,),
        ).fetchall()

    items = []
    monthly_equivalent = 0.0
    annual_provision = 0.0
    due_this_month = 0.0
    paid_this_month = 0.0
    for row in rows:
        item = rowdict(row)
        amount = float(item["amount"])
        equivalent = amount if item["frequency"] == "Mensual" else amount / 12
        is_due = item["frequency"] == "Mensual" or (
            item["frequency"] == "Anual"
            and item.get("next_due_date")
            and item["next_due_date"][:7] == month
        )
        item["monthly_equivalent"] = round(equivalent, 2)
        item["is_due"] = bool(is_due and item["active"])
        item["paid"] = bool(item["paid"])
        items.append(item)
        if not item["active"]:
            continue
        monthly_equivalent += equivalent
        if item["frequency"] == "Anual":
            annual_provision += equivalent
        if is_due:
            due_this_month += amount
            if item["paid"]:
                paid_this_month += amount

    return {
        "month": month,
        "items": items,
        "categories": RECURRING_CATEGORIES,
        "accounts": RECURRING_PAYMENT_METHODS,
        "summary": {
            "monthlyEquivalent": round(monthly_equivalent, 2),
            "annualProvision": round(annual_provision, 2),
            "dueThisMonth": round(due_this_month, 2),
            "paidThisMonth": round(paid_this_month, 2),
            "pendingThisMonth": round(max(0, due_this_month - paid_this_month), 2),
        },
    }


def safe_filename(value: str) -> str:
    name = Path(value).name.strip() or "archivo"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]


ATTACHMENT_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".jfif", ".webp",
    ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif",
}
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
# Topes del cuerpo de la solicitud para no cargar bloques enormes en memoria.
MAX_JSON_BYTES = 1 * 1024 * 1024
MAX_UPLOAD_BYTES = MAX_ATTACHMENT_BYTES + 5 * 1024 * 1024  # margen para overhead multipart


def save_attachment(base_dir: Path, prefix: str, file: dict) -> tuple[str, Path, str]:
    original_name = safe_filename(file.get("filename", "archivo"))
    suffix = Path(original_name).suffix.lower()
    if suffix not in ATTACHMENT_EXTENSIONS:
        raise ValueError("Solo se permiten archivos PDF o imagenes.")
    data = file.get("data", b"")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise ValueError("El archivo supera el limite de 15 MB.")
    mime = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    if suffix == ".pdf":
        mime = "application/pdf"
    elif not mime.startswith("image/"):
        mime = "image/jpeg"
    file_path = base_dir / f"{prefix}{original_name}"
    file_path.write_bytes(data)
    return original_name, file_path, mime


def delete_attachment(base_dir: Path, relative_path: str | None) -> None:
    if not relative_path:
        return
    file_path = (DATA / relative_path).resolve()
    try:
        file_path.relative_to(base_dir.resolve())
    except ValueError:
        return
    file_path.unlink(missing_ok=True)


def save_wedding_attachment(expense_id: int, file: dict) -> tuple[str, Path, str]:
    return save_attachment(WEDDING_FILES, f"{expense_id}_", file)


def save_wedding_payment_attachment(payment_id: int, file: dict) -> tuple[str, Path, str]:
    return save_attachment(WEDDING_FILES, f"payment_{payment_id}_", file)


def save_house_attachment(payment_id: int, file: dict) -> tuple[str, Path, str]:
    return save_attachment(HOUSE_FILES, f"{payment_id}_", file)


def save_transaction_attachment(transaction_id: int, file: dict) -> tuple[str, Path, str]:
    return save_attachment(TRANSACTION_FILES, f"{transaction_id}_", file)


def save_debt_payment_attachment(payment_id: int, file: dict) -> tuple[str, Path, str]:
    return save_attachment(DEBT_FILES, f"payment_{payment_id}_", file)


def delete_wedding_attachment(relative_path: str | None) -> None:
    delete_attachment(WEDDING_FILES, relative_path)


def delete_house_attachment(relative_path: str | None) -> None:
    delete_attachment(HOUSE_FILES, relative_path)


def delete_transaction_attachment(relative_path: str | None) -> None:
    delete_attachment(TRANSACTION_FILES, relative_path)


def delete_debt_attachment(relative_path: str | None) -> None:
    delete_attachment(DEBT_FILES, relative_path)


class App(BaseHTTPRequestHandler):
    server_version = "FinanzasLocal/0.1"

    PUBLIC_API_PATHS = {"/api/login", "/api/logout", "/api/session"}

    def current_user(self) -> str | None:
        if not AUTH_ENABLED:
            return AUTH_USER
        jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        morsel = jar.get(SESSION_COOKIE)
        return read_session_token(morsel.value if morsel else None)

    def require_auth(self, path: str) -> bool:
        if not AUTH_ENABLED or path in self.PUBLIC_API_PATHS:
            return True
        if self.current_user():
            return True
        self.send_json({"ok": False, "message": "No autorizado"}, status=401)
        return False

    def send_auth_cookie(self, username: str) -> None:
        token = make_session_token(username)
        cookie = cookies.SimpleCookie()
        cookie[SESSION_COOKIE] = token
        cookie[SESSION_COOKIE]["path"] = "/"
        cookie[SESSION_COOKIE]["max-age"] = str(SESSION_TTL_SECONDS)
        cookie[SESSION_COOKIE]["httponly"] = True
        cookie[SESSION_COOKIE]["samesite"] = "Lax"
        if SECURE_COOKIE:
            cookie[SESSION_COOKIE]["secure"] = True
        self.send_header("Set-Cookie", cookie.output(header="").strip())

    def clear_auth_cookie(self) -> None:
        cookie = cookies.SimpleCookie()
        cookie[SESSION_COOKIE] = ""
        cookie[SESSION_COOKIE]["path"] = "/"
        cookie[SESSION_COOKIE]["max-age"] = "0"
        cookie[SESSION_COOKIE]["httponly"] = True
        cookie[SESSION_COOKIE]["samesite"] = "Lax"
        if SECURE_COOKIE:
            cookie[SESSION_COOKIE]["secure"] = True
        self.send_header("Set-Cookie", cookie.output(header="").strip())

    def handle_login(self) -> None:
        body = self.read_json()
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        if username != AUTH_USER or not password_matches(password):
            self.send_json({"ok": False, "message": "Usuario o contraseÃ±a incorrectos"}, status=401)
            return
        payload = json.dumps({"ok": True, "user": username}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_auth_cookie(username)
        self.end_headers()
        self.wfile.write(payload)

    def handle_logout(self) -> None:
        payload = json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.clear_auth_cookie()
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            if not self.require_auth(parsed.path):
                return
            self.handle_api_get(parsed.path, parse_qs(parsed.query))
            return
        self.serve_static(parsed.path)

    def reject_oversized_body(self) -> bool:
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = 0
        content_type = self.headers.get("Content-Type", "")
        limit = MAX_UPLOAD_BYTES if content_type.startswith("multipart/form-data") else MAX_JSON_BYTES
        if length > limit:
            self.send_error(413, "El cuerpo de la solicitud es demasiado grande")
            return True
        return False

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self.require_auth(parsed.path):
            return
        if self.reject_oversized_body():
            return
        if parsed.path == "/api/login":
            self.handle_login()
        elif parsed.path == "/api/logout":
            self.handle_logout()
        elif parsed.path == "/api/import":
            self.handle_import()
        elif parsed.path == "/api/monthly-control":
            self.update_monthly_control(self.read_json())
        elif parsed.path == "/api/imports/update":
            body = self.read_json()
            self.update_import(body)
        elif parsed.path == "/api/imports/commit":
            self.commit_imports(self.read_json())
        elif parsed.path == "/api/transactions":
            body, file = self.read_transaction_payload()
            self.create_transaction(body, file)
        elif parsed.path == "/api/transactions/delete":
            body = self.read_json()
            self.delete_transactions(body.get("ids", []))
        elif parsed.path.startswith("/api/transactions/") and parsed.path.endswith("/attachment"):
            transaction_id = parse_id_segment(parsed.path.split("/")[3])
            if transaction_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            _, file = self.read_transaction_payload()
            self.update_transaction_attachment(transaction_id, file)
        elif parsed.path == "/api/wedding/expenses":
            body, file, initial_payment_file = self.read_wedding_expense_create_payload()
            self.create_wedding_expense(body, file, initial_payment_file)
        elif parsed.path == "/api/wedding/sample-data":
            self.load_wedding_sample_data()
        elif parsed.path.startswith("/api/wedding/expenses/") and parsed.path.endswith("/payments"):
            expense_id = parse_id_segment(parsed.path.split("/")[4])
            if expense_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            body, file = self.read_wedding_expense_payload()
            self.create_wedding_payment(expense_id, body, file)
        elif parsed.path.startswith("/api/wedding/expenses/") and parsed.path.endswith("/attachment"):
            expense_id = parse_id_segment(parsed.path.split("/")[4])
            if expense_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            _, file = self.read_wedding_expense_payload()
            self.update_wedding_attachment(expense_id, file)
        elif parsed.path.startswith("/api/wedding/payments/") and parsed.path.endswith("/attachment"):
            payment_id = parse_id_segment(parsed.path.split("/")[4])
            if payment_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            _, file = self.read_wedding_expense_payload()
            self.update_wedding_payment_attachment(payment_id, file)
        elif parsed.path == "/api/debts":
            self.create_debt(self.read_json())
        elif parsed.path.startswith("/api/debts/payments/") and parsed.path.endswith("/attachment"):
            payment_id = parse_id_segment(parsed.path.split("/")[4])
            if payment_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            _, file = self.read_wedding_expense_payload()
            self.update_debt_payment_attachment(payment_id, file)
        elif parsed.path.startswith("/api/debts/") and parsed.path.endswith("/payments"):
            debt_id = parse_id_segment(parsed.path.split("/")[3])
            if debt_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            body, file = self.read_wedding_expense_payload()
            self.create_debt_payment(debt_id, body, file)
        elif parsed.path == "/api/ahorros":
            self.create_ahorro(self.read_json())
        elif parsed.path.startswith("/api/ahorros/") and parsed.path.endswith("/movements"):
            ahorro_id = parse_id_segment(parsed.path.split("/")[3])
            if ahorro_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            body, file = self.read_wedding_expense_payload()
            self.create_ahorro_movement(ahorro_id, body, file)
        elif parsed.path == "/api/house/payments":
            body, file = self.read_wedding_expense_payload()
            self.create_house_payment(body, file)
        elif parsed.path.startswith("/api/house/payments/") and parsed.path.endswith("/attachment"):
            payment_id = parse_id_segment(parsed.path.split("/")[4])
            if payment_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            _, file = self.read_wedding_expense_payload()
            self.update_house_attachment(payment_id, file)
        elif parsed.path == "/api/recurring/expenses":
            self.create_recurring_expense(self.read_json())
        elif parsed.path.startswith("/api/recurring/expenses/") and parsed.path.endswith("/toggle-paid"):
            expense_id = parse_id_segment(parsed.path.split("/")[4])
            if expense_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            self.toggle_recurring_paid(expense_id, self.read_json())
        else:
            self.send_error(404)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if not self.require_auth(parsed.path):
            return
        if self.reject_oversized_body():
            return
        if parsed.path == "/api/monthly-control":
            self.update_monthly_control(self.read_json())
        elif parsed.path.startswith("/api/transactions/"):
            transaction_id = parse_id_segment(parsed.path.rsplit("/", 1)[-1])
            if transaction_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            body = self.read_json()
            self.update_transaction(transaction_id, body)
        elif parsed.path == "/api/wedding/budget":
            body = self.read_json()
            self.update_wedding_budget(body)
        elif parsed.path.startswith("/api/wedding/expenses/"):
            expense_id = parse_id_segment(parsed.path.rsplit("/", 1)[-1])
            if expense_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            self.update_wedding_expense(expense_id, self.read_json())
        elif parsed.path.startswith("/api/debts/"):
            debt_id = parse_id_segment(parsed.path.rsplit("/", 1)[-1])
            if debt_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            self.update_debt(debt_id, self.read_json())
        elif parsed.path.startswith("/api/ahorros/"):
            ahorro_id = parse_id_segment(parsed.path.rsplit("/", 1)[-1])
            if ahorro_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            self.update_ahorro(ahorro_id, self.read_json())
        elif parsed.path.startswith("/api/recurring/expenses/"):
            expense_id = parse_id_segment(parsed.path.rsplit("/", 1)[-1])
            if expense_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            self.update_recurring_expense(expense_id, self.read_json())
        else:
            self.send_error(404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if not self.require_auth(parsed.path):
            return
        if parsed.path == "/api/imports":
            debt_id = parse_qs(parsed.query).get("debtId", [None])[0]
            with db_connection() as conn:
                if debt_id not in (None, ""):
                    conn.execute(
                        """
                        DELETE FROM imports
                        WHERE debt_id = ? AND action NOT IN ('Registrado', 'Ignorar / transferencia')
                        """,
                        (int(debt_id),),
                    )
                else:
                    conn.execute(
                        "DELETE FROM imports WHERE action NOT IN ('Registrado', 'Ignorar / transferencia')"
                    )
            self.send_json({"ok": True})
        elif parsed.path.startswith("/api/transactions/"):
            transaction_id = parse_id_segment(parsed.path.rsplit("/", 1)[-1])
            if transaction_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            self.delete_transaction(transaction_id)
        elif parsed.path.startswith("/api/wedding/expenses/"):
            expense_id = parse_id_segment(parsed.path.rsplit("/", 1)[-1])
            if expense_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            self.delete_wedding_expense(expense_id)
        elif parsed.path.startswith("/api/debts/"):
            debt_id = parse_id_segment(parsed.path.rsplit("/", 1)[-1])
            if debt_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            self.delete_debt(debt_id)
        elif parsed.path.startswith("/api/ahorros/"):
            ahorro_id = parse_id_segment(parsed.path.rsplit("/", 1)[-1])
            if ahorro_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            self.delete_ahorro(ahorro_id)
        elif parsed.path.startswith("/api/house/payments/"):
            payment_id = parse_id_segment(parsed.path.rsplit("/", 1)[-1])
            if payment_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            self.delete_house_payment(payment_id)
        elif parsed.path.startswith("/api/recurring/expenses/"):
            expense_id = parse_id_segment(parsed.path.rsplit("/", 1)[-1])
            if expense_id is None:
                self.send_error(400, "Identificador invalido en la URL")
                return
            self.delete_recurring_expense(expense_id)
        else:
            self.send_error(404)

    def handle_api_get(self, path: str, query: dict) -> None:
        if path == "/api/session":
            user = self.current_user()
            self.send_json({"authenticated": bool(user), "user": user})
        elif path == "/api/meta":
            self.send_json(
                {
                    "accounts": ACCOUNTS,
                    "incomeCategories": INCOME_CATEGORIES,
                    "expenseCategories": EXPENSE_CATEGORIES,
                    "savingsCategories": SAVINGS_CATEGORIES,
                    "transferCategories": TRANSFER_CATEGORIES,
                    "categories": CATEGORIES,
                    "transactionTypes": TRANSACTION_TYPES,
                    "latestMonth": latest_transaction_month(),
                }
            )
        elif path == "/api/imports":
            debt_id = query.get("debtId", [None])[0]
            with db_connection() as conn:
                if debt_id not in (None, ""):
                    rows = conn.execute(
                        """
                        SELECT * FROM imports
                        WHERE action NOT IN ('Registrado', 'Ignorar / transferencia')
                          AND debt_id = ?
                        ORDER BY date, id
                        """,
                        (int(debt_id),),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT * FROM imports
                        WHERE action NOT IN ('Registrado', 'Ignorar / transferencia')
                        ORDER BY date, id
                        """
                    ).fetchall()
            self.send_json([rowdict(row) for row in rows])
        elif path == "/api/transactions":
            with db_connection() as conn:
                rows = conn.execute("SELECT * FROM transactions ORDER BY date DESC, id DESC").fetchall()
            self.send_json([rowdict(row) for row in rows])
        elif path == "/api/transactions/export":
            month = query.get("month", [datetime.now().strftime("%Y-%m")])[0]
            self.serve_transactions_export(month)
        elif path.startswith("/api/transactions/"):
            if path.endswith("/attachment"):
                transaction_id = int(path.split("/")[3])
                self.serve_transaction_attachment(transaction_id)
            else:
                transaction_id = int(path.rsplit("/", 1)[-1])
                with db_connection() as conn:
                    row = conn.execute("SELECT * FROM transactions WHERE id=?", (transaction_id,)).fetchone()
                if row is None:
                    self.send_error(404, "Movimiento no encontrado")
                else:
                    self.send_json(rowdict(row))
        elif path == "/api/monthly-control":
            month = query.get("month", [datetime.now().strftime("%Y-%m")])[0]
            self.send_json(build_monthly_control(month))
        elif path == "/api/dashboard":
            month = query.get("month", [datetime.now().strftime("%Y-%m")])[0]
            self.send_json(build_dashboard(month))
        elif path == "/api/sales/export":
            month = query.get("month", [datetime.now().strftime("%Y-%m")])[0]
            self.serve_sales_export(month)
        elif path == "/api/exchange-rate":
            self.send_json(fetch_usd_gtq_rate())
        elif path == "/api/wedding/state":
            self.send_json(build_wedding_state())
        elif path == "/api/wedding/export":
            self.serve_wedding_export()
        elif path.startswith("/api/wedding/expenses/") and path.endswith("/attachment"):
            expense_id = int(path.split("/")[4])
            self.serve_wedding_attachment(expense_id)
        elif path.startswith("/api/wedding/payments/") and path.endswith("/attachment"):
            payment_id = int(path.split("/")[4])
            self.serve_wedding_payment_attachment(payment_id)
        elif path == "/api/debts/state":
            self.send_json(build_debts_state())
        elif path == "/api/debts/export":
            self.serve_debts_export()
        elif path.startswith("/api/debts/payments/") and path.endswith("/attachment"):
            payment_id = int(path.split("/")[4])
            self.serve_debt_payment_attachment(payment_id)
        elif path.startswith("/api/debts/") and path.endswith("/transactions"):
            debt_id = int(path.split("/")[3])
            self.serve_debt_transactions(debt_id)
        elif path == "/api/ahorros/state":
            self.send_json(build_ahorros_state())
        elif path == "/api/ahorros/export":
            self.serve_ahorros_export()
        elif path == "/api/house/state":
            month = query.get("month", [datetime.now().strftime("%Y-%m")])[0]
            self.send_json(build_house_state(month))
        elif path == "/api/house/export":
            month = query.get("month", [datetime.now().strftime("%Y-%m")])[0]
            self.serve_house_export(month)
        elif path.startswith("/api/house/payments/") and path.endswith("/attachment"):
            payment_id = int(path.split("/")[4])
            self.serve_house_attachment(payment_id)
        elif path == "/api/recurring/state":
            month = query.get("month", [datetime.now().strftime("%Y-%m")])[0]
            self.send_json(build_recurring_state(month))
        elif path == "/api/reports":
            month = query.get("month", [datetime.now().strftime("%Y-%m")])[0]
            self.send_json(build_reports(month))
        elif path == "/api/reports/export":
            month = query.get("month", [datetime.now().strftime("%Y-%m")])[0]
            file_format = query.get("format", ["csv"])[0].lower()
            self.serve_report_export(month, file_format)
        else:
            self.send_error(404)

    def handle_import(self) -> None:
        fields, files = parse_multipart(self)
        bank = fields.get("bank", "GYT")
        account = fields.get("account", "GYT - Cuenta ahorro sueldo")
        product = fields.get("product") or infer_product(account)
        debt_id_raw = fields.get("debtId") or fields.get("debt_id")
        try:
            debt_id = int(debt_id_raw) if debt_id_raw not in (None, "") else None
        except (TypeError, ValueError):
            debt_id = None
        try:
            exchange_rate = float(fields.get("exchangeRate") or DEFAULT_USD_GTQ_RATE)
        except (TypeError, ValueError):
            exchange_rate = DEFAULT_USD_GTQ_RATE
        if exchange_rate <= 0:
            exchange_rate = DEFAULT_USD_GTQ_RATE
        if "file" not in files:
            self.send_error(400, "Falta archivo")
            return
        file = files["file"]
        name = file["filename"]
        data = file["data"]
        suffix = Path(name).suffix.lower()
        if suffix == ".pdf":
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(data)
                tmp_path = Path(tmp.name)
            try:
                rows = parse_pdf_upload(tmp_path, name, bank, product, account, exchange_rate)
            finally:
                tmp_path.unlink(missing_ok=True)
        else:
            rows = parse_csv_upload(data, name, bank, product, account)
        if not rows:
            self.send_error(
                422,
                "No se detectaron movimientos en el archivo. Proba exportarlo como CSV o compartime el formato del PDF para ajustar el lector.",
            )
            return
        for row in rows:
            row["debt_id"] = debt_id
        count = save_imports(rows)
        self.send_json({"ok": True, "count": count})

    def read_wedding_expense_payload(self) -> tuple[dict, dict | None]:
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            fields, files = parse_multipart(self)
            file = files.get("attachment")
            if file and not file.get("filename"):
                file = None
            return fields, file
        return self.read_json(), None

    def read_wedding_expense_create_payload(self) -> tuple[dict, dict | None, dict | None]:
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            fields, files = parse_multipart(self)
            file = files.get("attachment")
            if file and not file.get("filename"):
                file = None
            initial_payment_file = files.get("initialPaymentAttachment")
            if initial_payment_file and not initial_payment_file.get("filename"):
                initial_payment_file = None
            return fields, file, initial_payment_file
        return self.read_json(), None, None

    def read_transaction_payload(self) -> tuple[dict, dict | None]:
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            fields, files = parse_multipart(self)
            file = files.get("attachment")
            if file and not file.get("filename"):
                file = None
            return fields, file
        return self.read_json(), None

    def update_monthly_control(self, body: dict) -> None:
        month = str(body.get("month") or datetime.now().strftime("%Y-%m"))
        if not re.match(r"^\d{4}-\d{2}$", month):
            self.send_error(400, "Mes invalido")
            return
        try:
            amount = float(body.get("amount") or 0)
        except (TypeError, ValueError):
            self.send_error(400, "Monto invalido")
            return
        if amount < 0:
            self.send_error(400, "El monto no puede ser negativo")
            return
        updated_at = datetime.now().isoformat(timespec="seconds")
        with db_connection() as conn:
            updated = conn.execute(
                "UPDATE monthly_budgets SET amount = ?, updated_at = ? WHERE month = ?",
                (amount, updated_at, month),
            ).rowcount
            if not updated:
                conn.execute(
                    "INSERT INTO monthly_budgets (month, amount, updated_at) VALUES (?, ?, ?)",
                    (month, amount, updated_at),
                )
        self.send_json(build_monthly_control(month))
    def update_import(self, body: dict) -> None:
        allowed = {"suggested_type", "suggested_category", "account", "action", "notes"}
        updates = {k: v for k, v in body.items() if k in allowed}
        import_id = int(body["id"])
        if updates:
            assignments = ", ".join(f"{key}=?" for key in updates)
            with db_connection() as conn:
                conn.execute(f"UPDATE imports SET {assignments} WHERE id=?", [*updates.values(), import_id])
        self.send_json({"ok": True})

    def delete_transaction(self, transaction_id: int) -> None:
        with db_connection() as conn:
            row = conn.execute(
                "SELECT attachment_path, debt_id, type, amount FROM transactions WHERE id=?",
                (transaction_id,),
            ).fetchone()
            payment_row = conn.execute(
                "SELECT id, debt_id, amount, attachment_path FROM debt_payments WHERE transaction_id=?",
                (transaction_id,),
            ).fetchone()
            cursor = conn.execute("DELETE FROM transactions WHERE id=?", (transaction_id,))
            deltas: dict[int, float] = {}
            if row and row["debt_id"] is not None:
                deltas[row["debt_id"]] = deltas.get(row["debt_id"], 0) - self._debt_delta(row["type"], row["amount"])
            if payment_row:
                deltas[payment_row["debt_id"]] = deltas.get(payment_row["debt_id"], 0) + payment_row["amount"]
                conn.execute("DELETE FROM debt_payments WHERE id=?", (payment_row["id"],))
            self._adjust_debt_balances(conn, deltas)
        if cursor.rowcount == 0:
            self.send_error(404, "Movimiento no encontrado")
        else:
            delete_transaction_attachment(row["attachment_path"] if row else None)
            if payment_row:
                delete_debt_attachment(payment_row["attachment_path"])
            self.send_json({"ok": True})

    def delete_transactions(self, transaction_ids: list) -> None:
        ids = [int(item) for item in transaction_ids if str(item).isdigit()]
        if not ids:
            self.send_error(400, "No hay movimientos seleccionados")
            return
        placeholders = ",".join("?" for _ in ids)
        with db_connection() as conn:
            rows = conn.execute(
                f"SELECT attachment_path, debt_id, type, amount FROM transactions WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
            payment_rows = conn.execute(
                f"SELECT id, debt_id, amount, attachment_path FROM debt_payments WHERE transaction_id IN ({placeholders})",
                ids,
            ).fetchall()
            cursor = conn.execute(f"DELETE FROM transactions WHERE id IN ({placeholders})", ids)
            debt_deltas: dict[int, float] = {}
            for row in rows:
                if row["debt_id"] is None:
                    continue
                debt_deltas[row["debt_id"]] = debt_deltas.get(row["debt_id"], 0) - self._debt_delta(
                    row["type"], row["amount"]
                )
            for payment_row in payment_rows:
                debt_deltas[payment_row["debt_id"]] = debt_deltas.get(payment_row["debt_id"], 0) + payment_row["amount"]
            if payment_rows:
                payment_placeholders = ",".join("?" for _ in payment_rows)
                conn.execute(
                    f"DELETE FROM debt_payments WHERE id IN ({payment_placeholders})",
                    [p["id"] for p in payment_rows],
                )
            self._adjust_debt_balances(conn, debt_deltas)
        for row in rows:
            delete_transaction_attachment(row["attachment_path"])
        for payment_row in payment_rows:
            delete_debt_attachment(payment_row["attachment_path"])
        self.send_json({"ok": True, "count": cursor.rowcount})

    @staticmethod
    def _debt_delta(tx_type: str, amount: float) -> float:
        """Effect on a debt's current_balance from adding this transaction."""
        amount = float(amount or 0)
        if tx_type == "Gasto":
            return amount
        if tx_type in ("Transferencia", "Ingreso"):
            return -amount
        return 0

    @staticmethod
    def _adjust_debt_balances(conn: sqlite3.Connection, deltas: dict[int, float]) -> None:
        for debt_id, delta in deltas.items():
            if not delta:
                continue
            debt = conn.execute("SELECT current_balance FROM debts WHERE id=?", (debt_id,)).fetchone()
            if debt:
                new_balance = max(float(debt["current_balance"] or 0) + delta, 0)
                conn.execute("UPDATE debts SET current_balance=? WHERE id=?", (new_balance, debt_id))

    def update_transaction(self, transaction_id: int, body: dict) -> None:
        tx_type = body.get("type", "Gasto")
        amount = float(body.get("amount") or 0)
        if amount <= 0:
            self.send_error(400, "El monto debe ser mayor a cero")
            return
        with db_connection() as conn:
            old_row = conn.execute(
                "SELECT debt_id, ahorro_id, type, amount, usd_amount FROM transactions WHERE id=?",
                (transaction_id,),
            ).fetchone()
            if tx_type == "Ahorro" and not (old_row and old_row["ahorro_id"] is not None):
                # "Ahorro" solo es valido si la transaccion ya esta vinculada a un ahorro
                # (creada desde ese modulo); de lo contrario se reclasifica para no dejar
                # un movimiento "ahorrado" que no aparece en ninguna cuenta de Ahorros.
                tx_type = "Transferencia"
            account = body.get("account", "Otro")
            category = body.get("category") or default_category_for_type(tx_type, account)
            description = (body.get("description", "").strip() or "Movimiento manual")[:75]
            date = normalize_date(body.get("date", datetime.now().strftime("%Y-%m-%d")))
            usd_amount = body.get("usdAmount")
            exchange_rate = body.get("exchangeRate")
            usd_amount_value = float(usd_amount) if usd_amount else None
            if tx_type == "Venta USD":
                details = []
                if usd_amount:
                    details.append(f"USD {usd_amount}")
                if exchange_rate:
                    details.append(f"TC {exchange_rate}")
                if details and "(" not in description:
                    description = f"{description} ({', '.join(details)})"
                if not usd_amount and old_row:
                    usd_amount_value = old_row["usd_amount"]
            else:
                usd_amount_value = None
            description = description[:75]
            cursor = conn.execute(
                """
                UPDATE transactions
                SET date=?, type=?, category=?, description=?, account=?, amount=?, usd_amount=?
                WHERE id=?
                """,
                (date, tx_type, category, description, account, amount, usd_amount_value, transaction_id),
            )
            if cursor.rowcount and old_row and old_row["debt_id"] is not None:
                old_delta = self._debt_delta(old_row["type"], old_row["amount"])
                new_delta = self._debt_delta(tx_type, amount)
                self._adjust_debt_balances(conn, {old_row["debt_id"]: new_delta - old_delta})
        if cursor.rowcount == 0:
            self.send_error(404, "Movimiento no encontrado")
        else:
            self.send_json({"ok": True})

    def create_transaction(self, body: dict, file: dict | None = None) -> None:
        tx_type = body.get("type", "Gasto")
        if tx_type == "Ahorro":
            # "Ahorro" solo se crea desde el modulo de Ahorros (vincula ahorro_id);
            # por este endpoint generico se reclasifica para no dejar un movimiento huerfano.
            tx_type = "Transferencia"
        account = body.get("account", "Otro")
        category = body.get("category") or default_category_for_type(tx_type, account)
        description = (body.get("description", "").strip() or "Movimiento manual")[:75]
        amount = float(body.get("amount") or 0)
        date = normalize_date(body.get("date", datetime.now().strftime("%Y-%m-%d")))
        if amount <= 0:
            self.send_error(400, "El monto debe ser mayor a cero")
            return
        usd_amount = body.get("usdAmount")
        exchange_rate = body.get("exchangeRate")
        usd_amount_value = float(usd_amount) if usd_amount and tx_type == "Venta USD" else None
        if tx_type == "Venta USD":
            details = []
            if usd_amount:
                details.append(f"USD {usd_amount}")
            if exchange_rate:
                details.append(f"TC {exchange_rate}")
            if details:
                description = f"{description} ({', '.join(details)})"
        description = description[:75]
        now = datetime.now().isoformat(timespec="seconds")
        with db_connection() as conn:
            ahorro_id = None
            if tx_type == "Venta USD" and account == SAVINGS_ACCOUNT:
                # La venta de USD depositada en Banrural es, en la practica, un
                # movimiento de esa cuenta de ahorro: se vincula igual que "Ahorro"
                # para que build_dashboard/build_reports la excluyan de los totales
                # y quede junto al resto de savingsTransactions.
                ahorro = conn.execute(
                    "SELECT id FROM ahorros WHERE type='Ahorro' AND account=?", (SAVINGS_ACCOUNT,)
                ).fetchone()
                if ahorro:
                    ahorro_id = ahorro["id"]
            cursor = conn.execute(
                """
                INSERT INTO transactions
                (date, type, category, description, account, amount, usd_amount, source_import_id, ahorro_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (date, tx_type, category, description, account, amount, usd_amount_value, ahorro_id, now),
            )
            transaction_id = cursor.lastrowid
            if file:
                try:
                    filename, file_path, mime = save_transaction_attachment(transaction_id, file)
                except ValueError as exc:
                    self.send_error(400, str(exc))
                    return
                conn.execute(
                    """
                    UPDATE transactions
                    SET attachment_name=?, attachment_path=?, attachment_mime=?
                    WHERE id=?
                    """,
                    (filename, str(file_path.relative_to(DATA)), mime, transaction_id),
                )
        self.send_json({"ok": True, "id": transaction_id})

    def commit_imports(self, body: dict | None = None) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        debt_id_raw = (body or {}).get("debtId")
        try:
            debt_id = int(debt_id_raw) if debt_id_raw not in (None, "") else None
        except (TypeError, ValueError):
            debt_id = None
        with db_connection() as conn:
            if debt_id is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM imports
                    WHERE action NOT IN ('Registrado', 'Ignorar / transferencia')
                      AND debt_id = ?
                    ORDER BY date, id
                    """,
                    (debt_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM imports
                    WHERE action NOT IN ('Registrado', 'Ignorar / transferencia')
                    ORDER BY date, id
                    """
                ).fetchall()
            debt_balance_deltas: dict[int, float] = {}
            existing_counts: dict[tuple, int] = {}
            seen_counts: dict[tuple, int] = {}
            for row in rows:
                tx_type = row["suggested_type"]
                if tx_type == "Ahorro":
                    # Los movimientos importados nunca quedan vinculados a un ahorro_id;
                    # reclasificar para no dejar un "Ahorro" fantasma fuera del modulo de Ahorros.
                    tx_type = "Transferencia"
                key = (row["date"], tx_type, row["suggested_category"], row["account"], row["description"], row["amount"])
                if key not in existing_counts:
                    # Cuantas transacciones con esta misma forma ya existian ANTES de este commit.
                    # Solo esas cuentan como duplicado real; dos filas nuevas identicas en el mismo
                    # lote (ej. dos "DEBITO ACH" del mismo dia y monto) son movimientos distintos.
                    count_row = conn.execute(
                        """
                        SELECT COUNT(*) FROM transactions
                        WHERE date=? AND type=? AND category=? AND account=? AND description=? AND amount=?
                        """,
                        key,
                    ).fetchone()
                    existing_counts[key] = count_row[0]
                seen_counts[key] = seen_counts.get(key, 0) + 1
                if seen_counts[key] <= existing_counts[key]:
                    conn.execute("UPDATE imports SET action='Registrado' WHERE id=?", (row["id"],))
                    continue
                conn.execute(
                    """
                    INSERT INTO transactions
                    (date, type, category, description, account, amount, source_import_id, debt_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["date"],
                        tx_type,
                        row["suggested_category"],
                        row["description"],
                        row["account"],
                        row["amount"],
                        row["id"],
                        row["debt_id"],
                        now,
                    ),
                )
                conn.execute("UPDATE imports SET action='Registrado' WHERE id=?", (row["id"],))
                if row["debt_id"] is not None:
                    delta = self._debt_delta(tx_type, row["amount"])
                    debt_balance_deltas[row["debt_id"]] = debt_balance_deltas.get(row["debt_id"], 0) + delta
            self._adjust_debt_balances(conn, debt_balance_deltas)
        month = rows[0]["date"][:7] if rows else None
        self.send_json({"ok": True, "count": len(rows), "month": month})

    def recurring_values(self, body: dict) -> tuple:
        name = (body.get("name", "").strip())[:90]
        category = body.get("category") or "Otro"
        account = body.get("account") or "Otro"
        amount = float(body.get("amount") or 0)
        frequency = body.get("frequency") or "Mensual"
        next_due_date = body.get("nextDueDate") or None
        active = 1 if str(body.get("active", "1")).lower() in ("1", "true", "activo", "on") else 0
        if not name:
            raise ValueError("Escribe el nombre del gasto")
        if amount <= 0:
            raise ValueError("El monto debe ser mayor a cero")
        if frequency not in ("Mensual", "Anual"):
            raise ValueError("La frecuencia debe ser mensual o anual")
        if next_due_date:
            next_due_date = normalize_date(next_due_date)
        return name, category, account, amount, frequency, next_due_date, active

    def create_recurring_expense(self, body: dict) -> None:
        try:
            values = self.recurring_values(body)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        with db_connection() as conn:
            conn.execute(
                """
                INSERT INTO recurring_expenses
                (name, category, account, amount, frequency, next_due_date, active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*values, datetime.now().isoformat(timespec="seconds")),
            )
        self.send_json(build_recurring_state(body.get("month", "")), status=201)

    def update_recurring_expense(self, expense_id: int, body: dict) -> None:
        try:
            values = self.recurring_values(body)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        with db_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE recurring_expenses
                SET name=?, category=?, account=?, amount=?, frequency=?, next_due_date=?, active=?
                WHERE id=?
                """,
                (*values, expense_id),
            )
        if cursor.rowcount == 0:
            self.send_error(404, "Gasto recurrente no encontrado")
            return
        self.send_json(build_recurring_state(body.get("month", "")))

    def toggle_recurring_paid(self, expense_id: int, body: dict) -> None:
        month = body.get("month") or datetime.now().strftime("%Y-%m")
        if not re.match(r"^\d{4}-\d{2}$", month):
            self.send_error(400, "Mes invalido")
            return
        with db_connection() as conn:
            exists = conn.execute(
                "SELECT id FROM recurring_expenses WHERE id=?",
                (expense_id,),
            ).fetchone()
            if not exists:
                self.send_error(404, "Gasto recurrente no encontrado")
                return
            paid = conn.execute(
                "SELECT id FROM recurring_payments WHERE recurring_expense_id=? AND month=?",
                (expense_id, month),
            ).fetchone()
            if paid:
                conn.execute("DELETE FROM recurring_payments WHERE id=?", (paid["id"],))
            else:
                conn.execute(
                    "INSERT INTO recurring_payments (recurring_expense_id, month) VALUES (?, ?)",
                    (expense_id, month),
                )
        self.send_json(build_recurring_state(month))

    def delete_recurring_expense(self, expense_id: int) -> None:
        with db_connection() as conn:
            conn.execute("DELETE FROM recurring_payments WHERE recurring_expense_id=?", (expense_id,))
            cursor = conn.execute("DELETE FROM recurring_expenses WHERE id=?", (expense_id,))
        if cursor.rowcount == 0:
            self.send_error(404, "Gasto recurrente no encontrado")
            return
        self.send_json({"ok": True})

    def update_wedding_budget(self, body: dict) -> None:
        budget = float(body.get("budget") or 0)
        with db_connection() as conn:
            conn.execute(
                """
                INSERT INTO wedding_settings (key, value)
                VALUES ('budget', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(budget),),
            )
        self.send_json(build_wedding_state())

    def create_house_payment(self, body: dict, file: dict | None = None) -> None:
        amount = float(body.get("amount") or 0)
        if amount <= 0:
            self.send_error(400, "El monto debe ser mayor a cero")
            return
        description = (body.get("description", "").strip() or "Pago de la casa")[:90]
        payment_date = normalize_date(body.get("paymentDate") or body.get("date") or datetime.now().strftime("%Y-%m-%d"))
        now = datetime.now().isoformat(timespec="seconds")
        with db_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO house_payments
                (payment_date, description, amount, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (payment_date, description, amount, now),
            )
            payment_id = cursor.lastrowid
            if file:
                try:
                    filename, file_path, mime = save_house_attachment(payment_id, file)
                except ValueError as exc:
                    conn.rollback()
                    self.send_error(400, str(exc))
                    return
                conn.execute(
                    """
                    UPDATE house_payments
                    SET attachment_name=?, attachment_path=?, attachment_mime=?
                    WHERE id=?
                    """,
                    (filename, str(file_path.relative_to(DATA)), mime, payment_id),
                )
        self.send_json(build_house_state(payment_date[:7]), status=201)

    def update_house_attachment(self, payment_id: int, file: dict | None) -> None:
        if not file:
            self.send_error(400, "Debes seleccionar un archivo PDF o imagen")
            return
        with db_connection() as conn:
            existing = conn.execute(
                "SELECT payment_date, attachment_path FROM house_payments WHERE id=?",
                (payment_id,),
            ).fetchone()
            if not existing:
                self.send_error(404, "Pago de casa no encontrado")
                return
            try:
                filename, file_path, mime = save_house_attachment(payment_id, file)
            except ValueError as exc:
                self.send_error(400, str(exc))
                return
            relative_path = str(file_path.relative_to(DATA))
            conn.execute(
                """
                UPDATE house_payments
                SET attachment_name=?, attachment_path=?, attachment_mime=?
                WHERE id=?
                """,
                (filename, relative_path, mime, payment_id),
            )
        if existing["attachment_path"] != relative_path:
            delete_house_attachment(existing["attachment_path"])
        self.send_json(build_house_state(existing["payment_date"][:7]))

    def delete_house_payment(self, payment_id: int) -> None:
        with db_connection() as conn:
            row = conn.execute(
                "SELECT attachment_path FROM house_payments WHERE id=?",
                (payment_id,),
            ).fetchone()
            cursor = conn.execute("DELETE FROM house_payments WHERE id=?", (payment_id,))
        if cursor.rowcount == 0:
            self.send_error(404, "Pago de casa no encontrado")
        else:
            delete_house_attachment(row["attachment_path"] if row else None)
            self.send_json({"ok": True})

    def create_wedding_expense(
        self, body: dict, file: dict | None = None, initial_payment_file: dict | None = None
    ) -> None:
        amount = float(body.get("amount") or 0)
        initial_payment = float(body.get("initialPayment") or 0)
        if amount <= 0:
            self.send_error(400, "El monto debe ser mayor a cero")
            return
        if initial_payment > amount:
            self.send_error(400, "El abono inicial no puede ser mayor al monto del gasto")
            return
        description = (body.get("description", "").strip() or "Gasto de boda")[:90]
        category = body.get("category") or "Otro"
        vendor = (body.get("vendor", "").strip())[:90]
        date = normalize_date(body.get("date") or datetime.now().strftime("%Y-%m-%d"))
        payment_date = normalize_date(body.get("paymentDate") or date)
        now = datetime.now().isoformat(timespec="seconds")
        with db_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO wedding_expenses
                (date, description, category, vendor, amount, legacy_id, created_at)
                VALUES (?, ?, ?, ?, ?, NULL, ?)
                """,
                (date, description, category, vendor, amount, now),
            )
            expense_id = cursor.lastrowid
            if file:
                try:
                    filename, file_path, mime = save_wedding_attachment(expense_id, file)
                except ValueError as exc:
                    conn.rollback()
                    self.send_error(400, str(exc))
                    return
                conn.execute(
                    """
                    UPDATE wedding_expenses
                    SET attachment_name=?, attachment_path=?, attachment_mime=?
                    WHERE id=?
                    """,
                    (filename, str(file_path.relative_to(DATA)), mime, expense_id),
                )
            if initial_payment > 0:
                payment_cursor = conn.execute(
                    """
                    INSERT INTO wedding_payments
                    (expense_id, date, amount, note, legacy_id, created_at)
                    VALUES (?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        expense_id,
                        payment_date,
                        min(initial_payment, amount),
                        "Abono inicial",
                        now,
                    ),
                )
                if initial_payment_file:
                    payment_id = payment_cursor.lastrowid
                    try:
                        payment_filename, payment_file_path, payment_mime = save_wedding_payment_attachment(
                            payment_id, initial_payment_file
                        )
                    except ValueError as exc:
                        conn.rollback()
                        self.send_error(400, str(exc))
                        return
                    conn.execute(
                        """
                        UPDATE wedding_payments
                        SET attachment_name=?, attachment_path=?, attachment_mime=?
                        WHERE id=?
                        """,
                        (payment_filename, str(payment_file_path.relative_to(DATA)), payment_mime, payment_id),
                    )
        self.send_json(build_wedding_state(), status=201)

    def update_wedding_expense(self, expense_id: int, body: dict) -> None:
        amount = float(body.get("amount") or 0)
        if amount <= 0:
            self.send_error(400, "El monto debe ser mayor a cero")
            return
        description = (body.get("description", "").strip() or "Gasto de boda")[:90]
        category = body.get("category") or "Otro"
        vendor = (body.get("vendor", "").strip())[:90]
        date = normalize_date(body.get("date") or datetime.now().strftime("%Y-%m-%d"))
        with db_connection() as conn:
            paid_so_far = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM wedding_payments WHERE expense_id=?",
                (expense_id,),
            ).fetchone()[0]
            if amount < paid_so_far:
                self.send_error(
                    400,
                    f"El monto no puede ser menor a lo ya abonado (Q{paid_so_far:.2f})",
                )
                return
            cursor = conn.execute(
                """
                UPDATE wedding_expenses
                SET date=?, description=?, category=?, vendor=?, amount=?
                WHERE id=?
                """,
                (date, description, category, vendor, amount, expense_id),
            )
        if cursor.rowcount == 0:
            self.send_error(404, "Gasto de boda no encontrado")
            return
        self.send_json(build_wedding_state())

    def create_wedding_payment(self, expense_id: int, body: dict, file: dict | None = None) -> None:
        amount = float(body.get("amount") or 0)
        if amount <= 0:
            self.send_error(400, "El abono debe ser mayor a cero")
            return
        date = normalize_date(body.get("date", datetime.now().strftime("%Y-%m-%d")))
        note = (body.get("note", "").strip())[:90]
        now = datetime.now().isoformat(timespec="seconds")
        with db_connection() as conn:
            expense = conn.execute("SELECT amount FROM wedding_expenses WHERE id=?", (expense_id,)).fetchone()
            if not expense:
                self.send_error(404, "Gasto de boda no encontrado")
                return
            paid_so_far = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM wedding_payments WHERE expense_id=?",
                (expense_id,),
            ).fetchone()[0]
            pending = float(expense["amount"]) - float(paid_so_far)
            if amount > pending:
                self.send_error(400, f"El abono excede el monto pendiente (Q{max(pending, 0):.2f})")
                return
            cursor = conn.execute(
                """
                INSERT INTO wedding_payments
                (expense_id, date, amount, note, legacy_id, created_at)
                VALUES (?, ?, ?, ?, NULL, ?)
                """,
                (expense_id, date, amount, note, now),
            )
            if file:
                payment_id = cursor.lastrowid
                try:
                    filename, file_path, mime = save_wedding_payment_attachment(payment_id, file)
                except ValueError as exc:
                    conn.rollback()
                    self.send_error(400, str(exc))
                    return
                conn.execute(
                    """
                    UPDATE wedding_payments
                    SET attachment_name=?, attachment_path=?, attachment_mime=?
                    WHERE id=?
                    """,
                    (filename, str(file_path.relative_to(DATA)), mime, payment_id),
                )
        self.send_json(build_wedding_state(), status=201)

    def update_wedding_payment_attachment(self, payment_id: int, file: dict | None) -> None:
        if not file:
            self.send_error(400, "Debes seleccionar un archivo PDF o imagen")
            return
        with db_connection() as conn:
            existing = conn.execute(
                "SELECT attachment_path FROM wedding_payments WHERE id=?",
                (payment_id,),
            ).fetchone()
            if not existing:
                self.send_error(404, "Abono no encontrado")
                return
            try:
                filename, file_path, mime = save_wedding_payment_attachment(payment_id, file)
            except ValueError as exc:
                self.send_error(400, str(exc))
                return
            relative_path = str(file_path.relative_to(DATA))
            conn.execute(
                """
                UPDATE wedding_payments
                SET attachment_name=?, attachment_path=?, attachment_mime=?
                WHERE id=?
                """,
                (filename, relative_path, mime, payment_id),
            )
        if existing["attachment_path"] != relative_path:
            delete_wedding_attachment(existing["attachment_path"])
        self.send_json(build_wedding_state())

    def update_wedding_attachment(self, expense_id: int, file: dict | None) -> None:
        if not file:
            self.send_error(400, "Debes seleccionar un archivo PDF o imagen")
            return
        with db_connection() as conn:
            existing = conn.execute(
                "SELECT attachment_path FROM wedding_expenses WHERE id=?",
                (expense_id,),
            ).fetchone()
            if not existing:
                self.send_error(404, "Gasto de boda no encontrado")
                return
            try:
                filename, file_path, mime = save_wedding_attachment(expense_id, file)
            except ValueError as exc:
                self.send_error(400, str(exc))
                return
            relative_path = str(file_path.relative_to(DATA))
            conn.execute(
                """
                UPDATE wedding_expenses
                SET attachment_name=?, attachment_path=?, attachment_mime=?
                WHERE id=?
                """,
                (filename, relative_path, mime, expense_id),
            )
        if existing["attachment_path"] != relative_path:
            delete_wedding_attachment(existing["attachment_path"])
        self.send_json(build_wedding_state())

    def update_transaction_attachment(self, transaction_id: int, file: dict | None) -> None:
        if not file:
            self.send_error(400, "Debes seleccionar un archivo PDF o imagen")
            return
        with db_connection() as conn:
            existing = conn.execute(
                "SELECT attachment_path FROM transactions WHERE id=?",
                (transaction_id,),
            ).fetchone()
            if not existing:
                self.send_error(404, "Movimiento no encontrado")
                return
            try:
                filename, file_path, mime = save_transaction_attachment(transaction_id, file)
            except ValueError as exc:
                self.send_error(400, str(exc))
                return
            relative_path = str(file_path.relative_to(DATA))
            conn.execute(
                """
                UPDATE transactions
                SET attachment_name=?, attachment_path=?, attachment_mime=?
                WHERE id=?
                """,
                (filename, relative_path, mime, transaction_id),
            )
        if existing["attachment_path"] != relative_path:
            delete_transaction_attachment(existing["attachment_path"])
        self.send_json({"ok": True})

    def delete_wedding_expense(self, expense_id: int) -> None:
        with db_connection() as conn:
            row = conn.execute(
                "SELECT attachment_path FROM wedding_expenses WHERE id=?",
                (expense_id,),
            ).fetchone()
            payment_rows = conn.execute(
                "SELECT attachment_path FROM wedding_payments WHERE expense_id=?",
                (expense_id,),
            ).fetchall()
            conn.execute("DELETE FROM wedding_payments WHERE expense_id=?", (expense_id,))
            cursor = conn.execute("DELETE FROM wedding_expenses WHERE id=?", (expense_id,))
        if cursor.rowcount == 0:
            self.send_error(404, "Gasto de boda no encontrado")
        else:
            delete_wedding_attachment(row["attachment_path"] if row else None)
            for payment_row in payment_rows:
                delete_wedding_attachment(payment_row["attachment_path"])
            self.send_json({"ok": True})

    def _debt_fields_from_body(self, body: dict) -> dict:
        debt_type = body.get("type") or DEBT_TYPES[0]
        if debt_type not in DEBT_TYPES:
            debt_type = DEBT_TYPES[0]
        name = (body.get("name", "").strip() or "Deuda")[:90]
        is_card = debt_type == "Tarjeta de credito"
        is_loan = debt_type == "Prestamo"
        is_other = debt_type == "Otro pago"
        bank = (body.get("bank") or DEBT_BANKS[0]) if (is_card or is_loan) else ""
        start_date_raw = body.get("startDate")
        end_date_raw = body.get("endDate")
        return {
            "type": debt_type,
            "name": name,
            "bank": bank,
            "credit_limit": optional_float(body.get("creditLimit")) if is_card else None,
            "credit_limit_usd": optional_float(body.get("creditLimitUsd")) if is_card else None,
            "original_amount": optional_float(body.get("originalAmount")) if (is_loan or is_other) else None,
            "interest_rate": optional_float(body.get("interestRate")) if is_loan else None,
            "statement_day": optional_day(body.get("statementDay")) if is_card else None,
            "due_day": optional_day(body.get("dueDay")) if (is_card or is_loan) else None,
            "monthly_payment": optional_float(body.get("monthlyPayment")) if is_loan else None,
            "start_date": normalize_date(start_date_raw) if (is_loan and start_date_raw) else None,
            "end_date": normalize_date(end_date_raw) if ((is_loan or is_other) and end_date_raw) else None,
        }

    def create_debt(self, body: dict) -> None:
        fields = self._debt_fields_from_body(body)
        is_card = fields["type"] == "Tarjeta de credito"
        initial_balance = 0.0 if is_card else (fields["original_amount"] or 0.0)
        initial_balance_usd = 0.0 if is_card else None
        now = datetime.now().isoformat(timespec="seconds")
        with db_connection() as conn:
            conn.execute(
                """
                INSERT INTO debts
                (type, name, bank, current_balance, credit_limit, credit_limit_usd, original_amount,
                 interest_rate, statement_day, due_day, monthly_payment, balance_usd, start_date, end_date, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fields["type"], fields["name"], fields["bank"], initial_balance,
                    fields["credit_limit"], fields["credit_limit_usd"], fields["original_amount"],
                    fields["interest_rate"], fields["statement_day"], fields["due_day"],
                    fields["monthly_payment"], initial_balance_usd, fields["start_date"], fields["end_date"], now,
                ),
            )
        self.send_json(build_debts_state(), status=201)

    def update_debt(self, debt_id: int, body: dict) -> None:
        fields = self._debt_fields_from_body(body)
        is_card = fields["type"] == "Tarjeta de credito"
        with db_connection() as conn:
            existing = conn.execute(
                "SELECT original_amount, current_balance FROM debts WHERE id=?", (debt_id,)
            ).fetchone()
            if not existing:
                self.send_error(404, "Deuda no encontrada")
                return
            balance_clause = ""
            params = [
                fields["type"], fields["name"], fields["bank"], fields["credit_limit"], fields["credit_limit_usd"],
                fields["original_amount"], fields["interest_rate"], fields["statement_day"], fields["due_day"],
                fields["monthly_payment"], fields["start_date"], fields["end_date"],
            ]
            if not is_card:
                # Re-sincroniza el saldo pendiente cuando se corrige el monto, preservando lo ya abonado.
                paid = max(float(existing["original_amount"] or 0) - float(existing["current_balance"] or 0), 0)
                new_balance = max(float(fields["original_amount"] or 0) - paid, 0)
                balance_clause = ", current_balance=?"
                params.append(new_balance)
            params.append(debt_id)
            cursor = conn.execute(
                f"""
                UPDATE debts SET type=?, name=?, bank=?, credit_limit=?, credit_limit_usd=?,
                  original_amount=?, interest_rate=?, statement_day=?, due_day=?, monthly_payment=?,
                  start_date=?, end_date=?{balance_clause}
                WHERE id=?
                """,
                params,
            )
        if cursor.rowcount == 0:
            self.send_error(404, "Deuda no encontrada")
            return
        self.send_json(build_debts_state())

    def delete_debt(self, debt_id: int) -> None:
        with db_connection() as conn:
            payment_rows = conn.execute(
                "SELECT attachment_path, transaction_id FROM debt_payments WHERE debt_id=?",
                (debt_id,),
            ).fetchall()
            transaction_ids = [row["transaction_id"] for row in payment_rows if row["transaction_id"] is not None]
            if transaction_ids:
                placeholders = ",".join("?" * len(transaction_ids))
                conn.execute(f"DELETE FROM transactions WHERE id IN ({placeholders})", transaction_ids)
            conn.execute("DELETE FROM transactions WHERE debt_id=?", (debt_id,))
            conn.execute("DELETE FROM imports WHERE debt_id=?", (debt_id,))
            conn.execute("DELETE FROM debt_payments WHERE debt_id=?", (debt_id,))
            cursor = conn.execute("DELETE FROM debts WHERE id=?", (debt_id,))
        if cursor.rowcount == 0:
            self.send_error(404, "Deuda no encontrada")
        else:
            for row in payment_rows:
                delete_debt_attachment(row["attachment_path"])
            self.send_json({"ok": True})

    def create_debt_payment(self, debt_id: int, body: dict, file: dict | None = None) -> None:
        amount = optional_float(body.get("amount")) or 0
        if amount <= 0:
            self.send_error(400, "El abono debe ser mayor a cero")
            return
        date = normalize_date(body.get("date", datetime.now().strftime("%Y-%m-%d")))
        note = (body.get("note", "").strip())[:90]
        origin_account = body.get("originAccount") or None
        now = datetime.now().isoformat(timespec="seconds")
        with db_connection() as conn:
            debt = conn.execute("SELECT id, name, current_balance FROM debts WHERE id=?", (debt_id,)).fetchone()
            if not debt:
                self.send_error(404, "Deuda no encontrada")
                return
            transaction_id = None
            if origin_account:
                tx_cursor = conn.execute(
                    """
                    INSERT INTO transactions
                    (date, type, category, description, account, amount, source_import_id, created_at)
                    VALUES (?, 'Transferencia', ?, ?, ?, ?, NULL, ?)
                    """,
                    (date, DEBT_PAYMENT_CATEGORY, f"Pago {debt['name']}"[:75], origin_account, amount, now),
                )
                transaction_id = tx_cursor.lastrowid
            cursor = conn.execute(
                """
                INSERT INTO debt_payments (debt_id, date, amount, note, origin_account, transaction_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (debt_id, date, amount, note, origin_account, transaction_id, now),
            )
            new_balance = max(float(debt["current_balance"] or 0) - amount, 0)
            conn.execute("UPDATE debts SET current_balance=? WHERE id=?", (new_balance, debt_id))
            if file:
                payment_id = cursor.lastrowid
                try:
                    filename, file_path, mime = save_debt_payment_attachment(payment_id, file)
                except ValueError as exc:
                    self.send_error(400, str(exc))
                    return
                conn.execute(
                    """
                    UPDATE debt_payments
                    SET attachment_name=?, attachment_path=?, attachment_mime=?
                    WHERE id=?
                    """,
                    (filename, str(file_path.relative_to(DATA)), mime, payment_id),
                )
        self.send_json(build_debts_state(), status=201)

    def _ahorro_fields_from_body(self, body: dict) -> dict | None:
        ahorro_type = body.get("type") or AHORRO_TYPES[0]
        if ahorro_type not in AHORRO_TYPES:
            ahorro_type = AHORRO_TYPES[0]
        name = (body.get("name", "").strip() or "Ahorro")[:90]
        bank = body.get("bank") or DEBT_BANKS[0]
        account = body.get("account") or ACCOUNTS[0]
        initial_balance = optional_float(body.get("initialBalance")) or 0
        monthly_target = optional_float(body.get("monthlyTarget")) or 0
        return {
            "type": ahorro_type, "name": name, "bank": bank, "account": account,
            "initial_balance": initial_balance, "monthly_target": monthly_target,
        }

    def create_ahorro(self, body: dict) -> None:
        fields = self._ahorro_fields_from_body(body)
        now = datetime.now().isoformat(timespec="seconds")
        with db_connection() as conn:
            conn.execute(
                """
                INSERT INTO ahorros (type, name, bank, account, initial_balance, monthly_target, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fields["type"], fields["name"], fields["bank"], fields["account"],
                    fields["initial_balance"], fields["monthly_target"], now,
                ),
            )
        self.send_json(build_ahorros_state(), status=201)

    def update_ahorro(self, ahorro_id: int, body: dict) -> None:
        fields = self._ahorro_fields_from_body(body)
        with db_connection() as conn:
            existing = conn.execute("SELECT type FROM ahorros WHERE id=?", (ahorro_id,)).fetchone()
            if not existing:
                self.send_error(404, "Ahorro no encontrado")
                return
            if existing["type"] != fields["type"]:
                has_movements = conn.execute(
                    "SELECT 1 FROM transactions WHERE ahorro_id=? LIMIT 1", (ahorro_id,)
                ).fetchone()
                if has_movements:
                    self.send_error(
                        400,
                        "No se puede cambiar el tipo de un ahorro que ya tiene movimientos registrados",
                    )
                    return
            cursor = conn.execute(
                "UPDATE ahorros SET type=?, name=?, bank=?, account=?, initial_balance=?, monthly_target=? WHERE id=?",
                (
                    fields["type"], fields["name"], fields["bank"], fields["account"],
                    fields["initial_balance"], fields["monthly_target"], ahorro_id,
                ),
            )
        if cursor.rowcount == 0:
            self.send_error(404, "Ahorro no encontrado")
            return
        self.send_json(build_ahorros_state())

    def delete_ahorro(self, ahorro_id: int) -> None:
        with db_connection() as conn:
            tx_rows = conn.execute(
                "SELECT attachment_path FROM transactions WHERE ahorro_id=?", (ahorro_id,)
            ).fetchall()
            conn.execute("DELETE FROM transactions WHERE ahorro_id=?", (ahorro_id,))
            cursor = conn.execute("DELETE FROM ahorros WHERE id=?", (ahorro_id,))
        if cursor.rowcount == 0:
            self.send_error(404, "Ahorro no encontrado")
        else:
            for row in tx_rows:
                delete_transaction_attachment(row["attachment_path"])
            self.send_json({"ok": True})

    def create_ahorro_movement(self, ahorro_id: int, body: dict, file: dict | None = None) -> None:
        amount = optional_float(body.get("amount")) or 0
        if amount <= 0:
            self.send_error(400, "El monto debe ser mayor a cero")
            return
        direction = body.get("direction") or "Entrada"
        date = normalize_date(body.get("date", datetime.now().strftime("%Y-%m-%d")))
        now = datetime.now().isoformat(timespec="seconds")
        with db_connection() as conn:
            ahorro = conn.execute("SELECT id, type, account FROM ahorros WHERE id=?", (ahorro_id,)).fetchone()
            if not ahorro:
                self.send_error(404, "Ahorro no encontrado")
                return
            if ahorro["type"] == "Fondo":
                tx_type = "Transferencia"
                category = FUND_CATEGORY
                description = (body.get("description", "").strip() or "Aporte a fondo")[:75]
            else:
                tx_type = "Ahorro" if direction == "Entrada" else "Gasto"
                category = AHORRO_CATEGORY_IN if direction == "Entrada" else AHORRO_CATEGORY_OUT
                description = (body.get("description", "").strip() or "Movimiento de ahorro")[:75]
            cursor = conn.execute(
                """
                INSERT INTO transactions
                (date, type, category, description, account, amount, source_import_id, ahorro_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (date, tx_type, category, description, ahorro["account"], amount, ahorro_id, now),
            )
            if file:
                transaction_id = cursor.lastrowid
                try:
                    filename, file_path, mime = save_transaction_attachment(transaction_id, file)
                except ValueError as exc:
                    self.send_error(400, str(exc))
                    return
                conn.execute(
                    """
                    UPDATE transactions
                    SET attachment_name=?, attachment_path=?, attachment_mime=?
                    WHERE id=?
                    """,
                    (filename, str(file_path.relative_to(DATA)), mime, transaction_id),
                )
        self.send_json(build_ahorros_state(), status=201)

    def update_debt_payment_attachment(self, payment_id: int, file: dict | None) -> None:
        if not file:
            self.send_error(400, "Debes seleccionar un archivo PDF o imagen")
            return
        with db_connection() as conn:
            existing = conn.execute(
                "SELECT attachment_path FROM debt_payments WHERE id=?",
                (payment_id,),
            ).fetchone()
            if not existing:
                self.send_error(404, "Abono no encontrado")
                return
            try:
                filename, file_path, mime = save_debt_payment_attachment(payment_id, file)
            except ValueError as exc:
                self.send_error(400, str(exc))
                return
            relative_path = str(file_path.relative_to(DATA))
            conn.execute(
                """
                UPDATE debt_payments
                SET attachment_name=?, attachment_path=?, attachment_mime=?
                WHERE id=?
                """,
                (filename, relative_path, mime, payment_id),
            )
        if existing["attachment_path"] != relative_path:
            delete_debt_attachment(existing["attachment_path"])
        self.send_json(build_debts_state())

    def serve_debt_payment_attachment(self, payment_id: int) -> None:
        with db_connection() as conn:
            row = conn.execute(
                "SELECT attachment_name, attachment_path, attachment_mime FROM debt_payments WHERE id=?",
                (payment_id,),
            ).fetchone()
        if not row or not row["attachment_path"]:
            self.send_error(404, "Archivo no encontrado")
            return
        file_path = DATA / row["attachment_path"]
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404, "Archivo no encontrado")
            return
        content_type = row["attachment_mime"] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'inline; filename="{row["attachment_name"]}"')
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def serve_debt_transactions(self, debt_id: int) -> None:
        with db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE debt_id=? ORDER BY date DESC, id DESC",
                (debt_id,),
            ).fetchall()
        self.send_json([rowdict(row) for row in rows])

    def serve_debts_export(self) -> None:
        debts_state = build_debts_state()
        payload = build_debts_xlsx(debts_state)
        filename = f'deudas-{datetime.now().strftime("%Y-%m-%d")}.xlsx'
        self.send_file_bytes(
            payload,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename,
        )

    def serve_ahorros_export(self) -> None:
        payload = build_ahorros_xlsx(build_ahorros_state())
        filename = f'ahorros-{datetime.now().strftime("%Y-%m-%d")}.xlsx'
        self.send_file_bytes(
            payload,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename,
        )

    def load_wedding_sample_data(self) -> None:
        if not DEMO_MODE:
            self.send_error(403, "Solo disponible en modo demo")
            return
        with db_connection() as conn:
            expense_rows = conn.execute("SELECT attachment_path FROM wedding_expenses").fetchall()
            payment_rows = conn.execute("SELECT attachment_path FROM wedding_payments").fetchall()
            conn.execute("DELETE FROM wedding_payments")
            conn.execute("DELETE FROM wedding_expenses")
            conn.execute(
                """
                INSERT INTO wedding_settings (key, value)
                VALUES ('budget', '60000')
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """
            )
            now = datetime.now().isoformat(timespec="seconds")
            for expense in WEDDING_SAMPLE_EXPENSES:
                cursor = conn.execute(
                    """
                    INSERT INTO wedding_expenses
                    (date, description, category, vendor, amount, legacy_id, created_at)
                    VALUES (?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        expense["date"],
                        expense["description"],
                        expense["category"],
                        expense["vendor"],
                        float(expense["amount"]),
                        now,
                    ),
                )
                initial_payment = float(expense.get("initialPayment") or 0)
                if initial_payment > 0:
                    conn.execute(
                        """
                        INSERT INTO wedding_payments
                        (expense_id, date, amount, note, legacy_id, created_at)
                        VALUES (?, ?, ?, ?, NULL, ?)
                        """,
                        (
                            cursor.lastrowid,
                            expense.get("paymentDate") or expense["date"],
                            min(initial_payment, float(expense["amount"])),
                            "Abono inicial",
                            now,
                        ),
                    )
        for row in expense_rows:
            delete_wedding_attachment(row["attachment_path"])
        for row in payment_rows:
            delete_wedding_attachment(row["attachment_path"])
        self.send_json(build_wedding_state(), status=201)

    def serve_wedding_attachment(self, expense_id: int) -> None:
        with db_connection() as conn:
            row = conn.execute(
                """
                SELECT attachment_name, attachment_path, attachment_mime
                FROM wedding_expenses
                WHERE id=?
                """,
                (expense_id,),
            ).fetchone()
        if not row or not row["attachment_path"]:
            self.send_error(404, "Archivo no encontrado")
            return
        file_path = DATA / row["attachment_path"]
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404, "Archivo no encontrado")
            return
        content_type = row["attachment_mime"] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'inline; filename="{row["attachment_name"]}"')
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def serve_wedding_export(self) -> None:
        wedding = build_wedding_state()
        payload = build_wedding_xlsx(wedding)
        filename = f'gastos-boda-{datetime.now().strftime("%Y-%m-%d")}.xlsx'
        self.send_file_bytes(
            payload,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename,
        )

    def serve_transactions_export(self, month: str) -> None:
        dashboard = build_dashboard(month)
        payload = build_transactions_xlsx(dashboard, month)
        self.send_file_bytes(
            payload,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"movimientos-{month}.xlsx",
        )

    def serve_sales_export(self, month: str) -> None:
        dashboard = build_dashboard(month)
        payload = build_sales_xlsx(dashboard, month)
        self.send_file_bytes(
            payload,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"ventas-usd-{month}.xlsx",
        )

    def serve_house_export(self, month: str) -> None:
        house = build_house_state(month)
        payload = build_house_xlsx(house, month)
        self.send_file_bytes(
            payload,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"pago-casa-{month}.xlsx",
        )

    def serve_wedding_payment_attachment(self, payment_id: int) -> None:
        with db_connection() as conn:
            row = conn.execute(
                """
                SELECT attachment_name, attachment_path, attachment_mime
                FROM wedding_payments
                WHERE id=?
                """,
                (payment_id,),
            ).fetchone()
        if not row or not row["attachment_path"]:
            self.send_error(404, "Archivo no encontrado")
            return
        file_path = DATA / row["attachment_path"]
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404, "Archivo no encontrado")
            return
        content_type = row["attachment_mime"] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'inline; filename="{row["attachment_name"]}"')
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def serve_house_attachment(self, payment_id: int) -> None:
        with db_connection() as conn:
            row = conn.execute(
                """
                SELECT attachment_name, attachment_path, attachment_mime
                FROM house_payments
                WHERE id=?
                """,
                (payment_id,),
            ).fetchone()
        if not row or not row["attachment_path"]:
            self.send_error(404, "Archivo no encontrado")
            return
        file_path = DATA / row["attachment_path"]
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404, "Archivo no encontrado")
            return
        content_type = row["attachment_mime"] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'inline; filename="{row["attachment_name"]}"')
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def serve_transaction_attachment(self, transaction_id: int) -> None:
        with db_connection() as conn:
            row = conn.execute(
                """
                SELECT attachment_name, attachment_path, attachment_mime
                FROM transactions
                WHERE id=?
                """,
                (transaction_id,),
            ).fetchone()
        if not row or not row["attachment_path"]:
            self.send_error(404, "Archivo no encontrado")
            return
        file_path = DATA / row["attachment_path"]
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404, "Archivo no encontrado")
            return
        content_type = row["attachment_mime"] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'inline; filename="{row["attachment_name"]}"')
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def serve_report_export(self, month: str, file_format: str) -> None:
        report = build_reports(month)
        if file_format in ("xlsx", "excel"):
            payload = build_report_xlsx(report)
            filename = f"reporte-financiero-{report['month']}.xlsx"
            self.send_file_bytes(
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename,
            )
            return
        if file_format == "pdf":
            payload = build_report_pdf(report)
            filename = f"reporte-financiero-{report['month']}.pdf"
            self.send_file_bytes(payload, "application/pdf", filename)
            return
        self.serve_report_csv(month)

    def send_file_bytes(self, payload: bytes, content_type: str, filename: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def serve_report_csv(self, month: str) -> None:
        report = build_reports(month)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Reporte financiero", report["month"]])
        writer.writerow([])
        writer.writerow(["Resumen", "Monto Q"])
        writer.writerow(["Ingresos", report["summary"]["income"]])
        writer.writerow(["Gastos", report["summary"]["expenses"]])
        writer.writerow(["Ahorro", report["summary"]["savings"]])
        writer.writerow(["Resultado", report["summary"]["balance"]])
        writer.writerow([])
        writer.writerow(["Comparativo mes contra mes", "Actual Q", "Anterior Q", "Diferencia Q", "Cambio %"])
        for label, key in (
            ("Ingresos", "income"),
            ("Gastos", "expenses"),
            ("Ahorro", "savings"),
            ("Resultado", "balance"),
        ):
            metric = report["comparison"][key]
            writer.writerow(
                [
                    label,
                    metric["current"],
                    metric["previous"],
                    metric["delta"],
                    round(metric["percent"] * 100, 2),
                ]
            )
        writer.writerow([])
        writer.writerow(
            [
                "Resumen por banco",
                "Ingresos Q",
                "Gastos Q",
                "Ahorro Q",
                "Transferencias Q",
                "Neto Q",
                "Movimientos",
            ]
        )
        for row in report["byBank"]:
            writer.writerow(
                [
                    row["bank"],
                    row["income"],
                    row["expenses"],
                    row["savings"],
                    row["transfers"],
                    row["net"],
                    row["count"],
                ]
            )
        writer.writerow([])
        writer.writerow(["Comparacion mensual", "Ingresos", "Gastos", "Ahorro", "Resultado"])
        for row in report["trend"]:
            writer.writerow(
                [row["month"], row["income"], row["expenses"], row["savings"], row["balance"]]
            )
        writer.writerow([])
        writer.writerow(["Gastos por categoria", "Monto Q"])
        writer.writerows(report["byCategory"])
        writer.writerow([])
        writer.writerow(["Metodos de pago recurrentes", "Mensual equivalente Q"])
        writer.writerows(report["byPaymentMethod"])
        writer.writerow([])
        writer.writerow(["Gastos principales", "Fecha", "Categoria", "Cuenta", "Monto Q"])
        for row in report["topExpenses"]:
            writer.writerow(
                [row["description"], row["date"], row["category"], row["account"], row["amount"]]
            )
        payload = ("\ufeff" + output.getvalue()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="reporte-financiero-{report["month"]}.csv"',
        )
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def serve_static(self, path: str) -> None:
        requested = "index.html" if path in ("", "/") else path.lstrip("/")
        file_path = (STATIC / requested).resolve()
        try:
            file_path.relative_to(STATIC.resolve())
        except ValueError:
            self.send_error(404)
            return
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404)
            return
        content_type = "text/html"
        if file_path.suffix == ".css":
            content_type = "text/css"
        elif file_path.suffix == ".js":
            content_type = "application/javascript"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(file_path.read_bytes())

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def send_json(self, data, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def parse_multipart(handler: BaseHTTPRequestHandler) -> tuple[dict, dict]:
    content_type = handler.headers.get("Content-Type", "")
    match = re.search(r"boundary=(.+)", content_type)
    if not match:
        raise ValueError("Content-Type multipart invalido")
    boundary = ("--" + match.group(1)).encode()
    length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(length)
    fields: dict[str, str] = {}
    files: dict[str, dict] = {}
    for part in body.split(boundary):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        header_blob, _, content = part.partition(b"\r\n\r\n")
        headers = header_blob.decode("utf-8", errors="replace")
        name_match = re.search(r'name="([^"]+)"', headers)
        if not name_match:
            continue
        name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', headers)
        content = content.rstrip(b"\r\n")
        if filename_match:
            files[name] = {"filename": Path(filename_match.group(1)).name, "data": content}
        else:
            fields[name] = content.decode("utf-8", errors="replace")
    return fields, files


def build_monthly_control(month: str) -> dict:
    if not re.match(r"^\d{4}-\d{2}$", month or ""):
        month = datetime.now().strftime("%Y-%m")
    with db_connection() as conn:
        budget_row = conn.execute(
            "SELECT amount FROM monthly_budgets WHERE month = ?",
            (month,),
        ).fetchone()
        rows = conn.execute(
            "SELECT type, account, amount, source_import_id FROM transactions WHERE substr(date, 1, 7) = ?",
            (month,),
        ).fetchall()

    budget = float(budget_row["amount"]) if budget_row else 0.0
    imported_credits = 0.0
    imported_debits = 0.0
    manual_cash_expenses = 0.0
    total_credits = 0.0
    total_debits = 0.0

    for row in rows:
        amount = float(row["amount"] or 0)
        row_type = row["type"]
        is_imported = row["source_import_id"] is not None
        if row_type in {"Ingreso", "Ahorro", "Venta USD"}:
            total_credits += amount
            if is_imported:
                imported_credits += amount
        elif row_type in {"Gasto", "Transferencia"}:
            total_debits += amount
            if is_imported:
                imported_debits += amount
            elif row_type == "Gasto" and row["account"] == "Efectivo":
                manual_cash_expenses += amount

    return {
        "month": month,
        "budget": round(budget, 2),
        "importedCredits": round(imported_credits, 2),
        "importedDebits": round(imported_debits, 2),
        "manualCashExpenses": round(manual_cash_expenses, 2),
        "totalCredits": round(total_credits, 2),
        "totalDebits": round(total_debits, 2),
        "remaining": round(budget - total_debits, 2),
        "recordCount": len(rows),
    }

def build_dashboard(month: str) -> dict:
    with db_connection() as conn:
        all_txs = conn.execute("SELECT * FROM transactions WHERE substr(date,1,7)=? ORDER BY date", (month,)).fetchall()
        budget_row = conn.execute(
            "SELECT amount FROM monthly_budgets WHERE month = ?",
            (month,),
        ).fetchone()
    initial_balance = float(budget_row["amount"]) if budget_row else 0.0
    savings_txs = [row for row in all_txs if row["ahorro_id"] is not None]
    fund_txs = [row for row in all_txs if row["fund_id"] is not None]
    txs = [row for row in all_txs if row["ahorro_id"] is None and row["fund_id"] is None]
    base_income = sum(row["amount"] for row in txs if row["type"] == "Ingreso")
    usd_sales = sum(row["amount"] for row in txs if row["type"] == "Venta USD")
    income = base_income
    expenses = sum(row["amount"] for row in txs if row["type"] == "Gasto")
    savings = sum(row["amount"] for row in txs if row["type"] == "Ahorro")
    transfers = sum(row["amount"] for row in txs if row["type"] == "Transferencia")
    by_category: dict[str, float] = {}
    by_account: dict[str, float] = {}
    by_bank: dict[str, dict[str, float]] = {}
    for row in txs:
        if row["type"] == "Gasto":
            by_category[row["category"]] = by_category.get(row["category"], 0) + row["amount"]
        if row["type"] == "Venta USD":
            continue
        account_delta = row["amount"] if row["type"] in ("Ingreso", "Ahorro") else -row["amount"]
        by_account[row["account"]] = by_account.get(row["account"], 0) + account_delta
        bank_name = bank_from_account(row["account"])
        bank_row = by_bank.setdefault(
            bank_name,
            {
                "income": 0,
                "expenses": 0,
                "savings": 0,
                "usdSales": 0,
                "transfers": 0,
                "net": 0,
            },
        )
        if row["type"] == "Ingreso":
            bank_row["income"] += row["amount"]
            bank_row["net"] += row["amount"]
        elif row["type"] == "Ahorro":
            bank_row["savings"] += row["amount"]
            bank_row["net"] += row["amount"]
        elif row["type"] == "Transferencia":
            bank_row["transfers"] += row["amount"]
            bank_row["net"] -= row["amount"]
        else:
            bank_row["expenses"] += row["amount"]
            bank_row["net"] -= row["amount"]
    return {
        "month": month,
        "baseIncome": base_income,
        "usdSales": usd_sales,
        "income": income,
        "expenses": expenses,
        "savings": savings,
        "transfers": transfers,
        "initialBalance": round(initial_balance, 2),
        "balance": income - expenses - savings,
        "available": round(initial_balance + income - expenses - savings, 2),
        "savingsRate": savings / income if income else 0,
        "byCategory": sorted(by_category.items(), key=lambda x: x[1], reverse=True),
        "byAccount": sorted(by_account.items(), key=lambda x: x[0]),
        "byBank": [{"bank": bank, **values} for bank, values in sorted(by_bank.items(), key=lambda x: x[0])],
        "transactions": [rowdict(row) for row in txs],
        "savingsTransactions": [rowdict(row) for row in savings_txs],
        "fundTransactions": [rowdict(row) for row in fund_txs],
    }


def month_sequence(end_month: str, count: int = 6) -> list[str]:
    if not re.match(r"^\d{4}-\d{2}$", end_month or ""):
        end_month = datetime.now().strftime("%Y-%m")
    year, month = map(int, end_month.split("-"))
    months = []
    for offset in range(count - 1, -1, -1):
        absolute = year * 12 + (month - 1) - offset
        item_year, item_month = divmod(absolute, 12)
        months.append(f"{item_year:04d}-{item_month + 1:02d}")
    return months


def build_reports(month: str) -> dict:
    months = month_sequence(month, 6)
    first_month = months[0]
    last_month = months[-1]
    with db_connection() as conn:
        all_rows = conn.execute(
            """
            SELECT *
            FROM transactions
            WHERE substr(date,1,7) BETWEEN ? AND ?
            ORDER BY date, id
            """,
            (first_month, last_month),
        ).fetchall()
        rows = [row for row in all_rows if row["ahorro_id"] is None and row["fund_id"] is None]
        recurring_rows = conn.execute(
            """
            SELECT account, amount, frequency
            FROM recurring_expenses
            WHERE active=1
            """
        ).fetchall()

    trend = []
    for item_month in months:
        month_rows = [row for row in rows if row["date"][:7] == item_month]
        income = sum(row["amount"] for row in month_rows if row["type"] == "Ingreso")
        expenses = sum(row["amount"] for row in month_rows if row["type"] == "Gasto")
        savings = sum(row["amount"] for row in month_rows if row["type"] == "Ahorro")
        trend.append(
            {
                "month": item_month,
                "income": round(income, 2),
                "expenses": round(expenses, 2),
                "savings": round(savings, 2),
                "balance": round(income - expenses - savings, 2),
            }
        )

    selected_rows = [row for row in rows if row["date"][:7] == last_month]
    by_category: dict[str, float] = {}
    by_account: dict[str, float] = {}
    by_bank: dict[str, dict[str, float | int]] = {}
    for row in selected_rows:
        if row["type"] == "Gasto":
            by_category[row["category"]] = by_category.get(row["category"], 0) + row["amount"]
        if row["type"] == "Venta USD":
            continue
        delta = row["amount"] if row["type"] in ("Ingreso", "Ahorro") else -row["amount"]
        by_account[row["account"]] = by_account.get(row["account"], 0) + delta
        bank_name = bank_from_account(row["account"])
        bank_row = by_bank.setdefault(
            bank_name,
            {
                "income": 0.0,
                "expenses": 0.0,
                "savings": 0.0,
                "transfers": 0.0,
                "net": 0.0,
                "count": 0,
            },
        )
        bank_row["count"] += 1
        if row["type"] == "Ingreso":
            bank_row["income"] += row["amount"]
            bank_row["net"] += row["amount"]
        elif row["type"] == "Gasto":
            bank_row["expenses"] += row["amount"]
            bank_row["net"] -= row["amount"]
        elif row["type"] == "Ahorro":
            bank_row["savings"] += row["amount"]
            bank_row["net"] += row["amount"]
        elif row["type"] == "Transferencia":
            bank_row["transfers"] += row["amount"]
            bank_row["net"] -= row["amount"]

    by_payment_method: dict[str, float] = {}
    for row in recurring_rows:
        equivalent = row["amount"] if row["frequency"] == "Mensual" else row["amount"] / 12
        by_payment_method[row["account"]] = by_payment_method.get(row["account"], 0) + equivalent

    selected = trend[-1]
    previous = trend[-2] if len(trend) > 1 else {"expenses": 0}
    expense_change = (
        (selected["expenses"] - previous["expenses"]) / previous["expenses"]
        if previous["expenses"]
        else 0
    )

    def compare_metric(key: str) -> dict:
        current = float(selected.get(key, 0) or 0)
        previous_value = float(previous.get(key, 0) or 0)
        delta = current - previous_value
        percent = delta / previous_value if previous_value else 0
        return {
            "current": round(current, 2),
            "previous": round(previous_value, 2),
            "delta": round(delta, 2),
            "percent": percent,
        }

    top_expenses = sorted(
        [
            {
                "date": row["date"],
                "description": row["description"],
                "category": row["category"],
                "account": row["account"],
                "amount": row["amount"],
            }
            for row in selected_rows
            if row["type"] == "Gasto"
        ],
        key=lambda item: item["amount"],
        reverse=True,
    )[:8]

    recurring_summary = build_recurring_state(last_month)["summary"]

    wedding_state = build_wedding_state()
    wedding = {
        "hasData": len(wedding_state["expenses"]) > 0,
        "budget": wedding_state["budget"],
        "spent": wedding_state["spent"],
        "paid": wedding_state["paid"],
        "pending": wedding_state["pending"],
        "available": wedding_state["available"],
        "progress": wedding_state["progress"],
    }

    house_state = build_house_state(last_month)
    with db_connection() as conn:
        house_ever = conn.execute("SELECT 1 FROM house_payments LIMIT 1").fetchone()
    house = {
        "hasData": house_ever is not None,
        "total": house_state["total"],
        "count": house_state["count"],
    }

    return {
        "month": last_month,
        "summary": {
            **selected,
            "savingsRate": selected["savings"] / selected["income"] if selected["income"] else 0,
            "expenseChange": expense_change,
        },
        "trend": trend,
        "comparison": {
            "currentMonth": last_month,
            "previousMonth": previous.get("month", ""),
            "income": compare_metric("income"),
            "expenses": compare_metric("expenses"),
            "savings": compare_metric("savings"),
            "balance": compare_metric("balance"),
        },
        "byCategory": sorted(by_category.items(), key=lambda item: item[1], reverse=True),
        "byAccount": sorted(by_account.items(), key=lambda item: item[0]),
        "byBank": [
            {"bank": bank, **values}
            for bank, values in sorted(
                by_bank.items(), key=lambda item: abs(float(item[1]["net"])), reverse=True
            )
        ],
        "byPaymentMethod": sorted(
            by_payment_method.items(), key=lambda item: item[1], reverse=True
        ),
        "recurringSummary": recurring_summary,
        "wedding": wedding,
        "house": house,
        "topExpenses": top_expenses,
    }


def report_money(value: float | int | None) -> str:
    amount = float(value or 0)
    sign = "-" if amount < 0 else ""
    return f"{sign}Q {abs(amount):,.2f}"


def report_percent(value: float | int | None) -> str:
    return f"{float(value or 0) * 100:.1f}%"


def report_month_name(month: str) -> str:
    names = [
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ]
    try:
        year, month_number = month.split("-")
        return f"{names[int(month_number) - 1]} de {year}"
    except Exception:
        return month


def xlsx_col(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def xlsx_cell(value, row: int, col: int, style: int = 0) -> str:
    ref = f"{xlsx_col(col)}{row}"
    style_attr = f' s="{style}"' if style else ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{style_attr}><v>{float(value):.2f}</v></c>'
    text = xml_escape("" if value is None else str(value))
    return f'<c r="{ref}" t="inlineStr"{style_attr}><is><t>{text}</t></is></c>'


def xlsx_sheet(rows: list[dict], widths: list[int]) -> str:
    cols = "".join(
        f'<col min="{idx}" max="{idx}" width="{width}" customWidth="1"/>'
        for idx, width in enumerate(widths, start=1)
    )
    sheet_rows = []
    for row_idx, row in enumerate(rows, start=1):
        values = row.get("values", [])
        styles = row.get("styles", [])
        height = row.get("height")
        height_attr = f' ht="{height}" customHeight="1"' if height else ""
        cells = []
        for col_idx, value in enumerate(values, start=1):
            style = styles[col_idx - 1] if col_idx <= len(styles) else row.get("style", 0)
            cells.append(xlsx_cell(value, row_idx, col_idx, style))
        sheet_rows.append(f'<row r="{row_idx}"{height_attr}>{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<cols>{cols}</cols><sheetData>{''.join(sheet_rows)}</sheetData>"
        "</worksheet>"
    )


def report_rows(report: dict) -> dict[str, list[dict]]:
    summary = report["summary"]
    comparison = report["comparison"]
    rows = {
        "Resumen": [
            {"values": ["Reporte financiero", report_month_name(report["month"])], "style": 1, "height": 24},
            {"values": []},
            {"values": ["Resumen", "Monto"], "style": 2},
            {"values": ["Ingresos", summary["income"]], "styles": [0, 4]},
            {"values": ["Gastos", summary["expenses"]], "styles": [0, 5]},
            {"values": ["Ahorro", summary["savings"]], "styles": [0, 3]},
            {"values": ["Resultado", summary["balance"]], "styles": [0, 3]},
            {"values": ["Tasa de ahorro", report_percent(summary.get("savingsRate"))], "styles": [0, 0]},
            {"values": []},
            {"values": ["Comparativo mes contra mes", "Actual", "Anterior", "Diferencia", "Cambio %"], "style": 2},
        ],
        "Bancos": [
            {"values": ["Resumen por banco", report_month_name(report["month"])], "style": 1, "height": 24},
            {"values": []},
            {"values": ["Banco", "Ingresos", "Gastos", "Ahorro", "Transferencias", "Neto", "Movimientos"], "style": 2},
        ],
        "Tendencia": [
            {"values": ["Tendencia de 6 meses", report_month_name(report["month"])], "style": 1, "height": 24},
            {"values": []},
            {"values": ["Mes", "Ingresos", "Gastos", "Ahorro", "Resultado"], "style": 2},
        ],
        "Categorias": [
            {"values": ["Gastos por categoria", report_month_name(report["month"])], "style": 1, "height": 24},
            {"values": []},
            {"values": ["Categoria", "Monto"], "style": 2},
        ],
        "Gastos principales": [
            {"values": ["Gastos principales", report_month_name(report["month"])], "style": 1, "height": 24},
            {"values": []},
            {"values": ["Fecha", "Descripcion", "Categoria", "Cuenta", "Monto"], "style": 2},
        ],
        "Compromisos": [
            {"values": ["Compromisos fijos del mes", report_month_name(report["month"])], "style": 1, "height": 24},
            {"values": []},
            {"values": ["Concepto", "Monto"], "style": 2},
        ],
    }
    recurring_summary = report["recurringSummary"]
    for label, key, style in (
        ("Debido este mes", "dueThisMonth", 3),
        ("Pagado este mes", "paidThisMonth", 4),
        ("Pendiente este mes", "pendingThisMonth", 5),
        ("Equivalente mensual", "monthlyEquivalent", 3),
        ("Provision anual", "annualProvision", 3),
    ):
        rows["Compromisos"].append({"values": [label, recurring_summary.get(key, 0)], "styles": [0, style]})
    if report["wedding"]["hasData"]:
        wedding = report["wedding"]
        rows["Boda"] = [
            {"values": ["Presupuesto de boda", report_month_name(report["month"])], "style": 1, "height": 24},
            {"values": []},
            {"values": ["Concepto", "Monto"], "style": 2},
            {"values": ["Presupuesto", wedding["budget"]], "styles": [0, 3]},
            {"values": ["Gastado", wedding["spent"]], "styles": [0, 5]},
            {"values": ["Pagado", wedding["paid"]], "styles": [0, 4]},
            {"values": ["Pendiente", wedding["pending"]], "styles": [0, 5]},
            {"values": ["Disponible", wedding["available"]], "styles": [0, 3]},
            {"values": ["Ejecutado", report_percent(wedding["progress"])], "styles": [0, 0]},
        ]
    if report["house"]["hasData"]:
        house = report["house"]
        rows["Casa"] = [
            {"values": ["Pago de la casa", report_month_name(report["month"])], "style": 1, "height": 24},
            {"values": []},
            {"values": ["Concepto", "Monto"], "style": 2},
            {"values": ["Pagado este mes", house["total"]], "styles": [0, 4]},
            {"values": ["Cantidad de pagos", house["count"]], "styles": [0, 0]},
        ]
    for label, key in (
        ("Ingresos", "income"),
        ("Gastos", "expenses"),
        ("Ahorro", "savings"),
        ("Resultado", "balance"),
    ):
        metric = comparison[key]
        rows["Resumen"].append(
            {
                "values": [
                    label,
                    metric["current"],
                    metric["previous"],
                    metric["delta"],
                    report_percent(metric["percent"]),
                ],
                "styles": [0, 3, 3, 3, 0],
            }
        )
    for bank in report["byBank"]:
        rows["Bancos"].append(
            {
                "values": [
                    bank["bank"],
                    bank["income"],
                    bank["expenses"],
                    bank["savings"],
                    bank["transfers"],
                    bank["net"],
                    bank["count"],
                ],
                "styles": [0, 4, 5, 3, 3, 3, 0],
            }
        )
    for item in report["trend"]:
        rows["Tendencia"].append(
            {
                "values": [
                    report_month_name(item["month"]),
                    item["income"],
                    item["expenses"],
                    item["savings"],
                    item["balance"],
                ],
                "styles": [0, 4, 5, 3, 3],
            }
        )
    for category, amount in report["byCategory"]:
        rows["Categorias"].append({"values": [category, amount], "styles": [0, 5]})
    for expense in report["topExpenses"]:
        rows["Gastos principales"].append(
            {
                "values": [
                    expense["date"],
                    expense["description"],
                    expense["category"],
                    expense["account"],
                    expense["amount"],
                ],
                "styles": [0, 0, 0, 0, 5],
            }
        )
    return rows


def build_xlsx_workbook(sheets: dict[str, list[dict]], widths: dict[str, list[int]]) -> bytes:
    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="1"><numFmt numFmtId="164" formatCode="Q #,##0.00"/></numFmts>
  <fonts count="4">
    <font><sz val="11"/><color rgb="FF111827"/><name val="Calibri"/></font>
    <font><b/><sz val="16"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><color rgb="FF111827"/><name val="Calibri"/></font>
  </fonts>
  <fills count="5">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF173A5E"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFEAFBF5"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFFEFEF"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left style="thin"><color rgb="FFD7E0ED"/></left><right style="thin"><color rgb="FFD7E0ED"/></right><top style="thin"><color rgb="FFD7E0ED"/></top><bottom style="thin"><color rgb="FFD7E0ED"/></bottom><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="6">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFill="1" applyFont="1"/>
    <xf numFmtId="0" fontId="2" fillId="2" borderId="1" xfId="0" applyFill="1" applyFont="1"/>
    <xf numFmtId="164" fontId="3" fillId="0" borderId="1" xfId="0" applyNumberFormat="1"/>
    <xf numFmtId="164" fontId="3" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1"/>
    <xf numFmtId="164" fontId="3" fillId="4" borderId="1" xfId="0" applyNumberFormat="1" applyFill="1"/>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""
    sheet_names = list(sheets.keys())
    workbook_sheets = "".join(
        f'<sheet name="{xml_escape(name)}" sheetId="{idx}" r:id="rId{idx}"/>'
        for idx, name in enumerate(sheet_names, start=1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{workbook_sheets}</sheets></workbook>"
    )
    rels = "".join(
        f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>'
        for idx in range(1, len(sheet_names) + 1)
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{rels}<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for idx in range(1, len(sheet_names) + 1)
        )
        + "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("_rels/.rels", root_rels)
        package.writestr("xl/workbook.xml", workbook)
        package.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        package.writestr("xl/styles.xml", styles)
        for idx, name in enumerate(sheet_names, start=1):
            package.writestr(f"xl/worksheets/sheet{idx}.xml", xlsx_sheet(sheets[name], widths[name]))
    return output.getvalue()


def build_report_xlsx(report: dict) -> bytes:
    sheets = report_rows(report)
    widths = {
        "Resumen": [28, 18, 18, 18, 14],
        "Bancos": [28, 16, 16, 16, 18, 16, 14],
        "Tendencia": [22, 16, 16, 16, 16],
        "Categorias": [34, 18],
        "Gastos principales": [14, 45, 22, 30, 16],
        "Compromisos": [28, 18],
        "Boda": [28, 18],
        "Casa": [28, 18],
    }
    return build_xlsx_workbook(sheets, widths)


def build_wedding_xlsx(wedding: dict) -> bytes:
    today = datetime.now().strftime("%d/%m/%Y")
    rows = [
        {"values": ["Gastos de boda", today], "style": 1, "height": 24},
        {"values": []},
        {"values": ["Presupuesto", "Gastado", "Pagado", "Pendiente", "Disponible"], "style": 2},
        {
            "values": [
                wedding["budget"],
                wedding["spent"],
                wedding["paid"],
                wedding["pending"],
                wedding["available"],
            ],
            "styles": [3, 5, 4, 5, 3],
        },
        {"values": []},
        {
            "values": [
                "Vencimiento",
                "Concepto",
                "Categoria",
                "Proveedor",
                "Total",
                "Abonado",
                "Pendiente",
                "Estado",
            ],
            "style": 2,
        },
    ]
    for expense in wedding["expenses"]:
        rows.append(
            {
                "values": [
                    expense["date"],
                    expense["description"],
                    expense["category"],
                    expense["vendor"] or "-",
                    expense["amount"],
                    expense["paid_amount"],
                    expense["pending_amount"],
                    expense["status"],
                ],
                "styles": [0, 0, 0, 0, 3, 4, 5, 0],
            }
        )
    widths = {"Gastos de boda": [14, 34, 16, 26, 14, 14, 14, 14]}
    return build_xlsx_workbook({"Gastos de boda": rows}, widths)


def build_transactions_xlsx(dashboard: dict, month: str) -> bytes:
    rows = [
        {"values": ["Movimientos del mes", report_month_name(month)], "style": 1, "height": 24},
        {"values": []},
        {"values": ["Ingresos", "Gastos", "Ahorro", "Disponible"], "style": 2},
        {
            "values": [dashboard["income"], dashboard["expenses"], dashboard["savings"], dashboard["available"]],
            "styles": [4, 5, 3, 3],
        },
        {"values": []},
        {"values": ["Fecha", "Tipo", "Categoria", "Cuenta", "Descripcion", "Monto", "Origen"], "style": 2},
    ]
    for tx in dashboard["transactions"]:
        rows.append(
            {
                "values": [
                    tx["date"],
                    tx["type"],
                    tx["category"],
                    tx["account"],
                    tx["description"],
                    tx["amount"],
                    "Importado" if tx.get("source_import_id") else "Manual",
                ],
                "styles": [0, 0, 0, 0, 0, 3, 0],
            }
        )
    widths = {"Movimientos": [14, 14, 18, 26, 34, 14, 14]}
    return build_xlsx_workbook({"Movimientos": rows}, widths)




def build_sales_xlsx(dashboard: dict, month: str) -> bytes:
    sale_txs = [
        tx for tx in dashboard.get("transactions", []) if tx["type"] == "Venta USD" and not tx.get("source_import_id")
    ]
    gtq_total = sum(tx["amount"] for tx in sale_txs)
    usd_total = sum(tx.get("usd_amount") or 0 for tx in sale_txs)
    rows = [
        {"values": ["Ventas de dolares", report_month_name(month)], "style": 1, "height": 24},
        {"values": []},
        {"values": ["Ventas Quetzales", "Ventas USD", "Registros"], "style": 2},
        {"values": [gtq_total, usd_total, len(sale_txs)], "styles": [4, 4, 0]},
        {"values": []},
        {"values": ["Fecha", "Tipo", "Categoria", "Cuenta", "Descripcion", "Monto Q", "Monto USD"], "style": 2},
    ]
    for tx in sale_txs:
        rows.append(
            {
                "values": [
                    tx["date"],
                    tx["type"],
                    tx["category"],
                    tx["account"],
                    tx["description"],
                    tx["amount"],
                    tx.get("usd_amount") or 0,
                ],
                "styles": [0, 0, 0, 0, 0, 3, 3],
            }
        )
    widths = {"Ventas USD": [14, 14, 16, 26, 34, 14, 14]}
    return build_xlsx_workbook({"Ventas USD": rows}, widths)


def build_house_xlsx(house: dict, month: str) -> bytes:
    rows = [
        {"values": ["Pagos de la casa", report_month_name(month)], "style": 1, "height": 24},
        {"values": []},
        {"values": ["Total pagado", "Cantidad de pagos"], "style": 2},
        {"values": [house["total"], house["count"]], "styles": [4, 0]},
        {"values": []},
        {"values": ["Fecha", "Concepto", "Monto", "Documento"], "style": 2},
    ]
    for payment in house["payments"]:
        rows.append(
            {
                "values": [
                    payment["paymentDate"],
                    payment["description"],
                    payment["amount"],
                    "Si" if payment["has_attachment"] else "No",
                ],
                "styles": [0, 0, 3, 0],
            }
        )
    widths = {"Pagos casa": [14, 34, 14, 14]}
    return build_xlsx_workbook({"Pagos casa": rows}, widths)


def build_debts_xlsx(debts_state: dict) -> bytes:
    today = datetime.now().strftime("%d/%m/%Y")
    rows = [
        {"values": ["Deudas y tarjetas", today], "style": 1, "height": 24},
        {"values": []},
        {"values": ["Deuda total", "Credito disponible", "Pago minimo"], "style": 2},
        {
            "values": [debts_state["totalDebt"], debts_state["totalAvailable"], debts_state["minPaymentTotal"]],
            "styles": [5, 4, 3],
        },
        {"values": []},
        {
            "values": ["Nombre", "Tipo", "Banco", "Saldo", "Limite/Original", "Tasa %", "Cuota", "Dia pago", "Fecha fin/limite"],
            "style": 2,
        },
    ]
    for debt in debts_state["debts"]:
        is_card = debt["type"] == "Tarjeta de credito"
        rows.append(
            {
                "values": [
                    debt["name"],
                    debt["type"],
                    debt["bank"] or "-",
                    debt["current_balance"],
                    (debt["credit_limit"] if is_card else debt["original_amount"]) or 0,
                    debt["interest_rate"] or 0,
                    (debt["monthly_payment"] if not is_card else 0) or 0,
                    debt["due_day"] or "-",
                    debt["end_date"] or "-",
                ],
                "styles": [0, 0, 0, 5, 3, 0, 3, 0, 0],
            }
        )
    widths = {"Deudas": [24, 18, 16, 14, 16, 10, 12, 10, 14]}
    return build_xlsx_workbook({"Deudas": rows}, widths)


def build_ahorros_xlsx(ahorros_state: dict) -> bytes:
    today = datetime.now().strftime("%d/%m/%Y")
    rows = [
        {"values": ["Ahorros y fondos", today], "style": 1, "height": 24},
        {"values": []},
        {"values": ["Saldo total", "Cuentas registradas"], "style": 2},
        {"values": [ahorros_state["totalBalance"], ahorros_state["count"]], "styles": [5, 0]},
        {"values": []},
        {"values": ["Nombre", "Tipo", "Banco", "Cuenta", "Aporte mensual", "Saldo actual"], "style": 2},
    ]
    for ahorro in ahorros_state["ahorros"]:
        rows.append(
            {
                "values": [
                    ahorro["name"], ahorro["type"], ahorro["bank"], ahorro["account"],
                    ahorro["monthly_target"] if ahorro["type"] == "Fondo" else "-",
                    ahorro["current_balance"],
                ],
                "styles": [0, 0, 0, 0, 3, 5],
            }
        )
    widths = {"Ahorros": [24, 12, 16, 26, 16, 16]}
    return build_xlsx_workbook({"Ahorros": rows}, widths)


def pdf_escape_text(value) -> str:
    text = str(value).encode("latin-1", errors="replace").decode("latin-1")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_report_pdf(report: dict) -> bytes:
    commands: list[str] = []
    pages: list[bytes] = []
    y = 750

    def new_page() -> None:
        nonlocal commands, y
        if commands:
            pages.append("\n".join(commands).encode("latin-1", errors="replace"))
        commands = []
        y = 750
        commands.append("0.96 0.98 1 rg 0 0 612 792 re f")
        commands.append("0.09 0.22 0.36 rg 0 742 612 50 re f")
        add_text(42, 762, "Reporte financiero", 18, "white")
        add_text(420, 762, report_month_name(report["month"]), 11, "white")

    def color_cmd(color: str) -> str:
        return {
            "navy": "0.09 0.22 0.36 rg",
            "muted": "0.35 0.42 0.52 rg",
            "green": "0.00 0.50 0.32 rg",
            "red": "0.78 0.10 0.10 rg",
            "amber": "0.70 0.42 0.02 rg",
            "white": "1 1 1 rg",
            "black": "0.07 0.09 0.14 rg",
        }.get(color, "0.07 0.09 0.14 rg")

    def add_text(x: int, yy: int, text: str, size: int = 10, color: str = "black") -> None:
        commands.append(f"{color_cmd(color)} BT /F1 {size} Tf {x} {yy} Td ({pdf_escape_text(text)}) Tj ET")

    def add_section(title: str) -> None:
        nonlocal y
        if y < 120:
            new_page()
        y -= 24
        commands.append("0.88 0.92 0.97 rg 36 " + str(y - 8) + " 540 24 re f")
        add_text(44, y, title, 12, "navy")
        y -= 22

    def add_row(columns: list[str], widths: list[int], header: bool = False) -> None:
        nonlocal y
        if y < 70:
            new_page()
        x = 42
        if header:
            commands.append("0.09 0.22 0.36 rg 36 " + str(y - 7) + " 540 22 re f")
        for idx, col in enumerate(columns):
            add_text(x, y, col[:42], 8 if header else 9, "white" if header else "black")
            x += widths[idx]
        y -= 22

    new_page()
    summary = report["summary"]
    add_section("Resumen del mes")
    add_row(["Ingresos", "Gastos", "Ahorro", "Resultado"], [135, 135, 135, 135], True)
    add_row(
        [
            report_money(summary["income"]),
            report_money(summary["expenses"]),
            report_money(summary["savings"]),
            report_money(summary["balance"]),
        ],
        [135, 135, 135, 135],
    )
    add_section("Comparativo mes contra mes")
    add_row(["Concepto", "Actual", "Anterior", "Diferencia", "Cambio"], [120, 105, 105, 105, 105], True)
    for label, key in (("Ingresos", "income"), ("Gastos", "expenses"), ("Ahorro", "savings"), ("Resultado", "balance")):
        metric = report["comparison"][key]
        add_row(
            [
                label,
                report_money(metric["current"]),
                report_money(metric["previous"]),
                report_money(metric["delta"]),
                report_percent(metric["percent"]),
            ],
            [120, 105, 105, 105, 105],
        )
    add_section("Resumen por banco")
    add_row(["Banco", "Ingresos", "Gastos", "Neto", "Movs"], [170, 100, 100, 100, 70], True)
    for bank in report["byBank"]:
        add_row(
            [
                bank["bank"],
                report_money(bank["income"]),
                report_money(bank["expenses"]),
                report_money(bank["net"]),
                str(bank["count"]),
            ],
            [170, 100, 100, 100, 70],
        )
    add_section("Tendencia de 6 meses")
    add_row(["Mes", "Ingresos", "Gastos", "Ahorro", "Resultado"], [140, 100, 100, 100, 100], True)
    for item in report["trend"]:
        add_row(
            [
                report_month_name(item["month"]),
                report_money(item["income"]),
                report_money(item["expenses"]),
                report_money(item["savings"]),
                report_money(item["balance"]),
            ],
            [140, 100, 100, 100, 100],
        )
    add_section("Compromisos fijos del mes")
    add_row(["Concepto", "Monto"], [300, 240], True)
    recurring_summary = report["recurringSummary"]
    for label, key in (
        ("Debido este mes", "dueThisMonth"),
        ("Pagado este mes", "paidThisMonth"),
        ("Pendiente este mes", "pendingThisMonth"),
        ("Equivalente mensual", "monthlyEquivalent"),
        ("Provision anual", "annualProvision"),
    ):
        add_row([label, report_money(recurring_summary.get(key, 0))], [300, 240])
    if report["wedding"]["hasData"]:
        wedding = report["wedding"]
        add_section("Presupuesto de boda")
        add_row(["Concepto", "Monto"], [300, 240], True)
        add_row(["Presupuesto", report_money(wedding["budget"])], [300, 240])
        add_row(["Gastado", report_money(wedding["spent"])], [300, 240])
        add_row(["Pagado", report_money(wedding["paid"])], [300, 240])
        add_row(["Pendiente", report_money(wedding["pending"])], [300, 240])
        add_row(["Disponible", report_money(wedding["available"])], [300, 240])
        add_row(["Ejecutado", report_percent(wedding["progress"])], [300, 240])
    if report["house"]["hasData"]:
        house = report["house"]
        add_section("Pago de la casa")
        add_row(["Concepto", "Monto"], [300, 240], True)
        add_row(["Pagado este mes", report_money(house["total"])], [300, 240])
        add_row(["Cantidad de pagos", str(house["count"])], [300, 240])
    add_section("Gastos principales")
    add_row(["Fecha", "Descripcion", "Categoria", "Monto"], [85, 255, 115, 85], True)
    for expense in report["topExpenses"][:12]:
        add_row(
            [
                expense["date"],
                expense["description"],
                expense["category"],
                report_money(expense["amount"]),
            ],
            [85, 255, 115, 85],
        )
    pages.append("\n".join(commands).encode("latin-1", errors="replace"))

    objects: list[bytes] = []
    kids = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for idx, content in enumerate(pages):
        content_id = 4 + idx * 2
        page_id = content_id + 1
        kids.append(f"{page_id} 0 R")
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode("latin-1") + content + b"\nendstream")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode(
                "latin-1"
            )
        )
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>".encode("latin-1")

    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = [0]
    for obj_id, obj in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{obj_id} 0 obj\n".encode("latin-1"))
        output.write(obj)
        output.write(b"\nendobj\n")
    xref = output.tell()
    output.write(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    output.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode("latin-1"))
    output.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode(
            "latin-1"
        )
    )
    return output.getvalue()


if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer((APP_HOST, APP_PORT), App)
    display_host = "127.0.0.1" if APP_HOST in {"0.0.0.0", "::"} else APP_HOST
    print(f"Finanzas Local en http://{display_host}:{APP_PORT}")
    if AUTH_ENABLED and AUTH_PASSWORD == "cambiar-esta-clave" and not AUTH_PASSWORD_HASH:
        print("Aviso: cambia FINANZAS_PASSWORD o FINANZAS_PASSWORD_HASH antes de publicar el sistema.")
    if AUTH_ENABLED and not SESSION_SECRET_FROM_ENV:
        print("Aviso: define FINANZAS_SESSION_SECRET para que las sesiones sobrevivan a reinicios.")
    server.serve_forever()







