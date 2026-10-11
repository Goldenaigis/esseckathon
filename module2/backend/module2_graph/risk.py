"""
M2 - Score de risque PROVISOIRE (mock M3).

Tant que l'equipe M3 (ML) ne fournit pas de scores, on calcule un score
heuristique 0..100 a partir des features de graphe, pour que la cartographie
soit coloree de maniere credible.

>>> A REMPLACER par les scores reels de M3 <<<
Le format de sortie (dict account_id -> int 0..100) est le CONTRAT : quand M3
livre, on substitue la source sans toucher au front ni a l'export WebGL
(cf. load_m3_scores ci-dessous et le branchement dans backend/app.py).
"""
from __future__ import annotations

import json
import os

# Artefact de M3 : { account_id : int 0..100 }. Chemin surchargeable.
# _HERE = <racine>/module2/backend/module2_graph  ->  3 remontees = <racine>
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
DEFAULT_M3_SCORES = os.environ.get(
    "M3_SCORES",
    os.path.join(_REPO_ROOT, "module3", "ml", "artifacts", "account_scores.json"),
)


def load_m3_scores(path: str = DEFAULT_M3_SCORES) -> "dict[str, int] | None":
    """
    Charge les scores reels de M3 ({account_id: 0..100}), ou None si l'artefact
    est absent / illisible / hors contrat. Les comptes absents du fichier ne
    sont pas inventes : l'appelant leur laissera la valeur par defaut 0.

    Verifie au 2026-10-11 sur l'artefact M3 reel : 7052 comptes sur les 7060 de
    M1, entiers de 0 a 100, aucune clef inconnue -> le format colle.
    """
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict) or not raw:
            return None
        return {str(k): int(max(0, min(100, round(float(v))))) for k, v in raw.items()}
    except (OSError, ValueError, TypeError):
        return None


def heuristic_account_scores(features: dict[str, dict]) -> dict[str, int]:
    """
    Score heuristique explicable, borne a [0, 100].

    Le terme principal est la COLLECTE CONCENTREE (`inbound_burst` : entrees
    recues dans une meme fenetre de 6 h) et NON le fan-in brut. Mesure a l'appui :
    avec le fan-in brut, un gros compte legitime montait plus haut qu'une mule
    (AUC 0.34 sur M1, 0.43 sur les fixtures : pire que le hasard) ; avec la
    rafale, AUC 0.58 et precision@25 de 48 % contre 32 %.
    """
    scores: dict[str, int] = {}
    for acc, f in features.items():
        s = 0.0
        # collecte concentree (rafale d'entrees sur 6 h)
        burst = f.get("inbound_burst", 0)
        s += min(burst, 30) * 2.0
        # redistribution rapide apres collecte
        if burst >= 8 and f["redistribution_speed_min"] is not None:
            if f["redistribution_speed_min"] <= 180:
                s += 25
        # appartenance a un cycle (toujours False quand les features tournent
        # en mode fast : la detection de cycles y est sautee)
        if f["in_cycle"]:
            s += 20
        # role de pont (betweenness eleve ; 0 en mode fast)
        s += min(f["betweenness"] * 100, 15)
        # fractionnement (smurfing) : entrees nombreuses, similaires, d'un meme compte
        if f.get("same_amount_inflow") and f.get("distinct_senders", 99) <= 2 \
                and burst >= 8:
            s += 25
        scores[acc] = int(max(0, min(100, round(s))))
    return scores


def truth_account_scores(graph) -> dict[str, int]:
    """
    Score 0..100 derive de la VERITE TERRAIN de M1 (transitoire, en attendant M3).

    Mapping (categoriel -> echelle, compatible avec les seuils 50/25) :
      - fraudster / mule           -> 85  (rouge, >= 50)
      - victime (manipulee)        -> 40  (jaune, >= 25) : impliquee, pas coupable
      - leurre / decoy (trompeur)  -> 30  (jaune, >= 25) : legitime mais suspect
      - normal                     -> 5   (vert)

    >>> POINT DE BRANCHEMENT M3 <<<
    Quand M3 livre, on remplace cet appel par les scores reels du modele ;
    le format (dict account_id -> int 0..100) et les seuils ne changent pas.
    """
    scores: dict[str, int] = {}
    for node, attrs in graph.nodes(data=True):
        role = (attrs.get("truth_role") or "normal")
        if role in ("fraudster", "mule"):
            scores[node] = 85
        elif role == "victim":
            scores[node] = 40
        elif attrs.get("truth_is_decoy"):
            scores[node] = 30
        else:
            scores[node] = 5
    return scores
