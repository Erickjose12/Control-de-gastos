import json
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        server.DATA = Path(tmp)
        server.DB = server.DATA / "finanzas.db"
        server.init_db()
        with server.db_connection() as conn:
            server.seed_examples(conn)
        dashboard = server.build_dashboard("2026-06")
        assert dashboard["income"] == 8500.0
        assert dashboard["expenses"] == 2100.0
        assert dashboard["savings"] == 1000.0
        assert dashboard["balance"] == 5400.0
        print(json.dumps({"ok": True, "dashboard": dashboard["month"]}))


if __name__ == "__main__":
    main()
