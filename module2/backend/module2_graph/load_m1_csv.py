"""
M2 - Adaptateur LECTURE SEULE des donnees M1 (esseckathon/fraudnet/data/*.csv).

But : pouvoir alimenter la cartographie avec la vraie base de M1 (~7000 comptes,
~150k transactions) sans rien modifier chez eux, et sans toucher au chemin
SQLite historique (fixtures). On lit les CSV et on expose les memes structures
que build_graph (dicts accounts / transactions) + un graphe NetworkX.

Mapping des colonnes M1 -> schema M2 :
  accounts.csv   : account_id, bank_name -> bank, country, opened_at -> opened_date,
                   account_age_days, balance, owner_type -> customer_type,
                   owner_name, gt_role -> truth_role
  persons.csv    : first_name, last_name (joints via owner_id)
  transactions.csv: tx_id, src_account, dst_account, amount, ts -> timestamp,
                   channel, status, currency, instrument, tx_type,
                   gt_is_fraud -> is_fraud,
                   gt_scenario_id -> scenario_id, gt_decoy_id -> truth_is_decoy

ATTENTION, le domaine de `status` differe du contrat : M1 ecrit completed /
pending / rejected (et non legitimate / suspicious / confirmed_fraud). Ce champ
n'est ni une feature ni un signal de fraude ici, il est transporte tel quel.
"""
from __future__ import annotations

import csv
import os
from typing import Optional

import networkx as nx

# chemin par defaut vers les donnees M1.
# _HERE = <racine>/module2/backend/module2_graph  ->  3 remontees = <racine>.
# M1 vit dans <racine>/esseckathon/fraudnet/data (dossier imbrique), avec repli
# sur <racine>/fraudnet/data. On NE deduit PAS le chemin du NOM du dossier de la
# racine : le depot peut etre clone sous n'importe quel nom.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
_CANDIDATES = [
    os.path.join(_REPO_ROOT, "esseckathon", "fraudnet", "data"),
    os.path.join(_REPO_ROOT, "fraudnet", "data"),
]
DEFAULT_M1_DIR = os.environ.get("M1_DATA_DIR") or next(
    (p for p in _CANDIDATES if os.path.exists(os.path.join(p, "accounts.csv"))),
    _CANDIDATES[0],
)


def _customer_type(row: dict) -> str:
    """
    owner_type M1 -> customer_type du contrat. Mesure sur les CSV reels :
    6525 "person", 490 "company", 45 "association". Une association n'est pas
    un particulier, on la compte en "business".
    Le type "senior" du contrat reste INATTEIGNABLE ici : les segments M1 valent
    particulier / pro / association, l'age est dans persons.csv (champ age_band).
    """
    owner = (row.get("owner_type") or "").lower()
    if owner in ("company", "association"):
        return "business"
    seg = (row.get("segment") or "").lower()
    if "senior" in seg:
        return "senior"
    return "individual"


def _load_person_names(data_dir: str) -> dict:
    """person_id -> (first_name, last_name) depuis persons.csv (lecture seule)."""
    path = os.path.join(data_dir, "persons.csv")
    names: dict[str, tuple] = {}
    if not os.path.exists(path):
        return names
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            names[r["person_id"]] = (r.get("first_name") or "", r.get("last_name") or "")
    return names


def build_graph_from_m1(data_dir: str = DEFAULT_M1_DIR) -> nx.MultiDiGraph:
    """Construit le MultiDiGraph a partir des CSV de M1 (lecture seule).

    transactions.csv (18 Mo) n'est lu QU'UNE fois : les comptes impliques dans
    un leurre (gt_decoy_id) sont marques au passage, dans la meme boucle, et le
    debut de la partition de test y est releve (cf. g.graph["t_demo_start"])."""
    acc_path = os.path.join(data_dir, "accounts.csv")
    tx_path = os.path.join(data_dir, "transactions.csv")
    person_names = _load_person_names(data_dir)

    g = nx.MultiDiGraph()
    with open(acc_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            age = r.get("account_age_days")
            owner_type = (r.get("owner_type") or "").lower()
            # nom/prenom : pour une PERSONNE on prend persons.csv ; pour une
            # ENTREPRISE il n'y a pas de prenom -> on garde la raison sociale.
            first = last = ""
            if owner_type == "person":
                first, last = person_names.get(r.get("owner_id"), ("", ""))
            acc_id = r["account_id"]
            role = (r.get("gt_role") or "normal")
            # VERITE TERRAIN M1 (prefixe truth_) : affichage/eval UNIQUEMENT,
            # JAMAIS une feature ni une entree du score (contrat anti-fuite M1).
            g.add_node(
                acc_id,
                bank=r.get("bank_name"),
                country=r.get("country"),
                opened_date=r.get("opened_at"),
                account_age_days=int(age) if age not in (None, "") else None,
                balance=float(r["balance"]) if r.get("balance") else None,
                customer_type=_customer_type(r),
                owner_name=r.get("owner_name") or None,
                first_name=first or None,
                last_name=last or None,
                truth_role=role,                       # normal/victim/fraudster/mule
                truth_is_decoy=False,                  # renseigne dans la boucle tx
                # conserve pour compat interne (statut d'arete), pas une feature
                is_fraudster=1 if role in ("fraudster", "mule") else 0,
            )

    # gt_split n'est PAS importe sur les aretes (ce n'est ni une feature ni un
    # attribut d'affichage), mais la frise de demo doit demarrer au debut de la
    # partition de test : on en retient seulement le premier horodatage.
    t_test_min: Optional[str] = None
    with open(tx_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            s, d = r["src_account"], r["dst_account"]
            for acc in (s, d):
                if acc not in g:
                    g.add_node(acc, country=None, customer_type=None,
                               is_fraudster=0, truth_is_decoy=False)
            if r.get("gt_decoy_id"):
                # LEURRE : compte legitime mais trompeur. Affichage/eval seulement.
                g.nodes[s]["truth_is_decoy"] = True
                g.nodes[d]["truth_is_decoy"] = True
            ts = r.get("ts")
            if ts and r.get("gt_split") == "test" and (
                    t_test_min is None or ts < t_test_min):
                t_test_min = ts
            g.add_edge(
                s, d,
                key=r["tx_id"],
                tx_id=r["tx_id"],
                amount=float(r["amount"]) if r.get("amount") else 0.0,
                timestamp=ts,
                channel=r.get("channel"),
                status=r.get("status"),
                # moyen de paiement (perimetre scoré par M3) vs finalite
                # economique : `instrument` et `tx_type` ne sont PAS
                # interchangeables, cf. CLAUDE.md a la racine.
                instrument=r.get("instrument") or None,
                tx_type=r.get("tx_type") or None,
                currency=r.get("currency") or None,
                is_fraud=int(r["gt_is_fraud"]) if r.get("gt_is_fraud") else 0,
                scenario_id=r.get("gt_scenario_id") or None,
            )
    if t_test_min:
        # On ramene au debut du JOUR : la frise avance jour par jour, demarrer a
        # 00:09:20 ferait sauter la premiere journee a un instant arbitraire.
        g.graph["t_demo_start"] = t_test_min[:10] + "T00:00:00"
    return g


def m1_available(data_dir: str = DEFAULT_M1_DIR) -> bool:
    return os.path.exists(os.path.join(data_dir, "accounts.csv")) and \
        os.path.exists(os.path.join(data_dir, "transactions.csv"))
