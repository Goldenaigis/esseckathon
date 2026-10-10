"""Scenarios de fraude. Tous les parametres sont tires aleatoirement.

Objectif anti-circularite: aucun scenario n'a de parametre fixe. Le nombre de
victimes, les delais, les montants, les paliers, le nombre de sauts et les pays
de destination varient d'une instance a l'autre, et les plages se recoupent
avec celles des faux amis legitimes (voir decoys.py).
"""

import json
from datetime import date, timedelta

from . import names as N
from ..shared.schema import SCENARIO_TYPES
from .world import make_tx, pick_status, lognormal_amount, weighted_choice

EMI_COUNTRIES_BIAS = 0.72  # part des destinations finales en etablissement EMI

# Regime de montant tire par instance de scenario. Le regime "discret" produit
# des virements qu'aucune analyse transaction par transaction ne peut signaler:
# montant ordinaire pour la victime, beneficiaire domestique. Seule la
# convergence des flux les trahit. C'est la these du projet, et elle n'est
# demontrable que si ce regime existe dans les donnees.
AMOUNT_REGIMES = {
    "discret": {"median": (220, 480), "lo": 80, "hi": 900,
                "foreign_bias": 0.35, "w": 0.46},
    "standard": {"median": (800, 1500), "lo": 250, "hi": 3000,
                 "foreign_bias": 0.76, "w": 0.39},
    "eleve": {"median": (2200, 3900), "lo": 800, "hi": 9500,
              "foreign_bias": 0.88, "w": 0.15},
}


def _pick_regime(rng):
    name = weighted_choice(rng, [(k, v["w"]) for k, v in AMOUNT_REGIMES.items()])
    r = AMOUNT_REGIMES[name]
    return name, rng.uniform(*r["median"]), r["lo"], r["hi"], r["foreign_bias"]


def _victim_amount(rng, income, median, lo, hi):
    """Montant plausible pour la victime: borne par ses revenus declares."""
    cap = max(lo * 1.2, min(hi, income * rng.uniform(0.8, 4.0)))
    return round(max(lo, min(cap, lognormal_amount(rng, median, 0.5, lo, hi))), 2)


def generate_fraud(world, used=None):
    rng, cfg = world.rng, world.cfg
    # Chaque type recoit un minimum d'instances et une repartition train/test
    # garantie: sans cela, un type rare se retrouve absent du jeu de test et
    # son rappel devient impossible a mesurer.
    n = cfg.n_fraud_scenarios
    min_per_type = 4 if n >= 40 else 2
    plan = []
    for stype, share in cfg.scenario_mix.items():
        k = max(min_per_type, round(share * n))
        n_test = min(k - 1, max(1, round(k * (1 - cfg.fraud_train_ratio))))
        splits = ["test"] * n_test + ["train"] * (k - n_test)
        rng.shuffle(splits)
        plan += [(stype, s) for s in splits]
    rng.shuffle(plan)

    builders = {
        "faux_conseiller": _faux_conseiller,
        "faux_investissement": _faux_investissement,
        "compte_collecteur": _compte_collecteur,
        "smurfing": _smurfing,
        "chaine_mules": _chaine_mules,
        "dormant_reactive": _dormant_reactive,
        "cycle": _cycle,
    }

    used = used if used is not None else set()
    scenarios, txs = [], []
    for i, (stype, split) in enumerate(plan, start=1):
        sid = f"SCN_{i:03d}"
        sc, stx = builders[stype](world, sid, split, used)
        if not stx:
            continue
        scenarios.append(sc)
        txs += stx
    return scenarios, txs


# ---------------------------------------------------------------- utilitaires

def _mule_account(world, sid, start, foreign=False, age_range=(2, 40),
                  role="mule"):
    rng = world.rng
    profile = "emi" if rng.random() < EMI_COUNTRIES_BIAS else "retail"
    acct = world.open_mule_account(sid, role=role, foreign=foreign,
                                   profile=profile)
    age = rng.randrange(age_range[0], age_range[1] + 1)
    acct["opened_at"] = (start - timedelta(days=age)).date().isoformat()
    return acct


def _fraud_channel(rng, victim_driven=True):
    if victim_driven:
        return weighted_choice(
            rng, [("web", 0.42), ("mobile", 0.46), ("branch", 0.12)]
        )
    return weighted_choice(rng, [("web", 0.55), ("mobile", 0.43), ("branch", 0.02)])


def _record(sid, stype, start, end, n_vic, n_mule, txs, redistributed,
            dest_countries, split, params, description):
    total = round(sum(t["amount"] for t in txs), 2)
    return {
        "scenario_id": sid,
        "scenario_type": stype,
        "scenario_type_fr": SCENARIO_TYPES[stype],
        "start_ts": start.isoformat(),
        "end_ts": end.isoformat(),
        "duration_hours": round((end - start).total_seconds() / 3600, 2),
        "n_victim_accounts": n_vic,
        "n_mule_accounts": n_mule,
        "n_transactions": len(txs),
        "total_amount": total,
        "redistributed_ratio": round(redistributed, 3),
        "destination_countries": "|".join(sorted(set(dest_countries))),
        "gt_split": split,
        "params_json": json.dumps(params, ensure_ascii=True),
        "description_fr": description,
    }


def _tag(txs, sid, stype, split):
    for t in txs:
        t["gt_is_fraud"] = 1
        t["gt_scenario_id"] = sid
        t["gt_scenario_type"] = stype
        t["gt_split"] = split
        t["status"] = "completed" if t["status"] != "rejected" else "rejected"
    return txs


# ---------------------------------------------------------------- scenarios

def _faux_conseiller(world, sid, split, used):
    """Plusieurs victimes virent vers un meme compte, qui vide aussitot."""
    rng = world.rng
    n_victims = rng.randrange(8, 31)
    collect_hours = rng.uniform(6, 48)
    regime, med, lo, hi, foreign_bias = _pick_regime(rng)
    start = world.pick_scenario_start(collect_hours + 6, split)

    collector = _mule_account(world, sid, start, foreign=False,
                              age_range=(2, 40))
    victims = world.pick_victims(n_victims, sid, elderly_bias=True, used=used)
    if len(victims) < 5:
        return None, []

    txs = []
    last = start
    for v in victims:
        src = world.main_account[v["person_id"]]
        used.add(src)
        n_tx = weighted_choice(rng, [(1, 0.62), (2, 0.28), (3, 0.10)])
        for k in range(n_tx):
            ts = start + timedelta(
                hours=rng.uniform(0, collect_hours),
                minutes=rng.randrange(60),
            )
            amount = _victim_amount(
                rng, v["declared_monthly_income"], med, lo, hi
            )
            txs.append(make_tx(
                ts, src, collector["account_id"], amount, "transfer",
                rng.choice(N.FRAUD_LABELS["faux_conseiller"]),
                _fraud_channel(rng, True), pick_status(rng),
                src_country="FR", dst_country=collector["country"],
            ))
            last = max(last, ts)

    collected = sum(t["amount"] for t in txs if t["status"] == "completed")
    ratio = rng.uniform(0.70, 0.95)
    n_out = rng.randrange(2, 5)
    outs, dest = [], []
    for _ in range(n_out):
        outs.append(_mule_account(world, sid, start,
                                  foreign=rng.random() < foreign_bias,
                                  age_range=(2, 60), role="fraudster"))
    exit_lag = rng.uniform(0.3, 3.0)
    shares = [rng.uniform(0.5, 1.5) for _ in outs]
    ssum = sum(shares)
    out_txs = []
    for acct, s in zip(outs, shares):
        ts = last + timedelta(hours=rng.uniform(exit_lag, exit_lag + 1.5))
        amount = round(collected * ratio * s / ssum, 2)
        if amount < 20:
            continue
        dest.append(acct["country"])
        out_txs.append(make_tx(
            ts, collector["account_id"], acct["account_id"], amount, "transfer",
            rng.choice(["Transfert", "Virement", "Reglement"]),
            _fraud_channel(rng, False), "completed",
            src_country=collector["country"], dst_country=acct["country"],
        ))
    txs += out_txs
    _tag(txs, sid, "faux_conseiller", split)
    end = max(t["ts"] for t in txs)

    desc = (
        f"{len(victims)} victimes ont vire {collected:,.0f} EUR vers un compte "
        f"ouvert depuis peu sur une fenetre de {collect_hours:.0f} h "
        f"(regime de montant: {regime}). {ratio * 100:.0f} % des fonds sont "
        f"ressortis vers {len(out_txs)} comptes en moins de "
        f"{exit_lag + 1.5:.1f} h."
    ).replace(",", " ")
    return _record(
        sid, "faux_conseiller", start, end, len(victims), 1 + len(outs), txs,
        ratio, dest, split,
        {"n_victims": len(victims), "collect_hours": round(collect_hours, 1),
         "exit_lag_hours": round(exit_lag, 2), "n_out": len(out_txs),
         "amount_regime": regime, "amount_median": round(med, 2)},
        desc,
    ), txs


def _faux_investissement(world, sid, split, used):
    """Victimes aisees vers plusieurs comptes collecteurs, puis consolidation."""
    rng = world.rng
    n_victims = rng.randrange(10, 36)
    spread_days = rng.uniform(3, 15)
    inv_lo, inv_hi = weighted_choice(
        rng, [((400, 3_500), 0.34), ((1_200, 25_000), 0.46),
              ((4_000, 60_000), 0.20)]
    )
    start = world.pick_scenario_start(spread_days * 24 + 48, split)

    n_collect = rng.randrange(2, 6)
    collectors = [
        _mule_account(world, sid, start, foreign=rng.random() < 0.35,
                      age_range=(5, 90))
        for _ in range(n_collect)
    ]
    victims = world.pick_victims(n_victims, sid, elderly_bias=False, used=used)
    if len(victims) < 6:
        return None, []

    txs = []
    for v in victims:
        src = world.main_account[v["person_id"]]
        used.add(src)
        n_tx = weighted_choice(rng, [(1, 0.35), (2, 0.30), (3, 0.20), (4, 0.15)])
        target = rng.choice(collectors)
        for k in range(n_tx):
            ts = start + timedelta(
                hours=rng.uniform(0, spread_days * 24), minutes=rng.randrange(60)
            )
            base = max(inv_lo, v["declared_monthly_income"] * rng.uniform(0.8, 4.0))
            amount = lognormal_amount(rng, base, 0.6, inv_lo, inv_hi)
            txs.append(make_tx(
                ts, src, target["account_id"], amount, "transfer",
                rng.choice(N.FRAUD_LABELS["faux_investissement"]),
                _fraud_channel(rng, True), pick_status(rng),
                src_country="FR", dst_country=target["country"],
            ))

    final = _mule_account(world, sid, start, foreign=True, age_range=(5, 120),
                          role="fraudster")
    last = max(t["ts"] for t in txs)
    ratio = rng.uniform(0.60, 0.92)
    dest = [final["country"]]
    for c in collectors:
        got = sum(t["amount"] for t in txs
                  if t["dst_account"] == c["account_id"]
                  and t["status"] == "completed")
        if got < 500:
            continue
        for _ in range(rng.randrange(1, 4)):
            ts = last + timedelta(hours=rng.uniform(2, 96))
            txs.append(make_tx(
                ts, c["account_id"], final["account_id"],
                round(got * ratio / rng.uniform(1.0, 3.0), 2), "transfer",
                "Consolidation", _fraud_channel(rng, False), "completed",
                src_country=c["country"], dst_country=final["country"],
            ))
    _tag(txs, sid, "faux_investissement", split)
    end = max(t["ts"] for t in txs)
    total = sum(t["amount"] for t in txs)
    desc = (
        f"{len(victims)} clients ont verse {total:,.0f} EUR vers "
        f"{n_collect} comptes lies, sur {spread_days:.0f} jours. Les fonds ont "
        f"ensuite ete consolides vers un unique compte en {final['country']}."
    ).replace(",", " ")
    return _record(
        sid, "faux_investissement", start, end, len(victims),
        n_collect + 1, txs, ratio, dest, split,
        {"n_victims": len(victims), "n_collectors": n_collect,
         "spread_days": round(spread_days, 1),
         "amount_range": [inv_lo, inv_hi]},
        desc,
    ), txs


def _compte_collecteur(world, sid, split, used):
    """Mule recrutee parmi des clients existants: entree massive puis sortie."""
    rng = world.rng
    n_senders = rng.randrange(15, 41)
    collect_hours = rng.uniform(24, 72)
    regime, med, lo, hi, foreign_bias = _pick_regime(rng)
    start = world.pick_scenario_start(collect_hours + 12, split)

    collector = world.recruit_existing_mule(sid, used)
    if collector is None:
        return None, []
    used.add(collector["account_id"])

    senders = world.pick_victims(n_senders, sid, elderly_bias=rng.random() < 0.5,
                                 used=used)
    if len(senders) < 8:
        return None, []

    txs = []
    for s in senders:
        src = world.main_account[s["person_id"]]
        used.add(src)
        ts = start + timedelta(hours=rng.uniform(0, collect_hours),
                               minutes=rng.randrange(60))
        amount = _victim_amount(rng, s["declared_monthly_income"], med, lo, hi)
        txs.append(make_tx(
            ts, src, collector["account_id"], amount, "transfer",
            rng.choice(N.FRAUD_LABELS["compte_collecteur"]),
            _fraud_channel(rng, True), pick_status(rng),
            src_country="FR", dst_country=collector["country"],
        ))

    collected = sum(t["amount"] for t in txs if t["status"] == "completed")
    ratio = rng.uniform(0.80, 0.97)
    n_out = rng.randrange(3, 7)
    outs = [_mule_account(world, sid, start, foreign=rng.random() < foreign_bias,
                          age_range=(3, 70), role="fraudster")
            for _ in range(n_out)]
    last = max(t["ts"] for t in txs)
    lag = rng.uniform(0.5, 6.0)
    shares = [rng.uniform(0.6, 1.4) for _ in outs]
    ssum = sum(shares)
    dest = []
    for acct, s in zip(outs, shares):
        ts = last + timedelta(hours=rng.uniform(lag, lag + 2))
        amount = round(collected * ratio * s / ssum, 2)
        if amount < 20:
            continue
        dest.append(acct["country"])
        txs.append(make_tx(
            ts, collector["account_id"], acct["account_id"], amount, "transfer",
            "Transfert", _fraud_channel(rng, False), "completed",
            src_country=collector["country"], dst_country=acct["country"],
        ))
    _tag(txs, sid, "compte_collecteur", split)
    end = max(t["ts"] for t in txs)
    desc = (
        f"Un compte client existant a recu {len(senders)} virements de comptes "
        f"distincts en {collect_hours:.0f} h, puis a redistribue "
        f"{ratio * 100:.0f} % des fonds vers {n_out} beneficiaires en "
        f"{lag:.1f} h."
    )
    return _record(
        sid, "compte_collecteur", start, end, len(senders), 1 + n_out, txs,
        ratio, dest, split,
        {"n_senders": len(senders), "collect_hours": round(collect_hours, 1),
         "exit_lag_hours": round(lag, 2), "n_out": n_out,
         "amount_regime": regime, "amount_median": round(med, 2)},
        desc,
    ), txs


def _smurfing(world, sid, split, used):
    """Un montant important fractionne juste sous un palier."""
    rng = world.rng
    threshold = rng.choice([990, 1900, 2900, 4900, 9900])
    total = rng.uniform(15_000, 60_000)
    n_tx = max(8, min(60, int(total / threshold) + rng.randrange(0, 4)))
    duration_h = rng.uniform(4, 72)
    start = world.pick_scenario_start(duration_h + 4, split)

    source = world.recruit_existing_mule(sid, used)
    if source is None:
        source = _mule_account(world, sid, start, foreign=False, age_range=(3, 50))
    used.add(source["account_id"])

    n_dst = rng.randrange(1, 4)
    dsts = [_mule_account(world, sid, start, foreign=rng.random() < 0.6,
                          age_range=(2, 60), role="fraudster")
            for _ in range(n_dst)]

    txs, dest = [], []
    for _ in range(n_tx):
        ts = start + timedelta(hours=rng.uniform(0, duration_h),
                               minutes=rng.randrange(60))
        acct = rng.choice(dsts)
        amount = round(threshold - rng.uniform(0.5, threshold * 0.06), 2)
        dest.append(acct["country"])
        txs.append(make_tx(
            ts, source["account_id"], acct["account_id"], amount, "transfer",
            rng.choice(N.FRAUD_LABELS["smurfing"]),
            _fraud_channel(rng, False), pick_status(rng),
            src_country=source["country"], dst_country=acct["country"],
        ))
    _tag(txs, sid, "smurfing", split)
    end = max(t["ts"] for t in txs)
    desc = (
        f"{n_tx} virements de montants proches de {threshold} EUR emis par un "
        f"meme compte vers {n_dst} beneficiaires en {duration_h:.0f} h, pour un "
        f"total de {sum(t['amount'] for t in txs):,.0f} EUR."
    ).replace(",", " ")
    return _record(
        sid, "smurfing", start, end, 0, 1 + n_dst, txs, 1.0, dest, split,
        {"threshold": threshold, "n_tx": n_tx,
         "duration_hours": round(duration_h, 1), "n_dst": n_dst},
        desc,
    ), txs


def _chaine_mules(world, sid, split, used):
    """Empilement: l'argent traverse plusieurs comptes, commission a chaque saut."""
    rng = world.rng
    n_hops = rng.randrange(3, 6)
    amount = rng.uniform(10_000, 80_000)
    start = world.pick_scenario_start(n_hops * 8 + 6, split)

    origin_victims = world.pick_victims(rng.randrange(1, 4), sid,
                                        elderly_bias=rng.random() < 0.6,
                                        used=used)
    if not origin_victims:
        return None, []

    hops = []
    for i in range(n_hops):
        foreign = (i == n_hops - 1 and rng.random() < 0.8) or rng.random() < 0.2
        role = "fraudster" if i == n_hops - 1 else "mule"
        hops.append(_mule_account(world, sid, start, foreign=foreign,
                                  age_range=(2, 80), role=role))

    txs, dest = [], []
    cursor = start
    remaining = 0.0
    for v in origin_victims:
        src = world.main_account[v["person_id"]]
        used.add(src)
        share = amount / len(origin_victims)
        ts = cursor + timedelta(minutes=rng.randrange(0, 180))
        txs.append(make_tx(
            ts, src, hops[0]["account_id"], round(share, 2), "transfer",
            rng.choice(N.FRAUD_LABELS["chaine_mules"]),
            _fraud_channel(rng, True), "completed",
            src_country="FR", dst_country=hops[0]["country"],
        ))
        remaining += share
    cursor = max(t["ts"] for t in txs)

    for i in range(n_hops - 1):
        commission = rng.uniform(0.02, 0.08)
        remaining = remaining * (1 - commission)
        cursor = cursor + timedelta(
            hours=rng.uniform(0.3, 6.0), minutes=rng.randrange(60)
        )
        dest.append(hops[i + 1]["country"])
        txs.append(make_tx(
            cursor, hops[i]["account_id"], hops[i + 1]["account_id"],
            round(remaining, 2), "transfer",
            rng.choice(N.FRAUD_LABELS["chaine_mules"]),
            _fraud_channel(rng, False), "completed",
            src_country=hops[i]["country"], dst_country=hops[i + 1]["country"],
        ))
    _tag(txs, sid, "chaine_mules", split)
    end = max(t["ts"] for t in txs)
    desc = (
        f"{amount:,.0f} EUR ont traverse {n_hops} comptes successifs en "
        f"{(end - start).total_seconds() / 3600:.1f} h, avec une commission "
        f"prelevee a chaque saut. Destination finale: {hops[-1]['country']}."
    ).replace(",", " ")
    return _record(
        sid, "chaine_mules", start, end, len(origin_victims), n_hops, txs,
        1.0, dest, split,
        {"n_hops": n_hops, "initial_amount": round(amount, 2)},
        desc,
    ), txs


def _dormant_reactive(world, sid, split, used):
    """Compte ancien et inactif qui devient brutalement un hub."""
    rng = world.rng
    regime, med, lo, hi, foreign_bias = _pick_regime(rng)
    start = world.pick_scenario_start(60, split)
    hub = _mule_account(world, sid, start, foreign=False,
                        age_range=(400, 2500))
    n_senders = rng.randrange(5, 21)
    senders = world.pick_victims(n_senders, sid,
                                 elderly_bias=rng.random() < 0.5, used=used)
    if len(senders) < 4:
        return None, []

    collect_hours = rng.uniform(12, 48)
    txs = []
    for s in senders:
        src = world.main_account[s["person_id"]]
        used.add(src)
        ts = start + timedelta(hours=rng.uniform(0, collect_hours),
                               minutes=rng.randrange(60))
        txs.append(make_tx(
            ts, src, hub["account_id"],
            _victim_amount(rng, s["declared_monthly_income"], med, lo, hi),
            "transfer", rng.choice(N.FRAUD_LABELS["dormant_reactive"]),
            _fraud_channel(rng, True), pick_status(rng),
            src_country="FR", dst_country=hub["country"],
        ))

    collected = sum(t["amount"] for t in txs if t["status"] == "completed")
    ratio = rng.uniform(0.75, 0.96)
    n_out = rng.randrange(2, 5)
    outs = [_mule_account(world, sid, start, foreign=rng.random() < foreign_bias,
                          age_range=(2, 60), role="fraudster")
            for _ in range(n_out)]
    last = max(t["ts"] for t in txs)
    dest = []
    for acct in outs:
        ts = last + timedelta(hours=rng.uniform(0.5, 8))
        dest.append(acct["country"])
        txs.append(make_tx(
            ts, hub["account_id"], acct["account_id"],
            round(collected * ratio / n_out, 2), "transfer", "Transfert",
            _fraud_channel(rng, False), "completed",
            src_country=hub["country"], dst_country=acct["country"],
        ))
    _tag(txs, sid, "dormant_reactive", split)
    end = max(t["ts"] for t in txs)
    age = (start.date() - date.fromisoformat(hub["opened_at"])).days
    desc = (
        f"Un compte ouvert depuis {age} jours et sans operation sur la periode "
        f"observee a recu {len(senders)} virements en {collect_hours:.0f} h, "
        f"puis a transfere {ratio * 100:.0f} % des fonds vers {n_out} comptes."
    )
    return _record(
        sid, "dormant_reactive", start, end, len(senders), 1 + n_out, txs,
        ratio, dest, split,
        {"dormant_days": age, "n_senders": len(senders),
         "collect_hours": round(collect_hours, 1),
         "amount_regime": regime, "amount_median": round(med, 2)},
        desc,
    ), txs


def _cycle(world, sid, split, used):
    """Boucle de transferts entre comptes pour brouiller l'origine des fonds."""
    rng = world.rng
    n = rng.randrange(3, 6)
    start = world.pick_scenario_start(48, split)
    ring = [_mule_account(world, sid, start, foreign=rng.random() < 0.3,
                          age_range=(5, 120))
            for _ in range(n)]
    amount = rng.uniform(4_000, 40_000)
    n_laps = rng.randrange(1, 4)

    txs, dest = [], []
    cursor = start
    cur = amount
    for lap in range(n_laps):
        for i in range(n):
            a, b = ring[i], ring[(i + 1) % n]
            cursor = cursor + timedelta(hours=rng.uniform(0.5, 9))
            cur = cur * rng.uniform(0.92, 0.99)
            dest.append(b["country"])
            txs.append(make_tx(
                cursor, a["account_id"], b["account_id"], round(cur, 2),
                "transfer", rng.choice(N.FRAUD_LABELS["cycle"]),
                _fraud_channel(rng, False), "completed",
                src_country=a["country"], dst_country=b["country"],
            ))
    _tag(txs, sid, "cycle", split)
    end = max(t["ts"] for t in txs)
    desc = (
        f"{n} comptes se sont transfere des fonds en boucle ({n_laps} tours, "
        f"{len(txs)} operations) pour un montant initial de {amount:,.0f} EUR."
    ).replace(",", " ")
    return _record(
        sid, "cycle", start, end, 0, n, txs, 1.0, dest, split,
        {"ring_size": n, "n_laps": n_laps, "initial_amount": round(amount, 2)},
        desc,
    ), txs
