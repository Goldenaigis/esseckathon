"""
M2 - Extraction de sous-graphes pour l'affichage.

Cytoscape devient illisible / lent au-dela de ~1000-2000 noeuds. On ne renvoie
donc JAMAIS tout le graphe : on extrait soit l'ego-network d'un compte, soit
les comptes les plus a risque.
"""
from __future__ import annotations

import networkx as nx


def ego_network(g: nx.MultiDiGraph, account_id: str, radius: int = 1) -> nx.MultiDiGraph:
    """Flux entrants/sortants autour d'un compte, jusqu'a `radius` sauts."""
    if account_id not in g:
        return nx.MultiDiGraph()
    # ego_graph suit par defaut les aretes sortantes ; on veut les deux sens.
    undirected_reach = nx.ego_graph(g.to_undirected(as_view=True),
                                    account_id, radius=radius)
    nodes = set(undirected_reach.nodes())
    return g.subgraph(nodes).copy()


def top_risk_subgraph(g: nx.MultiDiGraph, scores: dict[str, float],
                      top_n: int = 15, radius: int = 1) -> nx.MultiDiGraph:
    """
    Prend les `top_n` comptes au plus haut score, puis ajoute leur voisinage
    immediat pour que les structures (etoiles, chaines) restent lisibles.
    """
    if not g.number_of_nodes():
        return nx.MultiDiGraph()
    ranked = sorted(g.nodes(), key=lambda n: scores.get(n, 0.0), reverse=True)
    seeds = ranked[:top_n]
    keep: set[str] = set(seeds)
    und = g.to_undirected(as_view=True)
    for s in seeds:
        keep.update(nx.ego_graph(und, s, radius=radius).nodes())
    return g.subgraph(keep).copy()
