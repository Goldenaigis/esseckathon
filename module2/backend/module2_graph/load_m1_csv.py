"""
M2 - Adaptateur LECTURE SEULE des donnees M1 (esseckathon/fraudnet/data/*.csv).

But : pouvoir alimenter la cartographie avec la vraie base de M1 (~7000 comptes,
~150k transactions) sans rien modifier chez eux, et sans toucher au chemin
SQLite historique (fixtures). On lit les CSV et on expose les memes structures
que build_graph (dicts accounts / transactions) + un graphe NetworkX.

Mapping des colonnes M1 -> schema M2 :
  accounts.csv   : account_id, country, opened_at, account_age_days,
                   balance, segment/owner_type -> customer_type, gt_role
  transactions.csv: tx_id, src_account, dst_account, amount, ts -> timestamp,
                   channel, status, gt_is_fraud -> is_fraud, gt_scenario_id
"""
from __future__ import annotations

import csv
import os
from typing import Optional

import networkx as nx

# chemin par defaut vers les donnees M1.
# _HERE = .../esseckathon/module2/backend/module2_graph
#  3 up  = .../esseckathon/module2  ; 4 up = .../esseckathon (racine du depot)
# M1 vit dans <racine>/esseckathon/fraudnet/data (dossier imbrique).
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))
DEFAULT_M1_DIR = os.environ.get(
    "M1_DATA_DIR",
    os.path.join(_REPO_ROOT, "esseckathon", "esseckathon", "fraudnet", "data"),
)
# repli : si l'imbrication n'existe pas, essayer sans le doublon
if not os.path.exists(os.path.join(DEFAULT_M1_DIR, "accounts.csv")):
    _alt = os.path.join(_REPO_ROOT, "esseckathon", "fraudnet", "data")
    if os.path.exists(os.path.join(_alt, "accounts.csv")):
        DEFAULT_M1_DIR = _alt


def _customer_type(row: dict) -> str:
    owner = (row.get("owner_type") or "").lower()
    if owner == "company":
        return "business"
    seg = (row.get("segment") or "").lower()
    if "senior" in seg:
        return "senior"
    return "individual"


def build_graph_from_m1(data_dir: str = DEFAULT_M1_DIR) -> nx.MultiDiGraph:
    """Construit le MultiDiGraph a partir des CSV de M1 (lecture seule)."""
    acc_path = os.path.join(data_dir, "accounts.csv")
    tx_path = os.path.join(data_dir, "transactions.csv")

    g = nx.MultiDiGraph()
    with open(acc_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            age = r.get("account_age_days")
            g.add_node(
                r["account_id"],
                bank=r.get("bank_name"),
                country=r.get("country"),
                opened_date=r.get("opened_at"),
                account_age_days=int(age) if age not in (None, "") else None,
                balance=float(r["balance"]) if r.get("balance") else None,
                customer_type=_customer_type(r),
                is_fraudster=1 if (r.get("gt_role") or "") not in ("", "normal") else 0,
                gt_role=r.get("gt_role") or None,
            )

    with open(tx_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            s, d = r["src_account"], r["dst_account"]
            for acc in (s, d):
                if acc not in g:
                    g.add_node(acc, country=None, customer_type=None, is_fraudster=0)
            g.add_edge(
                s, d,
                key=r["tx_id"],
                tx_id=r["tx_id"],
                amount=float(r["amount"]) if r.get("amount") else 0.0,
                timestamp=r.get("ts"),
                channel=r.get("channel"),
                status=r.get("status"),
                is_fraud=int(r["gt_is_fraud"]) if r.get("gt_is_fraud") else 0,
                scenario_id=r.get("gt_scenario_id") or None,
            )
    return g


def m1_available(data_dir: str = DEFAULT_M1_DIR) -> bool:
    return os.path.exists(os.path.join(data_dir, "accounts.csv")) and \
        os.path.exists(os.path.join(data_dir, "transactions.csv"))
