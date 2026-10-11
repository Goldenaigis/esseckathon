#!/usr/bin/env bash
# Lance le prototype Module 2 (cartographie) de bout en bout.
#   1) genere la base de donnees jouet si absente
#   2) demarre le serveur FastAPI (API + front)
set -e
cd "$(dirname "$0")"

# Interpreteur : python3 (Linux/macOS), sinon python, sinon py (lanceur Windows).
# On ECARTE les faux binaires qui ne lancent rien (stub Microsoft Store sous
# Windows : `python`/`python3` existent dans le PATH mais sortent en erreur).
# Surcharge possible : PYTHON=/chemin/vers/python ./run.sh
if [ -z "${PYTHON:-}" ]; then
  for cand in python3 python py; do
    if command -v "$cand" >/dev/null 2>&1 \
       && "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
          >/dev/null 2>&1; then
      PYTHON="$cand"
      break
    fi
  done
fi
if [ -z "${PYTHON:-}" ]; then
  echo "Aucun Python 3.10+ utilisable trouve dans le PATH." >&2
  echo "Relancez avec : PYTHON=/chemin/vers/python ./run.sh" >&2
  exit 1
fi
echo "Interpreteur : $PYTHON ($("$PYTHON" -c 'import sys; print(sys.version.split()[0])'))"

# sortie UTF-8 garantie (consoles Windows en cp1252 sinon)
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

if [ ! -f data/bank.db ]; then
  echo "Generation des donnees jouet..."
  "$PYTHON" -m backend.module1_data.fixtures --seed 42
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
echo "Serveur sur http://${HOST}:${PORT}"
exec "$PYTHON" -m uvicorn backend.app:app --host "$HOST" --port "$PORT"
