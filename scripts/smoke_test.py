import json
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        # Redirigimos todas las rutas del modulo al temporal para que el test
        # sea hermetico y no cree carpetas dentro del repo.
        server.DATA = data
        server.DB = data / "finanzas.db"
        server.WEDDING_FILES = data / "wedding_files"
        server.HOUSE_FILES = data / "house_files"
        server.TRANSACTION_FILES = data / "transaction_files"
        server.init_db()
        with server.db_connection() as conn:
            server.seed_examples(conn)
        dashboard = server.build_dashboard("2026-06")

        # Totales operativos: el dashboard excluye la cuenta de ahorro (Banrural),
        # por eso el Ahorro y la Venta USD sembrados en esa cuenta no suman aqui.
        assert dashboard["income"] == 7000.0, dashboard["income"]
        assert dashboard["expenses"] == 2100.0, dashboard["expenses"]
        assert dashboard["savings"] == 0, dashboard["savings"]
        assert dashboard["balance"] == 4900.0, dashboard["balance"]

        # La separacion de la cuenta de ahorro es la logica que se debe blindar:
        # esos movimientos viven en savingsTransactions, no en los totales.
        savings_txs = dashboard["savingsTransactions"]
        assert len(savings_txs) == 2, len(savings_txs)
        assert sum(tx["amount"] for tx in savings_txs) == 2500.0

        print(json.dumps({"ok": True, "dashboard": dashboard["month"]}))


if __name__ == "__main__":
    main()
