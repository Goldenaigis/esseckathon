#!/usr/bin/env bash
# Lance le prototype Module 2 (cartographie) de bout en bout.
#   1) genere la base de donnees jouet si absente
#   2) demarre le serveur FastAPI (API + front)
set -e
cd "$(dirname "$0")"

if [ ! -f data/bank.db ]; then
  echo "Generation des donnees jouet..."
  python3 -m backend.module1_data.fixtures --seed 42
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
echo "Serveur sur http://${HOST}:${PORT}"
exec python3 -m uvicorn backend.app:app --host "$HOST" --port "$PORT"
