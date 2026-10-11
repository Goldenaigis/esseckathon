"""Chemins du projet et accès au contrat de données de l'équipe.

Le code vit pour l'instant en dehors du dépôt de l'équipe. Les imports sont
écrits sous la forme `fraudnet.shared.schema` : le jour où ce dossier est
déplacé dans le dépôt, la recherche de chemin ci-dessous devient inutile et
rien d'autre ne change.

Surcharge possible par variables d'environnement FRAUDNET_REPO et FRAUDNET_DATA.
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = PROJECT_ROOT / "ml" / "artifacts"
PROCESSED = PROJECT_ROOT / "data" / "processed"

_CLONE = PROJECT_ROOT.parent / "esseckathon-v2" / "esseckathon"


def _locate_repo():
    override = os.environ.get("FRAUDNET_REPO")
    if override:
        return Path(override)
    # Cas où ce dossier a été déplacé dans le dépôt de l'équipe, en module3/ :
    # le paquet fraudnet est alors dans le dossier esseckathon/ voisin.
    for candidat in (PROJECT_ROOT, PROJECT_ROOT.parent / "esseckathon"):
        if (candidat / "fraudnet" / "shared" / "schema.py").exists():
            return candidat
    return _CLONE


REPO_ROOT = _locate_repo()
DATA_DIR = Path(os.environ.get("FRAUDNET_DATA", REPO_ROOT / "fraudnet" / "data"))

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def require_data():
    missing = [
        name
        for name in ("transactions.csv", "accounts.csv", "scenarios.csv", "decoys.csv", "persons.csv")
        if not (DATA_DIR / name).exists()
    ]
    if missing:
        raise FileNotFoundError(
            f"Fichiers manquants dans {DATA_DIR} : {missing}.\n"
            f"Clone le dépôt de l'équipe ou pointe FRAUDNET_DATA vers son dossier data."
        )
    return DATA_DIR
