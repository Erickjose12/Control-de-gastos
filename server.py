from __future__ import annotations

import csv
import io
import json
import mimetypes
import re
import sqlite3
import tempfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
DATA = ROOT / "data"
DB = DATA / "finanzas.db"
WEDDING_FILES = DATA / "wedding_files"
EXCHANGE_RATE_URL = "https://open.er-api.com/v6/latest/USD"
LEGACY_WEDDING_DB = ROOT.parent / "Control-de-gastos-de-boda" / "data" / "boda.db"

ACCOUNTS = [
    "GYT - Cuenta ahorro sueldo",
    "GYT - Tarjeta debito",
    "GYT - Tarjeta credito",
    "BAC - Cuenta ahorro USD",
    "Banrural - Cuenta ahorro",
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
TRANSFER_CATEGORIES = ["Pago tarjeta", "Transferencia entre cuentas", "Retiro efectivo"]
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

DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d+)\s+(.*)$")
AMOUNT_RE = re.compile(r"(-?Q[\d,]+\.\d{2})\s+(Q[\d,]+\.\d{2})$")


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
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO wedding_settings (key, value) VALUES ('budget', '60000')"
        )
        ensure_column(conn, "wedding_expenses", "attachment_name", "TEXT")
        ensure_column(conn, "wedding_expenses", "attachment_path", "TEXT")
        ensure_column(conn, "wedding_expenses", "attachment_mime", "TEXT")
        migrate_existing_data(conn)
        migrate_wedding_data(conn)


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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
    return "Cuenta ahorro / debito"


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


def parse_gyt_pdf(path: Path, source_name: str) -> list[dict]:
    if PdfReader is None:
        raise RuntimeError("pypdf no esta disponible")

    reader = PdfReader(str(path))
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
    with db_connection() as conn:
        conn.executemany(
            """
            INSERT INTO imports
            (source_name, bank, product, account, document, date, description, suggested_type,
             suggested_category, amount, balance, action, notes, created_at)
            VALUES
            (:source_name, :bank, :product, :account, :document, :date, :description,
             :suggested_type, :suggested_category, :amount, :balance, :action, :notes, :created_at)
            """,
            [{**row, "created_at": now} for row in rows],
        )
    return len(rows)


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
        "has_attachment": bool(row["attachment_path"]),
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


def safe_filename(value: str) -> str:
    name = Path(value).name.strip() or "archivo"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120]


def save_wedding_attachment(expense_id: int, file: dict) -> tuple[str, Path, str]:
    original_name = safe_filename(file.get("filename", "archivo"))
    suffix = Path(original_name).suffix.lower()
    allowed = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
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


def delete_wedding_attachment(relative_path: str | None) -> None:
    if not relative_path:
        return
    file_path = (DATA / relative_path).resolve()
    try:
        file_path.relative_to(WEDDING_FILES.resolve())
    except ValueError:
        return
    file_path.unlink(missing_ok=True)


class App(BaseHTTPRequestHandler):
    server_version = "FinanzasLocal/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed.path, parse_qs(parsed.query))
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/import":
            self.handle_import()
        elif parsed.path == "/api/imports/update":
            body = self.read_json()
            self.update_import(body)
        elif parsed.path == "/api/imports/commit":
            self.commit_imports()
        elif parsed.path == "/api/transactions":
            body = self.read_json()
            self.create_transaction(body)
        elif parsed.path == "/api/transactions/delete":
            body = self.read_json()
            self.delete_transactions(body.get("ids", []))
        elif parsed.path == "/api/wedding/expenses":
            body, file = self.read_wedding_expense_payload()
            self.create_wedding_expense(body, file)
        elif parsed.path == "/api/wedding/sample-data":
            self.load_wedding_sample_data()
        elif parsed.path.startswith("/api/wedding/expenses/") and parsed.path.endswith("/payments"):
            expense_id = int(parsed.path.split("/")[4])
            body = self.read_json()
            self.create_wedding_payment(expense_id, body)
        else:
            self.send_error(404)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/transactions/"):
            transaction_id = int(parsed.path.rsplit("/", 1)[-1])
            body = self.read_json()
            self.update_transaction(transaction_id, body)
        elif parsed.path == "/api/wedding/budget":
            body = self.read_json()
            self.update_wedding_budget(body)
        else:
            self.send_error(404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
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
        else:
            self.send_error(404)

    def handle_api_get(self, path: str, query: dict) -> None:
        if path == "/api/meta":
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
        else:
            self.send_error(404)

    def handle_import(self) -> None:
        fields, files = parse_multipart(self)
        bank = fields.get("bank", "GYT")
        account = fields.get("account", "GYT - Cuenta ahorro sueldo")
        product = fields.get("product") or infer_product(account)
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
                rows = parse_gyt_pdf(tmp_path, name)
            finally:
                tmp_path.unlink(missing_ok=True)
        else:
            rows = parse_csv_upload(data, name, bank, product, account)
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
            cursor = conn.execute("DELETE FROM transactions WHERE id=?", (transaction_id,))
        if cursor.rowcount == 0:
            self.send_error(404, "Movimiento no encontrado")
        else:
            self.send_json({"ok": True})

    def delete_transactions(self, transaction_ids: list) -> None:
        ids = [int(item) for item in transaction_ids if str(item).isdigit()]
        if not ids:
            self.send_error(400, "No hay movimientos seleccionados")
            return
        placeholders = ",".join("?" for _ in ids)
        with db_connection() as conn:
            cursor = conn.execute(f"DELETE FROM transactions WHERE id IN ({placeholders})", ids)
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

    def create_transaction(self, body: dict) -> None:
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
            conn.execute(
                """
                INSERT INTO transactions
                (date, type, category, description, account, amount, source_import_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (date, tx_type, category, description, account, amount, now),
            )
        self.send_json({"ok": True})

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
    income = base_income + usd_sales
    expenses = sum(row["amount"] for row in txs if row["type"] == "Gasto")
    savings = sum(row["amount"] for row in txs if row["type"] == "Ahorro")
    transfers = sum(row["amount"] for row in txs if row["type"] == "Transferencia")
    by_category: dict[str, float] = {}
    by_account: dict[str, float] = {}
    for row in txs:
        if row["type"] == "Gasto":
            by_category[row["category"]] = by_category.get(row["category"], 0) + row["amount"]
        account_delta = row["amount"] if row["type"] in ("Ingreso", "Ahorro", "Venta USD") else -row["amount"]
        by_account[row["account"]] = by_account.get(row["account"], 0) + account_delta
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
        "transactions": [rowdict(row) for row in txs],
    }


if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", 8765), App)
    print("Finanzas Local en http://127.0.0.1:8765")
    server.serve_forever()
