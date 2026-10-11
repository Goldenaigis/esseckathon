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

FUITE TEMPORELLE (attention M3) : par defaut les features sont calculees sur
TOUTE la fenetre du graphe passe en argument. Si ce graphe couvre train ET
test, les features d'un compte d'entrainement contiennent de l'information
POSTERIEURE a l'etiquette -> fuite. Passer `as_of="YYYY-MM-DDTHH:MM:SS"` pour
un calcul point-in-time : seules les transactions <= as_of sont prises en
compte. Voir docs/DATA_CONTRACT.md, section "M2 -> M3".
"""
from __future__ import annotations

from datetime import datetime, timedelta
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


def _before(g: nx.MultiDiGraph, as_of) -> nx.MultiDiGraph:
    """
    Sous-graphe POINT-IN-TIME : on garde les noeuds mais seulement les
    transactions horodatees <= `as_of`. Indispensable a M3 pour calculer les
    features d'un compte sans y injecter son activite future.
    Les transactions sans horodatage sont ecartees (on ne peut pas les situer).
    """
    cut = _parse(as_of) if isinstance(as_of, str) else as_of
    if cut is None:
        raise ValueError(f"as_of illisible : {as_of!r} (attendu ISO YYYY-MM-DDTHH:MM:SS)")
    h = nx.MultiDiGraph()
    h.add_nodes_from(g.nodes(data=True))
    for u, v, k, d in g.edges(keys=True, data=True):
        ts = _parse(d.get("timestamp"))
        if ts is not None and ts <= cut:
            h.add_edge(u, v, key=k, **d)
    return h


def _is_laundering_cycle(simple: nx.DiGraph, cyc: list[str]) -> bool:
    """
    Un cycle est juge "suspect" (blanchiment) s'il est TEMPOREL et REGULIER :
      - les transferts s'enchainent dans le temps autour de la boucle,
      - les montants sont quasi identiques (ratio max/min <= 1.25).
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
    Delai (minutes) entre la DERNIERE reception et le PREMIER renvoi QUI LA SUIT.
    Petit delai + gros fan-in => "collecte puis redistribution rapide".

    Renvoie None s'il n'y a AUCUN envoi apres la derniere reception : le compte
    n'a alors pas redistribue, la notion de vitesse n'a pas de sens. (L'ancien
    repli sur min(out_times) renvoyait un delai NEGATIF, qui passait le test
    `<= 180` de risk.py et gonflait a tort le score de 27 % des comptes M1.)
    """
    in_times = [_parse(d.get("timestamp")) for _, _, d in g.in_edges(node, data=True)]
    out_times = [_parse(d.get("timestamp")) for _, _, d in g.out_edges(node, data=True)]
    in_times = [t for t in in_times if t]
    out_times = [t for t in out_times if t]
    if not in_times or not out_times:
        return None
    last_in = max(in_times)
    first_out_after = [t for t in out_times if t >= last_in]
    if not first_out_after:
        return None
    return round((min(first_out_after) - last_in).total_seconds() / 60.0, 1)


def _inbound_window_min(g: nx.MultiDiGraph, node: str) -> Optional[float]:
    """Etendue (min) totale entre le 1er et le dernier virement entrant."""
    times = [_parse(d.get("timestamp")) for _, _, d in g.in_edges(node, data=True)]
    times = [t for t in times if t]
    if len(times) < 2:
        return None
    return round((max(times) - min(times)).total_seconds() / 60.0, 1)


def _inbound_burst(g: nx.MultiDiGraph, node: str, window_min: float = 360.0) -> int:
    """
    CONCENTRATION TEMPORELLE : nombre MAXIMAL de virements entrants recus dans
    une meme fenetre glissante de `window_min` minutes (6 h par defaut).

    C'est la bonne mesure pour separer une mule d'un gros compte legitime :
    l'etendue totale (max - min) ne marche pas, car une seule vieille
    transaction suffit a l'ecraser. Sur les vraies donnees M1 (60 jours),
    l'etendue mediane est de 33 jours et seuls 8 comptes sur 6813 avaient une
    etendue <= 6 h : le critere "rafale" ne se declenchait JAMAIS.
    """
    times = sorted(
        t for t in (_parse(d.get("timestamp")) for _, _, d in g.in_edges(node, data=True))
        if t is not None
    )
    if not times:
        return 0
    span = timedelta(minutes=window_min)
    best = 1
    lo = 0
    for hi in range(len(times)):
        while times[hi] - times[lo] > span:
            lo += 1
        best = max(best, hi - lo + 1)
    return best


def _classify_role(feats: dict) -> str:
    """
    Heuristique de role (sert le rendu + le resume d'alerte).

    Point cle : distinguer une FRAUDE d'un gros compte LEGITIME. Les deux ont
    un fort degre ; ce qui separe, c'est la CONCENTRATION TEMPORELLE (la fraude
    arrive en rafale) et des signaux comme la redistribution rapide.

    La concentration est mesuree par `inbound_burst` (plus grosse rafale sur 6 h)
    et non par l'etendue totale des entrees : un gros compte legitime peut avoir
    8 entrees en 6 h, mais elles ne representent qu'une fraction de son flux ;
    une mule, elle, recoit l'ESSENTIEL de son flux dans la rafale.
    """
    fi, fo = feats["fan_in"], feats["fan_out"]
    ds = feats.get("distinct_senders", fi)
    speed = feats["redistribution_speed_min"]
    burst = feats.get("inbound_burst", 0)
    # rafale : >= 8 entrees dans une meme fenetre de 6 h ET >= 60 % du flux entrant
    bursty = burst >= 8 and burst >= 0.6 * max(fi, 1)

    if feats["in_cycle"]:
        return "cycle_member"
    # smurfing : beaucoup d'entrees d'UN SEUL emetteur, montants similaires, en rafale
    if fi >= 8 and ds <= 2 and bursty and feats.get("same_amount_inflow"):
        return "smurf_target"
    # sablier : collecte de PLUSIEURS emetteurs + redistribution rapide
    if ds >= 8 and fo <= 4 and bursty and speed is not None and speed <= 180:
        return "collector_redistributor"
    # etoile de collecte : beaucoup d'emetteurs DISTINCTS, pas de sortie
    if ds >= 10 and fo == 0 and bursty:
        return "collector"
    if fi == 1 and fo == 1:
        return "relay"                     # maillon de chaine
    return "normal"


def compute_account_features(g: nx.MultiDiGraph, fast: bool = False,
                             as_of: "str | datetime | None" = None) -> dict[str, dict]:
    """
    Renvoie { account_id : { feature: valeur, ... } }.

    Features (toutes derivables sans la verite terrain) :
      fan_in, fan_out, distinct_senders, distinct_receivers,
      in_out_ratio, total_in, total_out,
      degree_centrality, betweenness, in_cycle,
      redistribution_speed_min, inbound_window_min, inbound_burst,
      same_amount_inflow, role

    `fast=True` : mode gros graphe (~7000 noeuds). Sur les vraies donnees M1
    (7060 noeuds / 77355 liens agreges) on a mesure : betweenness echantillonnee
    k=200 -> 14 s, et simple_cycles(length_bound=6) -> plus de 88 000 cycles sans
    terminer en 60 s. `fast` SAUTE ces deux etapes : `betweenness` vaut alors 0.0
    et `in_cycle` vaut toujours False pour TOUS les comptes (donc le role
    "cycle_member" et le bonus de cycle de risk.py sont inoperants en mode fast).

    `as_of` (ISO ou datetime) : calcul POINT-IN-TIME, seules les transactions
    <= as_of comptent. Sans ce parametre, les features couvrent toute la fenetre
    du graphe -> fuite d'information future si le graphe contient le futur de
    l'etiquette. M3 doit l'utiliser (cf. docs/DATA_CONTRACT.md).
    """
    if as_of is not None:
        g = _before(g, as_of)
    simple = _simple_digraph(g)
    n = simple.number_of_nodes()

    # centralite de degre : rapide, toujours exacte.
    deg_c = nx.degree_centrality(simple) if n else {}

    # betweenness : exacte sur petits graphes, APPROXIMEE (echantillon) au-dela ;
    # ignoree en mode fast (trop couteuse a l'echelle 7000 noeuds / 77k liens).
    try:
        if n == 0 or fast:
            betw = {}
        elif n <= 400:
            betw = nx.betweenness_centrality(simple)
        else:
            k = min(200, n)  # echantillon de sources
            betw = nx.betweenness_centrality(simple, k=k, seed=1)
    except Exception:
        betw = {node: 0.0 for node in simple.nodes()}

    # cycles de blanchiment : on borne la recherche aux cycles COURTS (3..6) via
    # `length_bound`. En mode fast (gros graphe), on SAUTE cette etape :
    # simple_cycles explose en combinatoire sur un graphe dense (~77k liens).
    # La detection de cycles se fera a la demande sur un sous-graphe (ego/zoom).
    in_cycle: set[str] = set()
    if not fast:
        try:
            try:
                cycle_iter = nx.simple_cycles(simple, length_bound=6)
            except TypeError:  # networkx plus ancien : pas de length_bound
                cycle_iter = nx.simple_cycles(simple)
            for cyc in cycle_iter:
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

        # signal smurfing : beaucoup d'ENTREES de montants SIMILAIRES
        in_amts = [d.get("amount", 0.0) for _, _, d in in_edges if d.get("amount")]
        same_amount_inflow = False
        if len(in_amts) >= 8:
            lo, hi = min(in_amts), max(in_amts)
            same_amount_inflow = (hi / max(lo, 1e-9)) <= 1.5

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
            "inbound_window_min": _inbound_window_min(g, node),
            "inbound_burst": _inbound_burst(g, node),
            "same_amount_inflow": same_amount_inflow,
        }
        f["role"] = _classify_role(f)
        feats[node] = f
    return feats


if __name__ == "__main__":
    import os
    from backend.module2_graph.build_graph import build_graph

    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    graph = build_graph(os.path.join(_root, "data", "bank.db"))
    fs = compute_account_features(graph)
    # affiche les comptes les plus "interessants"
    ranked = sorted(fs.items(), key=lambda kv: kv[1]["fan_in"], reverse=True)
    print("Top comptes par fan-in :")
    for acc, f in ranked[:6]:
        print(f"  {acc}  role={f['role']:<24} fan_in={f['fan_in']:<3} "
              f"fan_out={f['fan_out']:<3} redis={f['redistribution_speed_min']}")
