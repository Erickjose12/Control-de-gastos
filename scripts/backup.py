"""Respaldo completo de los datos de Finanzas Local.

Copia la base de datos (via la API de backup de sqlite3, segura aunque el
servidor este corriendo) y todas las carpetas de adjuntos, y deja todo
comprimido en un unico .zip con marca de fecha/hora dentro de backups/.

Uso:
    .venv\\Scripts\\python.exe scripts\\backup.py

Respeta las mismas variables de entorno que server.py (FINANZAS_DATA_DIR,
FINANZAS_DEMO), asi que respalda exactamente los datos que el servidor
esta usando en ese momento. Por defecto conserva los ultimos 30 respaldos
y borra los mas viejos.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server  # noqa: E402

BACKUP_DIR = Path(server.os.environ.get("FINANZAS_BACKUP_DIR", ROOT / "backups"))
KEEP_LAST = int(server.os.environ.get("FINANZAS_BACKUP_KEEP", "30"))


def backup_database(dest_dir: Path) -> None:
    if not server.DB.exists():
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(server.DB)
    try:
        target = sqlite3.connect(dest_dir / server.DB.name)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def backup_folder(source_dir: Path, dest_dir: Path) -> None:
    if not source_dir.exists():
        return
    shutil.copytree(source_dir, dest_dir / source_dir.name, dirs_exist_ok=True)


def prune_old_backups() -> None:
    if not BACKUP_DIR.exists():
        return
    zips = sorted(BACKUP_DIR.glob("finanzas-backup-*.zip"), key=lambda p: p.name)
    excess = len(zips) - KEEP_LAST
    for old in zips[:excess]:
        old.unlink(missing_ok=True)


def main() -> None:
    if not server.DATA.exists():
        print(f"No existe la carpeta de datos ({server.DATA}); nada que respaldar.")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    staging_dir = BACKUP_DIR / f"_staging_{timestamp}"
    staging_dir.mkdir(parents=True, exist_ok=True)

    try:
        backup_database(staging_dir)
        backup_folder(server.WEDDING_FILES, staging_dir)
        backup_folder(server.HOUSE_FILES, staging_dir)
        backup_folder(server.TRANSACTION_FILES, staging_dir)

        zip_path = BACKUP_DIR / f"finanzas-backup-{timestamp}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for file_path in staging_dir.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(staging_dir))
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    prune_old_backups()

    size_kb = zip_path.stat().st_size / 1024
    print(f"Respaldo guardado en: {zip_path} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
