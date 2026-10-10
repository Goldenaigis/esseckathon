"""
M2 - Export NetworkX -> JSON format Cytoscape.js.

C'EST LE CONTRAT avec M4 (front). Le format ne change pas, meme quand :
  - les donnees viennent du vrai M1 au lieu des fixtures,
  - les scores viennent du vrai M3 au lieu de l'heuristique.
"""
from __future__ import annotations

from typing import Optional

import networkx as nx


def to_cytoscape(g: nx.MultiDiGraph,
                 account_features: dict[str, dict],
                 account_scores: dict[str, int]) -> dict:
    """
    Produit { "nodes": [...], "edges": [...], "meta": {...} }.

    - node.data : id, country, customer_type, risk_score, fan_in, fan_out, role...
    - edge.data : id(tx), source, target, amount, timestamp, status, is_fraud
    """
    nodes = []
    for n, attrs in g.nodes(data=True):
        f = account_features.get(n, {})
        nodes.append({"data": {
            "id": n,
            "country": attrs.get("country"),
            "customer_type": attrs.get("customer_type"),
            "balance": attrs.get("balance"),
            "opened_date": attrs.get("opened_date"),
            "risk_score": int(account_scores.get(n, 0)),
            "fan_in": f.get("fan_in", 0),
            "fan_out": f.get("fan_out", 0),
            "total_in": f.get("total_in", 0.0),
            "total_out": f.get("total_out", 0.0),
            "role": f.get("role", "normal"),
            "redistribution_speed_min": f.get("redistribution_speed_min"),
            "in_cycle": f.get("in_cycle", False),
        }})

    edges = []
    for u, v, d in g.edges(data=True):
        edges.append({"data": {
            "id": d.get("tx_id"),
            "source": u,
            "target": v,
            "amount": d.get("amount"),
            "timestamp": d.get("timestamp"),
            "channel": d.get("channel"),
            "status": d.get("status"),
            "is_fraud": d.get("is_fraud", 0),
        }})

    meta = {
        "n_nodes": len(nodes),
        "n_edges": len(edges),
        "suspicious_structures": detect_structures(g, account_features),
    }
    return {"nodes": nodes, "edges": edges, "meta": meta}


def detect_structures(g: nx.MultiDiGraph,
                      account_features: dict[str, dict]) -> list[dict]:
    """
    Resume des structures suspectes reperees (pour le panneau "pourquoi suspect").
    S'appuie sur les roles deja calcules dans graph_features.
    """
    out = []
    for acc, f in account_features.items():
        role = f.get("role")
        if role == "collector":
            out.append({"type": "collector_star", "center": acc,
                        "detail": f"{f['distinct_senders']} emetteurs convergent vers ce compte"})
        elif role == "collector_redistributor":
            out.append({"type": "hourglass", "center": acc,
                        "detail": (f"{f['distinct_senders']} entrees puis redistribution en "
                                   f"{f['redistribution_speed_min']} min")})
        elif role == "smurf_target":
            out.append({"type": "smurfing_fan", "center": acc,
                        "detail": f"{f['fan_in']} petits virements d'un meme compte (fractionnement)"})
    # un seul resume de cycle (membres)
    cycle_members = [a for a, f in account_features.items() if f.get("in_cycle")]
    if cycle_members:
        out.append({"type": "cycle", "members": cycle_members,
                    "detail": f"cycle financier entre {len(cycle_members)} comptes"})
    return out
