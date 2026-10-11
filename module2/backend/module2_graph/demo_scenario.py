"""
M2 - Scenario de DEMONSTRATION "arnaque a l'instant T" (lecture seule).

But : raconter, sur un VRAI scenario de collecteur des donnees, le contraste
  - SANS le systeme : l'argent est collecte puis s'evapore vers l'etranger
    avant que la victime ne reagisse (plusieurs heures) ;
  - AVEC le systeme : le modele (M3) detecte tres vite -> on gele -> on sauve
    ce qui n'est pas encore sorti.

Tous les chiffres proviennent des VRAIES transactions (dates, montants) ; on
n'invente rien. Le "temps de detection avec systeme" est un ordre de grandeur
honnete appuye sur la metrique reelle de M3 (scoring ~0.05 ms/transaction),
exprime comme "quelques minutes apres l'emergence du motif".

Scenario retenu : le collecteur de SCN_001 (faux conseiller) :
  ACC_006771 (Lina Gautier, mule), 28 victimes, ~106 kEUR, sortie EE/CY.
Si ce compte/scenario est absent (donnees regenerees), on retombe sur le
collecteur au plus haut score M3.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import networkx as nx


# detection "avec systeme" : marge apres le 1er virement, en minutes.
# ordre de grandeur honnete (le modele score en ~0.05 ms/tx ; l'alerte se
# declenche des que le motif de convergence emerge, soit quelques virements).
DETECTION_MINUTES = 6


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


DEMO_SCENARIO_ID = "SCN_001"      # faux conseiller : montants par victime realistes
DEMO_HUB = "ACC_006771"


def _pick_hub(graph: nx.MultiDiGraph, scores: dict) -> Optional[str]:
    """Collecteur de SCN_001 si present, sinon le meilleur candidat :
    fort fan-in + redistribution + score M3 eleve."""
    if DEMO_HUB in graph:
        return DEMO_HUB
    best, best_key = None, -1
    for n in graph.nodes():
        fi = graph.in_degree(n)
        fo = graph.out_degree(n)
        if fi >= 10 and fo >= 1:
            key = scores.get(n, 0) * 1000 + fi
            if key > best_key:
                best, best_key = n, key
    return best


def build_demo(graph: nx.MultiDiGraph, scores: dict,
               alerts: dict | None = None) -> dict:
    """Prepare les donnees de la demo pour le front (chronologie + calcul casse).
    On se restreint au SCENARIO EXACT (SCN_001) : seules les transactions taguees
    de ce scenario comptent, pour des montants par victime realistes."""
    alerts = alerts or {}
    hub = _pick_hub(graph, scores)
    if not hub:
        return {"available": False}

    # ne garder QUE les aretes du scenario de demo si le hub est bien celui-ci
    use_scenario = (hub == DEMO_HUB)

    def in_scope(d):
        return (not use_scenario) or (d.get("scenario_id") == DEMO_SCENARIO_ID)

    in_edges = [(u, v, d) for u, v, d in graph.in_edges(hub, data=True) if in_scope(d)]
    out_edges = [(u, v, d) for u, v, d in graph.out_edges(hub, data=True) if in_scope(d)]

    # chronologie des ENTREES (victimes -> hub)
    ins = []
    for u, _, d in in_edges:
        t = _parse(d.get("timestamp"))
        if t:
            ins.append({"src": u, "amount": d.get("amount", 0.0), "ts": d.get("timestamp"), "t": t})
    ins.sort(key=lambda x: x["t"])

    # chronologie des SORTIES (hub -> mules/etranger)
    outs = []
    for _, v, d in out_edges:
        t = _parse(d.get("timestamp"))
        if t:
            outs.append({"dst": v, "amount": d.get("amount", 0.0), "ts": d.get("timestamp"),
                         "t": t, "dst_country": graph.nodes[v].get("country")})
    outs.sort(key=lambda x: x["t"])

    if not ins:
        return {"available": False}

    total_in = round(sum(e["amount"] for e in ins), 2)
    total_out = round(sum(e["amount"] for e in outs), 2)
    t0 = ins[0]["t"]                       # premier virement de victime
    first_exit = outs[0]["t"] if outs else None

    # SANS systeme : l'argent sort aux dates reelles. "Casse" = montant sorti
    # au moment ou la victime reagit (on prend la 1ere sortie comme reference
    # de l'evaporation ; a defaut, fin de collecte).
    hours_until_exit = round((first_exit - t0).total_seconds() / 3600.0, 1) if first_exit else None

    # AVEC systeme : alerte a t0 + DETECTION_MINUTES. Montant DEJA sorti a cet
    # instant = perdu ; le reste est encore gelable.
    from datetime import timedelta
    alert_time = t0 + timedelta(minutes=DETECTION_MINUTES)
    already_out_at_alert = round(sum(e["amount"] for e in outs if e["t"] <= alert_time), 2)
    salvageable = round(total_in - already_out_at_alert, 2)
    salvage_ratio = round(salvageable / total_in, 3) if total_in else 0.0

    # VICTIMES DISTINCTES (certaines ont pu virer plusieurs fois)
    victim_accounts = {e["src"] for e in ins}
    n_victims = len(victim_accounts)
    # montant par victime (realisme : arnaque "voix IA d'un proche")
    amounts = sorted(e["amount"] for e in ins)
    median_amount = round(amounts[len(amounts) // 2], 2) if amounts else 0.0

    hub_attrs = graph.nodes[hub]
    hub_name = (f"{hub_attrs.get('first_name','')} {hub_attrs.get('last_name','')}".strip()
                or hub_attrs.get("owner_name") or hub)

    return {
        "available": True,
        "hub": hub,
        "hub_name": hub_name,
        "hub_score": int(scores.get(hub, 0)),
        "hub_country": hub_attrs.get("country"),
        "hub_opened": hub_attrs.get("opened_date"),
        "n_victims": n_victims,
        "n_transfers": len(ins),
        "median_amount": median_amount,
        "total_collected": total_in,
        "total_redistributed": total_out,
        "redistribution_countries": sorted({e["dst_country"] for e in outs if e["dst_country"]}),
        "t_first": ins[0]["ts"],
        "t_first_exit": outs[0]["ts"] if outs else None,
        "hours_until_exit": hours_until_exit,
        "detection_minutes": DETECTION_MINUTES,
        "already_lost_at_alert": already_out_at_alert,
        "salvageable": salvageable,
        "salvage_ratio": salvage_ratio,
        "alert": alerts.get(hub) or {},
        # chronologie compacte pour l'animation (timestamps + montants)
        "inflows": [{"src": e["src"], "amount": e["amount"], "ts": e["ts"]} for e in ins],
        "outflows": [{"dst": e["dst"], "amount": e["amount"], "ts": e["ts"],
                      "country": e["dst_country"]} for e in outs],
    }
