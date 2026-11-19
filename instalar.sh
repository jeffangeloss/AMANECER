#!/usr/bin/env bash
# Instala lo necesario en macOS o Linux. Uso: ./instalar.sh
set -euo pipefail
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Falta Python 3: https://www.python.org/downloads/"; exit 1; }
python3 -m venv .venv
.venv/bin/pip install --upgrade -r requirements.txt
if [ ! -d "/Applications/Google Chrome.app" ] && ! command -v google-chrome >/dev/null; then
  echo "Falta Google Chrome: instalalo desde https://www.google.com/chrome/ antes de usar bb-todo."
  exit 1
fi
echo; echo "Listo. Ahora corre: ./bb-todo.sh"
