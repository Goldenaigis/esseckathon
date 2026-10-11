"""
M2 - Score de risque PROVISOIRE (mock M3).

Tant que l'equipe M3 (ML) ne fournit pas de scores, on calcule un score
heuristique 0..100 a partir des features de graphe, pour que la cartographie
soit coloree de maniere credible.

>>> A REMPLACER par les scores reels de M3 <<<
Le format de sortie (dict account_id -> int 0..100) est le CONTRAT : quand M3
livre, on substitue la source sans toucher au front ni a l'export Cytoscape.
"""
from __future__ import annotations


def heuristic_account_scores(features: dict[str, dict]) -> dict[str, int]:
    """Score heuristique explicable, borne a [0, 100]."""
    scores: dict[str, int] = {}
    for acc, f in features.items():
        s = 0.0
        # fan-in massif (collecte)
        s += min(f["fan_in"], 30) * 2.0
        # redistribution rapide apres collecte
        if f["fan_in"] >= 8 and f["redistribution_speed_min"] is not None:
            if f["redistribution_speed_min"] <= 180:
                s += 25
        # appartenance a un cycle
        if f["in_cycle"]:
            s += 20
        # role de pont (betweenness eleve)
        s += min(f["betweenness"] * 100, 15)
        # fractionnement (smurfing) : entrees nombreuses, similaires, d'un meme compte
        if f.get("same_amount_inflow") and f.get("distinct_senders", 99) <= 2 \
                and f["fan_in"] >= 8:
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
