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
DEMO_MODE = os.environ.get("FINANZAS_DEMO", "").lower() in {"1", "true", "yes", "demo"}
EXCHANGE_RATE_URL = "https://open.er-api.com/v6/latest/USD"
DEFAULT_USD_GTQ_RATE = 7.8
LEGACY_WEDDING_DB = ROOT.parent / "Control-de-gastos-de-boda" / "data" / "boda.db"
APP_HOST = os.environ.get("FINANZAS_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("PORT", os.environ.get("FINANZAS_PORT", "8765")))
AUTH_ENABLED = os.environ.get("FINANZAS_AUTH", "1").lower() not in {"0", "false", "no", "off"}
AUTH_USER = os.environ.get("FINANZAS_USER", "erick")
AUTH_PASSWORD = os.environ.get("FINANZAS_PASSWORD", "cambiar-esta-clave")
AUTH_PASSWORD_HASH = os.environ.get("FINANZAS_PASSWORD_HASH", "")
SESSION_SECRET = os.environ.get("FINANZAS_SESSION_SECRET") or hashlib.sha256(
    f"{ROOT}|finanzas-local-dev".encode("utf-8")
).hexdigest()
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

ACCOUNTS = [
    "GYT - Cuenta ahorro sueldo",
    "GYT - Tarjeta debito",
    "GYT - Tarjeta credito",
    "BAC - Cuenta ahorro USD",
    "Banrural - Cuenta ahorro",
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
SAVINGS_CATEGORIES = ["Ahorro Banrural", "Ahorro extra"]
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
RECURRING_ACCOUNTS = ["TC", "Tarjeta de debito", "Efectivo"]
RECURRING_SAMPLE_EXPENSES = [
    ("NORDIC GYM_CUOTA GYM", "Salud y bienestar", "Tarjeta de debito", 200.00, "Mensual"),
    ("Netflix", "Suscripciones", "TC", 76.21, "Mensual"),
    ("HBO Max", "Suscripciones", "TC", 29.90, "Mensual"),
    ("Google One", "Suscripciones", "TC", 15.18, "Mensual"),
    ("Crunchyroll", "Suscripciones", "TC", 38.45, "Mensual"),
    ("Microsoft OneDrive", "Suscripciones", "TC", 152.49, "Anual"),
    ("Tigo Residencial", "Servicios", "TC", 344.00, "Mensual"),
    ("Disney plus", "Suscripciones", "TC", 129.61, "Mensual"),
    ("awesomescreenshot", "Suscripciones", "TC", 61.03, "Mensual"),
    ("Chatgpt y CODEX", "Suscripciones", "TC", 152.57, "Mensual"),
    ("Cuota Casas", "Vivienda", "Efectivo", 1000.00, "Mensual"),
    ("CUOTA FONDO", "Ahorro", "Tarjeta de debito", 510.00, "Mensual"),
]
DEMO_RECURRING_SAMPLE_EXPENSES = [
    ("Internet casa", "Servicios", "TC", 325.00, "Mensual"),
    ("Streaming familiar", "Suscripciones", "TC", 89.00, "Mensual"),
    ("Gimnasio", "Salud y bienestar", "Tarjeta de debito", 180.00, "Mensual"),
    ("Cuota vivienda", "Vivienda", "Efectivo", 1200.00, "Mensual"),
    ("Respaldo nube", "Suscripciones", "TC", 240.00, "Anual"),
]

DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d+)\s+(.*)$")
AMOUNT_RE = re.compile(r"(-?Q[\d,]+\.\d{2})\s+(Q[\d,]+\.\d{2})$")
CARD_ENTRY_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\S+)\s+(.*?)\s+(-?(?:QTZ|DOL))\s+([\d,]+\.\d{2})$")
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
            "INSERT OR IGNORE INTO wedding_settings (key, value) VALUES ('budget', '60000')"
        )
        ensure_column(conn, "wedding_expenses", "attachment_name", "TEXT")
        ensure_column(conn, "wedding_expenses", "attachment_path", "TEXT")
        ensure_column(conn, "wedding_expenses", "attachment_mime", "TEXT")
        ensure_column(conn, "transactions", "attachment_name", "TEXT")
        ensure_column(conn, "transactions", "attachment_path", "TEXT")
        ensure_column(conn, "transactions", "attachment_mime", "TEXT")
        migrate_existing_data(conn)
        if not DEMO_MODE:
            migrate_wedding_data(conn)
        seed_recurring_expenses(conn)
        migrate_recurring_accounts(conn)
        if DEMO_MODE:
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
    sample_expenses = DEMO_RECURRING_SAMPLE_EXPENSES if DEMO_MODE else RECURRING_SAMPLE_EXPENSES
    conn.executemany(
        """
        INSERT INTO recurring_expenses
        (name, category, account, amount, frequency, next_due_date, active, created_at)
        VALUES (?, ?, ?, ?, ?, NULL, 1, ?)
        """,
        [(*expense, now) for expense in sample_expenses],
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
    finally:
        legacy.close()


def seed_examples(conn: sqlite3.Connection) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    rows = [
        ("2026-06-01", "Ingreso", "Sueldo GYT", "Sueldo depositado en GYT", "GYT - Cuenta ahorro sueldo", 4500, None, now),
        ("2026-06-15", "Ingreso", "Sueldo BAC USD", "Sueldo depositado en BAC USD", "BAC - Cuenta ahorro USD", 2500, None, now),
        ("2026-06-20", "Ahorro", "Ahorro Banrural", "Sobrante movido a Banrural", "Banrural - Cuenta ahorro", 1000, None, now),
        ("2026-06-22", "Venta USD", "Venta USD", "Venta manual de dolares", "Banrural - Cuenta ahorro", 1500, None, now),
        ("2026-06-02", "Gasto", "Alquiler / vivienda", "Renta", "GYT - Cuenta ahorro sueldo", 1500, None, now),
        ("2026-06-03", "Gasto", "Supermercado", "Compra semanal", "GYT - Tarjeta credito", 420, None, now),
        ("2026-06-05", "Gasto", "Transporte", "Gasolina / bus", "Efectivo", 180, None, now),
    ]
    conn.executemany(
        """
        INSERT INTO transactions
        (date, type, category, description, account, amount, source_import_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
        return "Ahorro"
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
            if not line or line in {"1 2", "1 2 3"}:
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
        if not line or line in {"1", "1 2", "1 2 3"}:
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
        is_credit = "CREDITO" in desc_upper and "DEBITO" not in desc_upper and not currency.startswith("-")
        signed_amount = amount if is_credit else -amount
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
        "DÉBITO",
        "RETIRO",
        "COMPRA",
        "CONSUMO",
        "PAGO",
        "CARGO",
        "COMISION",
        "COMISIÓN",
    )
    positive_tokens = (
        "CREDITO",
        "CRÉDITO",
        "DEPOSITO",
        "DEPÓSITO",
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
    text = data.decode("utf-8-sig", errors="replace")
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
        desc = first(lowered, "descripcion", "descripción", "descripcion_banco", "detalle", "concepto", "comercio")
        doc = first(lowered, "documento", "doc", "referencia", "no documento")
        saldo = money_to_number(first(lowered, "saldo", "balance"))
        monto = money_to_number(first(lowered, "monto", "amount", "importe", "valor"))
        if monto == 0:
            credito = money_to_number(first(lowered, "credito", "crédito", "creditos", "créditos", "abono"))
            debito = money_to_number(first(lowered, "debito", "débito", "debitos", "débitos", "cargo"))
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
                "suggested_category": first(lowered, "categoria", "categoría") or suggest_category(desc, monto),
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
                 suggested_category, amount, balance, action, notes, created_at)
                VALUES
                (:source_name, :bank, :product, :account, :document, :date, :description,
                 :suggested_type, :suggested_category, :amount, :balance, :action, :notes, :created_at)
                """,
                {**row, "created_at": now},
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
            ORDER BY e.date DESC, e.id DESC
            """
        ).fetchall()
    expenses = [serialize_wedding_expense(row) for row in rows]
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
        "accounts": RECURRING_ACCOUNTS,
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


def save_wedding_attachment(expense_id: int, file: dict) -> tuple[str, Path, str]:
    original_name = safe_filename(file.get("filename", "archivo"))
    suffix = Path(original_name).suffix.lower()
    allowed = {".pdf", ".png", ".jpg", ".jpeg", ".jfif", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
    if suffix not in allowed:
        raise ValueError("Solo se permiten archivos PDF o imagenes.")
    mime = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    if suffix == ".pdf":
        mime = "application/pdf"
    elif not mime.startswith("image/"):
        mime = "image/jpeg"
    file_path = WEDDING_FILES / f"{expense_id}_{original_name}"
    file_path.write_bytes(file.get("data", b""))
    return original_name, file_path, mime


def save_house_attachment(payment_id: int, file: dict) -> tuple[str, Path, str]:
    original_name = safe_filename(file.get("filename", "archivo"))
    suffix = Path(original_name).suffix.lower()
    allowed = {".pdf", ".png", ".jpg", ".jpeg", ".jfif", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
    if suffix not in allowed:
        raise ValueError("Solo se permiten archivos PDF o imagenes.")
    mime = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    if suffix == ".pdf":
        mime = "application/pdf"
    elif not mime.startswith("image/"):
        mime = "image/jpeg"
    file_path = HOUSE_FILES / f"{payment_id}_{original_name}"
    file_path.write_bytes(file.get("data", b""))
    return original_name, file_path, mime


def save_transaction_attachment(transaction_id: int, file: dict) -> tuple[str, Path, str]:
    original_name = safe_filename(file.get("filename", "archivo"))
    suffix = Path(original_name).suffix.lower()
    allowed = {".pdf", ".png", ".jpg", ".jpeg", ".jfif", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
    if suffix not in allowed:
        raise ValueError("Solo se permiten archivos PDF o imagenes.")
    mime = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    if suffix == ".pdf":
        mime = "application/pdf"
    elif not mime.startswith("image/"):
        mime = "image/jpeg"
    file_path = TRANSACTION_FILES / f"{transaction_id}_{original_name}"
    file_path.write_bytes(file.get("data", b""))
    return original_name, file_path, mime


def delete_wedding_attachment(relative_path: str | None) -> None:
    if not relative_path:
        return
    file_path = (DATA / relative_path).resolve()
    try:
        file_path.relative_to(WEDDING_FILES.resolve())
    except ValueError:
        return
    file_path.unlink(missing_ok=True)


def delete_house_attachment(relative_path: str | None) -> None:
    if not relative_path:
        return
    file_path = (DATA / relative_path).resolve()
    try:
        file_path.relative_to(HOUSE_FILES.resolve())
    except ValueError:
        return
    file_path.unlink(missing_ok=True)


def delete_transaction_attachment(relative_path: str | None) -> None:
    if not relative_path:
        return
    file_path = (DATA / relative_path).resolve()
    try:
        file_path.relative_to(TRANSACTION_FILES.resolve())
    except ValueError:
        return
    file_path.unlink(missing_ok=True)


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
            self.send_json({"ok": False, "message": "Usuario o contraseña incorrectos"}, status=401)
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

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self.require_auth(parsed.path):
            return
        if parsed.path == "/api/login":
            self.handle_login()
        elif parsed.path == "/api/logout":
            self.handle_logout()
        elif parsed.path == "/api/import":
            self.handle_import()
        elif parsed.path == "/api/imports/update":
            body = self.read_json()
            self.update_import(body)
        elif parsed.path == "/api/imports/commit":
            self.commit_imports()
        elif parsed.path == "/api/transactions":
            body, file = self.read_transaction_payload()
            self.create_transaction(body, file)
        elif parsed.path == "/api/transactions/delete":
            body = self.read_json()
            self.delete_transactions(body.get("ids", []))
        elif parsed.path.startswith("/api/transactions/") and parsed.path.endswith("/attachment"):
            transaction_id = int(parsed.path.split("/")[3])
            _, file = self.read_transaction_payload()
            self.update_transaction_attachment(transaction_id, file)
        elif parsed.path == "/api/wedding/expenses":
            body, file = self.read_wedding_expense_payload()
            self.create_wedding_expense(body, file)
        elif parsed.path == "/api/wedding/sample-data":
            self.load_wedding_sample_data()
        elif parsed.path.startswith("/api/wedding/expenses/") and parsed.path.endswith("/payments"):
            expense_id = int(parsed.path.split("/")[4])
            body = self.read_json()
            self.create_wedding_payment(expense_id, body)
        elif parsed.path.startswith("/api/wedding/expenses/") and parsed.path.endswith("/attachment"):
            expense_id = int(parsed.path.split("/")[4])
            _, file = self.read_wedding_expense_payload()
            self.update_wedding_attachment(expense_id, file)
        elif parsed.path == "/api/house/payments":
            body, file = self.read_wedding_expense_payload()
            self.create_house_payment(body, file)
        elif parsed.path.startswith("/api/house/payments/") and parsed.path.endswith("/attachment"):
            payment_id = int(parsed.path.split("/")[4])
            _, file = self.read_wedding_expense_payload()
            self.update_house_attachment(payment_id, file)
        elif parsed.path == "/api/recurring/expenses":
            self.create_recurring_expense(self.read_json())
        elif parsed.path.startswith("/api/recurring/expenses/") and parsed.path.endswith("/toggle-paid"):
            expense_id = int(parsed.path.split("/")[4])
            self.toggle_recurring_paid(expense_id, self.read_json())
        else:
            self.send_error(404)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if not self.require_auth(parsed.path):
            return
        if parsed.path.startswith("/api/transactions/"):
            transaction_id = int(parsed.path.rsplit("/", 1)[-1])
            body = self.read_json()
            self.update_transaction(transaction_id, body)
        elif parsed.path == "/api/wedding/budget":
            body = self.read_json()
            self.update_wedding_budget(body)
        elif parsed.path.startswith("/api/recurring/expenses/"):
            expense_id = int(parsed.path.rsplit("/", 1)[-1])
            self.update_recurring_expense(expense_id, self.read_json())
        else:
            self.send_error(404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if not self.require_auth(parsed.path):
            return
        if parsed.path == "/api/imports":
            with db_connection() as conn:
                conn.execute("DELETE FROM imports")
            self.send_json({"ok": True})
        elif parsed.path.startswith("/api/transactions/"):
            transaction_id = int(parsed.path.rsplit("/", 1)[-1])
            self.delete_transaction(transaction_id)
        elif parsed.path.startswith("/api/wedding/expenses/"):
            expense_id = int(parsed.path.rsplit("/", 1)[-1])
            self.delete_wedding_expense(expense_id)
        elif parsed.path.startswith("/api/house/payments/"):
            payment_id = int(parsed.path.rsplit("/", 1)[-1])
            self.delete_house_payment(payment_id)
        elif parsed.path.startswith("/api/recurring/expenses/"):
            expense_id = int(parsed.path.rsplit("/", 1)[-1])
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
            with db_connection() as conn:
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
        elif path == "/api/dashboard":
            month = query.get("month", [datetime.now().strftime("%Y-%m")])[0]
            self.send_json(build_dashboard(month))
        elif path == "/api/exchange-rate":
            self.send_json(fetch_usd_gtq_rate())
        elif path == "/api/wedding/state":
            self.send_json(build_wedding_state())
        elif path.startswith("/api/wedding/expenses/") and path.endswith("/attachment"):
            expense_id = int(path.split("/")[4])
            self.serve_wedding_attachment(expense_id)
        elif path == "/api/house/state":
            month = query.get("month", [datetime.now().strftime("%Y-%m")])[0]
            self.send_json(build_house_state(month))
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

    def read_transaction_payload(self) -> tuple[dict, dict | None]:
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            fields, files = parse_multipart(self)
            file = files.get("attachment")
            if file and not file.get("filename"):
                file = None
            return fields, file
        return self.read_json(), None

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
                "SELECT attachment_path FROM transactions WHERE id=?",
                (transaction_id,),
            ).fetchone()
            cursor = conn.execute("DELETE FROM transactions WHERE id=?", (transaction_id,))
        if cursor.rowcount == 0:
            self.send_error(404, "Movimiento no encontrado")
        else:
            delete_transaction_attachment(row["attachment_path"] if row else None)
            self.send_json({"ok": True})

    def delete_transactions(self, transaction_ids: list) -> None:
        ids = [int(item) for item in transaction_ids if str(item).isdigit()]
        if not ids:
            self.send_error(400, "No hay movimientos seleccionados")
            return
        placeholders = ",".join("?" for _ in ids)
        with db_connection() as conn:
            rows = conn.execute(
                f"SELECT attachment_path FROM transactions WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
            cursor = conn.execute(f"DELETE FROM transactions WHERE id IN ({placeholders})", ids)
        for row in rows:
            delete_transaction_attachment(row["attachment_path"])
        self.send_json({"ok": True, "count": cursor.rowcount})

    def update_transaction(self, transaction_id: int, body: dict) -> None:
        tx_type = body.get("type", "Gasto")
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
        if tx_type == "Venta USD":
            details = []
            if usd_amount:
                details.append(f"USD {usd_amount}")
            if exchange_rate:
                details.append(f"TC {exchange_rate}")
            if details and "(" not in description:
                description = f"{description} ({', '.join(details)})"
        description = description[:75]
        with db_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE transactions
                SET date=?, type=?, category=?, description=?, account=?, amount=?
                WHERE id=?
                """,
                (date, tx_type, category, description, account, amount, transaction_id),
            )
        if cursor.rowcount == 0:
            self.send_error(404, "Movimiento no encontrado")
        else:
            self.send_json({"ok": True})

    def create_transaction(self, body: dict, file: dict | None = None) -> None:
        tx_type = body.get("type", "Gasto")
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
            cursor = conn.execute(
                """
                INSERT INTO transactions
                (date, type, category, description, account, amount, source_import_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (date, tx_type, category, description, account, amount, now),
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

    def commit_imports(self) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with db_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM imports
                WHERE action NOT IN ('Registrado', 'Ignorar / transferencia')
                ORDER BY date, id
                """
            ).fetchall()
            for row in rows:
                tx_type = row["suggested_type"]
                exists = conn.execute(
                    """
                    SELECT 1 FROM transactions
                    WHERE date=? AND type=? AND category=? AND account=? AND description=? AND amount=?
                    LIMIT 1
                    """,
                    (
                        row["date"],
                        tx_type,
                        row["suggested_category"],
                        row["account"],
                        row["description"],
                        row["amount"],
                    ),
                ).fetchone()
                if exists:
                    conn.execute("UPDATE imports SET action='Registrado' WHERE id=?", (row["id"],))
                    continue
                conn.execute(
                    """
                    INSERT INTO transactions
                    (date, type, category, description, account, amount, source_import_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["date"],
                        tx_type,
                        row["suggested_category"],
                        row["description"],
                        row["account"],
                        row["amount"],
                        row["id"],
                        now,
                    ),
                )
                conn.execute("UPDATE imports SET action='Registrado' WHERE id=?", (row["id"],))
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

    def create_wedding_expense(self, body: dict, file: dict | None = None) -> None:
        amount = float(body.get("amount") or 0)
        initial_payment = float(body.get("initialPayment") or 0)
        if amount <= 0:
            self.send_error(400, "El monto debe ser mayor a cero")
            return
        description = (body.get("description", "").strip() or "Gasto de boda")[:90]
        category = body.get("category") or "Otro"
        vendor = (body.get("vendor", "").strip())[:90]
        date = normalize_date(body.get("date", datetime.now().strftime("%Y-%m-%d")))
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
                conn.execute(
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
        self.send_json(build_wedding_state(), status=201)

    def create_wedding_payment(self, expense_id: int, body: dict) -> None:
        amount = float(body.get("amount") or 0)
        if amount <= 0:
            self.send_error(400, "El abono debe ser mayor a cero")
            return
        date = normalize_date(body.get("date", datetime.now().strftime("%Y-%m-%d")))
        note = (body.get("note", "").strip())[:90]
        now = datetime.now().isoformat(timespec="seconds")
        with db_connection() as conn:
            exists = conn.execute("SELECT id FROM wedding_expenses WHERE id=?", (expense_id,)).fetchone()
            if not exists:
                self.send_error(404, "Gasto de boda no encontrado")
                return
            conn.execute(
                """
                INSERT INTO wedding_payments
                (expense_id, date, amount, note, legacy_id, created_at)
                VALUES (?, ?, ?, ?, NULL, ?)
                """,
                (expense_id, date, amount, note, now),
            )
        self.send_json(build_wedding_state(), status=201)

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
            conn.execute("DELETE FROM wedding_payments WHERE expense_id=?", (expense_id,))
            cursor = conn.execute("DELETE FROM wedding_expenses WHERE id=?", (expense_id,))
        if cursor.rowcount == 0:
            self.send_error(404, "Gasto de boda no encontrado")
        else:
            delete_wedding_attachment(row["attachment_path"] if row else None)
            self.send_json({"ok": True})

    def load_wedding_sample_data(self) -> None:
        with db_connection() as conn:
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
        file_path = STATIC / ("index.html" if path in ("", "/") else path.lstrip("/"))
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


def build_dashboard(month: str) -> dict:
    with db_connection() as conn:
        txs = conn.execute("SELECT * FROM transactions WHERE substr(date,1,7)=? ORDER BY date", (month,)).fetchall()
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
        "balance": income - expenses - savings,
        "savingsRate": savings / income if income else 0,
        "byCategory": sorted(by_category.items(), key=lambda x: x[1], reverse=True),
        "byAccount": sorted(by_account.items(), key=lambda x: x[0]),
        "byBank": [{"bank": bank, **values} for bank, values in sorted(by_bank.items(), key=lambda x: x[0])],
        "transactions": [rowdict(row) for row in txs],
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
        rows = conn.execute(
            """
            SELECT *
            FROM transactions
            WHERE substr(date,1,7) BETWEEN ? AND ?
            ORDER BY date, id
            """,
            (first_month, last_month),
        ).fetchall()
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
    }
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


def build_report_xlsx(report: dict) -> bytes:
    sheets = report_rows(report)
    widths = {
        "Resumen": [28, 18, 18, 18, 14],
        "Bancos": [28, 16, 16, 16, 18, 16, 14],
        "Tendencia": [22, 16, 16, 16, 16],
        "Categorias": [34, 18],
        "Gastos principales": [14, 45, 22, 30, 16],
    }
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
    server.serve_forever()
