"""
M2 - Serialisation COMPACTE du graphe pour le rendu WebGL (Sigma.js).

Contrairement a to_cytoscape (sous-graphe riche), ici on envoie TOUT le graphe
(~7000 noeuds) mais en payload minimal, car :
  - le layout (positions) est calcule cote navigateur (graphology + ForceAtlas2),
  - la timeline a besoin du timestamp de chaque lien,
  - au-dela de ~80k liens le rendu sature -> on AGREGE les transactions
    paralleles (meme couple src->dst) en un seul lien.

Format (clefs courtes = payload plus leger) :
  {
    "nodes": [ { "id", "s"(score), "r"(role), "ci"(country),
                 "ct"(customer_type), "fi"(fan_in), "fo"(fan_out) } ],
    "edges": [ { "s"(src), "t"(dst), "ts"(1er timestamp), "m"(montant cumule),
                 "c"(nb tx), "f"(fraude 0/1) } ],
    "meta":  { "n_nodes", "n_edges_raw", "n_edges", "t_min", "t_max" }
  }
"""
from __future__ import annotations

import networkx as nx


def to_webgl(g: nx.MultiDiGraph,
             account_features: dict[str, dict],
             account_scores: dict[str, int],
             positions: "dict[str, tuple] | None" = None) -> dict:
    positions = positions or {}
    nodes = []
    for n, attrs in g.nodes(data=True):
        f = account_features.get(n, {})
        x, y = positions.get(n, (0.0, 0.0))
        nodes.append({
            "id": n,
            "x": round(x, 2),
            "y": round(y, 2),
            "s": int(account_scores.get(n, 0)),
            "r": f.get("role", "normal"),
            "ci": attrs.get("country"),
            "ct": attrs.get("customer_type"),
            "fi": f.get("fan_in", 0),
            "fo": f.get("fan_out", 0),
            # identite du titulaire (affichee seulement dans le panneau d'infos)
            "nm": attrs.get("owner_name"),
            "fn": attrs.get("first_name"),
            "ln": attrs.get("last_name"),
            # VERITE TERRAIN M1 (affichage uniquement, jamais une feature)
            "tr": attrs.get("truth_role"),
            "td": bool(attrs.get("truth_is_decoy")),
        })

    # agregation des liens paralleles (src,dst)
    agg: dict[tuple, dict] = {}
    t_min = t_max = None
    raw = 0
    for u, v, d in g.edges(data=True):
        raw += 1
        ts = d.get("timestamp")
        if ts:
            t_min = ts if t_min is None or ts < t_min else t_min
            t_max = ts if t_max is None or ts > t_max else t_max
        key = (u, v)
        amt = d.get("amount", 0.0) or 0.0
        fraud = int(d.get("is_fraud", 0) or 0)
        if key in agg:
            e = agg[key]
            e["c"] += 1
            e["m"] += amt
            e["f"] = max(e["f"], fraud)
            if ts and (e["ts"] is None or ts < e["ts"]):
                e["ts"] = ts
        else:
            agg[key] = {"s": u, "t": v, "ts": ts, "m": amt, "c": 1, "f": fraud}

    edges = []
    for e in agg.values():
        e["m"] = round(e["m"], 2)
        edges.append(e)

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "n_nodes": len(nodes),
            "n_edges_raw": raw,
            "n_edges": len(edges),
            "t_min": t_min,
            "t_max": t_max,
        },
    }
