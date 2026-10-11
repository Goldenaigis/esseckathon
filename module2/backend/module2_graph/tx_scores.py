"""
M2 - Chargement des scores M3 a la maille TRANSACTION (module3/ml/artifacts/scores.csv).

Pendant du module `risk.py`, qui charge les scores par COMPTE. Deux artefacts
distincts chez M3, deux chargeurs distincts ici : le front a besoin des deux a
la fois (coloration des noeuds par compte, coloration des aretes par virement).

Le fichier est volontairement PARTIEL : seul le perimetre scoré par M3
(`instrument == "credit_transfer"`, soit 52 824 des 151 770 transactions) y
figure. Les paiements par carte et les prelevements n'ont pas de score, et ce
n'est pas une anomalie a corriger : une arete sans score reste neutre.

Il est aussi ABSENT d'un clone frais du depot (exclu par le .gitignore de M3,
regenere par `module3/ml/score.py`). Tout doit donc fonctionner sans lui :
`load_m3_tx_scores` renvoie None, les champs `i`/`r` du payload valent null et
`/api/meta` remonte `tx_scores: false`.
"""
from __future__ import annotations

import csv
import os

# _HERE = <racine>/module2/backend/module2_graph  ->  3 remontees = <racine>
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_M3_TX_SCORES = os.environ.get(
    "M3_TX_SCORES",
    os.path.join(_REPO_ROOT, "module3", "ml", "artifacts", "scores.csv"),
)

# M3 concatene les phrases d'explication avec ce separateur (shared.schema
# .FACTOR_SEPARATOR). On ne le redefinit pas au hasard : il est aussi le
# separateur attendu par le front pour afficher une puce par facteur.
FACTOR_SEPARATOR = " | "

# Colonnes du contrat SCORES_COLUMNS de M1/M3. Un fichier qui ne les a pas
# toutes n'est pas celui qu'on attend : on refuse plutot que de deviner.
_REQUIRED = ("tx_id", "score_tx_only", "score_full", "risk_score",
             "risk_level", "top_factors")


def load_m3_tx_scores(path: str = DEFAULT_M3_TX_SCORES) -> "dict[str, tuple] | None":
    """
    Charge `scores.csv` en `{ tx_id: (risk_score, risk_level, score_tx_only,
    top_factors_brut) }`, ou None si le fichier est absent / illisible / hors
    contrat.

    On stocke un TUPLE et non un dict, et `top_factors` reste la chaine brute :
    52 824 entrees sont gardees en memoire pour toute la duree de vie du
    serveur, et un dict de 6 clefs par ligne y coutait plusieurs dizaines de
    Mo pour rien. Le decoupage sur FACTOR_SEPARATOR se fait a la requete, il ne
    concerne qu'une ligne a la fois.

    `score_full` n'est pas conserve : `risk_score` en est deja l'arrondi 0..100
    et aucun endpoint du contrat ne l'expose.
    """
    if not path or not os.path.exists(path):
        return None
    try:
        out: dict[str, tuple] = {}
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or any(
                    c not in reader.fieldnames for c in _REQUIRED):
                return None
            for r in reader:
                tx_id = r.get("tx_id")
                if not tx_id:
                    continue
                # borne defensive : le front colore en rouge au-dela de 50 et
                # ne doit jamais recevoir une valeur hors echelle.
                score = int(max(0, min(100, round(float(r["risk_score"])))))
                out[tx_id] = (
                    score,
                    r.get("risk_level") or None,
                    float(r["score_tx_only"]) if r.get("score_tx_only") else None,
                    r.get("top_factors") or "",
                )
        return out or None
    except (OSError, ValueError, TypeError, csv.Error):
        return None


def split_factors(raw: str) -> list[str]:
    """Chaine `top_factors` de M3 -> liste de phrases, vide si rien."""
    if not raw:
        return []
    return [p.strip() for p in raw.split(FACTOR_SEPARATOR) if p.strip()]
