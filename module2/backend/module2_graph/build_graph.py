"""
M2 - Construction du graphe oriente a partir de la base SQLite.

noeud = compte bancaire   (attributs : pays, type, solde, anciennete...)
arete = transaction       (attributs : montant, date, statut...)

La source est la table SQLite produite par M1 (ou par les fixtures jouet).
Le code ne depend QUE du schema des tables, pas de la facon dont elles ont
ete generees -> on branchera le vrai M1 sans rien changer ici.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

import networkx as nx


def load_rows(db_path: str) -> tuple[list[dict], list[dict]]:
    """Lit les comptes et les transactions depuis SQLite."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    accounts = [dict(r) for r in con.execute("SELECT * FROM accounts")]
    transactions = [dict(r) for r in con.execute(
        "SELECT * FROM transactions ORDER BY timestamp")]
    con.close()
    return accounts, transactions


def build_graph(db_path: str) -> nx.MultiDiGraph:
    """
    Construit un MultiDiGraph (plusieurs transactions possibles entre 2 comptes).

    - Chaque noeud porte les attributs du compte.
    - Chaque arete porte les attributs de la transaction.
    """
    accounts, transactions = load_rows(db_path)

    g = nx.MultiDiGraph()
    for a in accounts:
        g.add_node(
            a["account_id"],
            bank=a["bank"],
            country=a["country"],
            opened_date=a["opened_date"],
            balance=a["balance"],
            customer_type=a["customer_type"],
            is_fraudster=a["is_fraudster"],
        )

    for t in transactions:
        # tolerance : si une transaction reference un compte absent, on le cree
        for acc in (t["src_account"], t["dst_account"]):
            if acc not in g:
                g.add_node(acc, bank=None, country=None, opened_date=None,
                           balance=None, customer_type=None, is_fraudster=0)
        g.add_edge(
            t["src_account"],
            t["dst_account"],
            key=t["tx_id"],
            tx_id=t["tx_id"],
            amount=t["amount"],
            timestamp=t["timestamp"],
            channel=t["channel"],
            status=t["status"],
            is_fraud=t["is_fraud"],
            scenario_id=t["scenario_id"],
        )
    return g


def summary(g: nx.MultiDiGraph) -> dict:
    """Petit resume pratique pour verifier / debugger."""
    n_fraud_edges = sum(1 for _, _, d in g.edges(data=True) if d.get("is_fraud"))
    return {
        "n_accounts": g.number_of_nodes(),
        "n_transactions": g.number_of_edges(),
        "n_fraud_transactions": n_fraud_edges,
    }


if __name__ == "__main__":
    import os
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db = os.path.join(_root, "data", "bank.db")
    graph = build_graph(db)
    print("Graphe construit :", summary(graph))
