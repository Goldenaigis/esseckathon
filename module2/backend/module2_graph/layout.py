"""
M2 - Layout GEOMETRIQUE precalcule (peu couteux, positions figees).

Objectif : donner a chaque compte une position (x, y) STABLE, calculee en une
passe (pas de simulation de forces), pour un rendu WebGL fluide a ~7000 noeuds.

Strategie "la moins couteuse et la plus sure" :
  1. Detecter les communautes (Louvain, ~1-2 s sur 7000 noeuds) -> des amas de
     comptes qui transigent entre eux.
  2. Placer chaque communaute comme un ILOT sur un grand cercle (bien espaces).
  3. A l'interieur d'un ilot, disposer les noeuds en disque (spiral) ; les
     comptes a risque eleve plutot au centre de l'ilot (plus visibles).
  Repli automatique : si Louvain echoue/trop lent -> ANNEAUX par score de risque
  (a risque au centre, legitimes en peripherie). Instantane, deterministe.

Les positions sont renvoyees normalisees dans un repere ~[-500, 500].
"""
from __future__ import annotations

import math
from typing import Optional

import networkx as nx


def _to_simple_undirected(g: nx.MultiDiGraph) -> nx.Graph:
    u = nx.Graph()
    u.add_nodes_from(g.nodes())
    for a, b in g.edges():
        if a != b:
            u.add_edge(a, b)
    return u


def _disk_positions(nodes: list[str], scores: dict[str, int],
                    cx: float, cy: float, radius: float) -> dict[str, tuple]:
    """Place des noeuds dans un disque (spirale de Vogel), les plus a risque
    vers le centre pour les rendre saillants."""
    pos: dict[str, tuple] = {}
    # repartition HOMOGENE dans le disque (spirale de Vogel), sans biais de risque,
    # pour que les comptes a risque affiches en vue d'ensemble soient bien etales
    # (et non empiles au centre de l'ilot).
    nodes = list(nodes)
    golden = math.pi * (3 - math.sqrt(5))
    n = max(len(nodes), 1)
    for i, node in enumerate(nodes):
        r = radius * math.sqrt((i + 0.5) / n)
        a = i * golden
        pos[node] = (cx + r * math.cos(a), cy + r * math.sin(a))
    return pos


def layout_communities(g: nx.MultiDiGraph, scores: dict[str, int],
                       spread: float = 460.0) -> dict[str, tuple]:
    """Layout principal : ilots de communautes espaces sur un grand cercle."""
    u = _to_simple_undirected(g)
    comms = nx.community.louvain_communities(u, seed=1)
    comms = sorted(comms, key=len, reverse=True)

    k = len(comms)
    pos: dict[str, tuple] = {}
    # centres d'ilots repartis en 2D par spirale de Vogel (remplit le plan,
    # evite l'effet "arc" d'un simple cercle)
    golden = math.pi * (3 - math.sqrt(5))
    for idx, comm in enumerate(comms):
        cr = spread * math.sqrt((idx + 0.5) / max(k, 1))
        ca = idx * golden
        cx, cy = cr * math.cos(ca), cr * math.sin(ca)
        isl_r = min(130.0, 18.0 + 3.0 * math.sqrt(len(comm)))
        pos.update(_disk_positions(list(comm), scores, cx, cy, isl_r))

    # noeuds isoles eventuels
    for node in g.nodes():
        pos.setdefault(node, (0.0, 0.0))
    return pos


def layout_risk_rings(g: nx.MultiDiGraph, scores: dict[str, int],
                      spread: float = 460.0) -> dict[str, tuple]:
    """Repli : anneaux concentriques par score (a risque au centre)."""
    nodes = list(g.nodes())
    # plus le score est haut, plus on est pres du centre
    ordered = sorted(nodes, key=lambda n: scores.get(n, 0), reverse=True)
    pos: dict[str, tuple] = {}
    golden = math.pi * (3 - math.sqrt(5))
    n = max(len(ordered), 1)
    for i, node in enumerate(ordered):
        r = spread * math.sqrt((i + 0.5) / n)
        a = i * golden
        pos[node] = (r * math.cos(a), r * math.sin(a))
    return pos


def compute_layout(g: nx.MultiDiGraph, scores: dict[str, int]) -> dict[str, tuple]:
    """Point d'entree : Louvain, avec repli automatique sur les anneaux."""
    try:
        return layout_communities(g, scores)
    except Exception:
        return layout_risk_rings(g, scores)
