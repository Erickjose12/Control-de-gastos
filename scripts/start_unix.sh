#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/python" ]; then
  echo "Creando entorno virtual..."
  if command -v python3 >/dev/null 2>&1; then
    python3 -m venv .venv
  else
    echo "No encontre python3. Instala Python 3.10 o superior."
    exit 1
  fi
fi

echo "Instalando dependencias..."
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

echo "Iniciando Finanzas Local en http://127.0.0.1:8765"
./.venv/bin/python server.py
