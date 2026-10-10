"""
M2 - Features de reseau par compte.

Ces features servent DEUX consommateurs :
  1. M3 (ML)  : elles enrichissent le modele (fan-in, centralite, cycle...).
  2. M2 (visu): elles pilotent le rendu (taille/couleur des noeuds, roles).

Chaque feature correspond a une "brique" mesurable :
  - DEGRE      : fan_in, fan_out, in_out_ratio      -> etoiles, eventails
  - CHEMINS    : betweenness, in_cycle, chain_len   -> ponts, cycles, chaines
  - TEMPOREL   : redistribution_speed_min           -> redistribution rapide

ANTI-FUITE : on n'utilise jamais is_fraud / scenario_id pour calculer une
feature. Ces champs ne servent qu'a l'evaluation / la coloration demo.

Pour M3 : appeler compute_account_features() sur un sous-ensemble (train/test)
en passant un graphe deja filtre -> pas de fuite entre les splits.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import networkx as nx


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _simple_digraph(g: nx.MultiDiGraph) -> nx.DiGraph:
    """
    Reduit le MultiDiGraph en DiGraph simple (une arete par couple),
    en agregeant montant/nombre + garde le 1er timestamp et le montant max.
    Utile pour les algos de chemins/cycles.
    """
    simple = nx.DiGraph()
    simple.add_nodes_from(g.nodes(data=True))
    for u, v, d in g.edges(data=True):
        amt = d.get("amount", 0.0)
        ts = _parse(d.get("timestamp"))
        if simple.has_edge(u, v):
            simple[u][v]["weight"] += 1
            simple[u][v]["amount"] += amt
            simple[u][v]["max_amount"] = max(simple[u][v]["max_amount"], amt)
            if ts and (simple[u][v]["ts"] is None or ts < simple[u][v]["ts"]):
                simple[u][v]["ts"] = ts
        else:
            simple.add_edge(u, v, weight=1, amount=amt, max_amount=amt, ts=ts)
    return simple


def _is_laundering_cycle(simple: nx.DiGraph, cyc: list[str]) -> bool:
    """
    Un cycle est juge "suspect" (blanchiment) s'il est TEMPOREL et REGULIER :
      - les transferts s'enchainent dans le temps autour de la boucle,
      - les montants sont du meme ordre de grandeur (ratio max/min <= 3).
    Cela ecarte les cycles fortuits du trafic legitime.
    """
    n = len(cyc)
    edges = [simple[cyc[i]][cyc[(i + 1) % n]] for i in range(n)]
    if any(e["ts"] is None for e in edges):
        return False
    amounts = [e["max_amount"] for e in edges if e["max_amount"] > 0]
    if not amounts:
        return False
    if max(amounts) / max(min(amounts), 1e-9) > 1.25:
        return False
    # au moins un ordre temporel coherent le long de la boucle
    ts = [e["ts"] for e in edges]
    rotations_increasing = any(
        all(ts[(k + j) % n] <= ts[(k + j + 1) % n] for j in range(n - 1))
        for k in range(n)
    )
    return rotations_increasing


def _redistribution_speed(g: nx.MultiDiGraph, node: str) -> Optional[float]:
    """
    Delai (minutes) entre la DERNIERE reception et le PREMIER renvoi.
    Petit delai + gros fan-in => "collecte puis redistribution rapide".
    """
    in_times = [_parse(d.get("timestamp")) for _, _, d in g.in_edges(node, data=True)]
    out_times = [_parse(d.get("timestamp")) for _, _, d in g.out_edges(node, data=True)]
    in_times = [t for t in in_times if t]
    out_times = [t for t in out_times if t]
    if not in_times or not out_times:
        return None
    last_in = max(in_times)
    first_out_after = [t for t in out_times if t >= last_in]
    ref_out = min(first_out_after) if first_out_after else min(out_times)
    return round((ref_out - last_in).total_seconds() / 60.0, 1)


def _classify_role(feats: dict) -> str:
    """Heuristique de role (sert le rendu + le resume d'alerte)."""
    fi, fo = feats["fan_in"], feats["fan_out"]
    speed = feats["redistribution_speed_min"]
    if feats["in_cycle"]:
        return "cycle_member"
    if fi >= 10 and fo <= 4 and speed is not None and speed <= 180:
        return "collector_redistributor"   # sablier
    if fi >= 10 and fo == 0:
        return "collector"                 # etoile de collecte
    if fo >= 10 and fi <= 2:
        return "distributor"               # eventail / smurfing
    if fi == 1 and fo == 1:
        return "relay"                     # maillon de chaine
    return "normal"


def compute_account_features(g: nx.MultiDiGraph) -> dict[str, dict]:
    """
    Renvoie { account_id : { feature: valeur, ... } }.

    Features (toutes derivables sans la verite terrain) :
      fan_in, fan_out, distinct_senders, distinct_receivers,
      in_out_ratio, total_in, total_out,
      degree_centrality, betweenness, in_cycle,
      redistribution_speed_min, role
    """
    simple = _simple_digraph(g)

    # centralites (sur le graphe simple)
    deg_c = nx.degree_centrality(simple) if simple.number_of_nodes() else {}
    try:
        betw = nx.betweenness_centrality(simple) if simple.number_of_nodes() else {}
    except Exception:
        betw = {n: 0.0 for n in simple.nodes()}

    # cycles (sur le graphe simple). On ne retient que les cycles COURTS
    # (3 a 6 comptes) : ce sont les cycles de blanchiment typiques. Les tres
    # longs cycles sont le plus souvent du bruit du graphe legitime.
    in_cycle: set[str] = set()
    try:
        for cyc in nx.simple_cycles(simple):
            if 3 <= len(cyc) <= 6 and _is_laundering_cycle(simple, cyc):
                in_cycle.update(cyc)
    except Exception:
        pass

    feats: dict[str, dict] = {}
    for node in g.nodes():
        in_edges = list(g.in_edges(node, data=True))
        out_edges = list(g.out_edges(node, data=True))
        distinct_senders = len({u for u, _, _ in in_edges})
        distinct_receivers = len({v for _, v, _ in out_edges})
        total_in = round(sum(d.get("amount", 0.0) for _, _, d in in_edges), 2)
        total_out = round(sum(d.get("amount", 0.0) for _, _, d in out_edges), 2)
        fan_in = len(in_edges)
        fan_out = len(out_edges)

        f = {
            "fan_in": fan_in,
            "fan_out": fan_out,
            "distinct_senders": distinct_senders,
            "distinct_receivers": distinct_receivers,
            "in_out_ratio": round(fan_in / fan_out, 2) if fan_out else float(fan_in),
            "total_in": total_in,
            "total_out": total_out,
            "degree_centrality": round(deg_c.get(node, 0.0), 4),
            "betweenness": round(betw.get(node, 0.0), 4),
            "in_cycle": node in in_cycle,
            "redistribution_speed_min": _redistribution_speed(g, node),
        }
        f["role"] = _classify_role(f)
        feats[node] = f
    return feats


if __name__ == "__main__":
    import os
    from backend.module2_graph.build_graph import build_graph

    graph = build_graph(os.path.join("data", "bank.db"))
    fs = compute_account_features(graph)
    # affiche les comptes les plus "interessants"
    ranked = sorted(fs.items(), key=lambda kv: kv[1]["fan_in"], reverse=True)
    print("Top comptes par fan-in :")
    for acc, f in ranked[:6]:
        print(f"  {acc}  role={f['role']:<24} fan_in={f['fan_in']:<3} "
              f"fan_out={f['fan_out']:<3} redis={f['redistribution_speed_min']}")
