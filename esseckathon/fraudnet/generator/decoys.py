"""Faux amis legitimes: des structures qui ressemblent a de la fraude.

C'est la piece la plus importante du jeu de donnees. Sans ces instances, un
modele apprend "convergence de flux = fraude" et obtient un F1 flatteur mais
inutilisable. Chaque faux ami reproduit volontairement une signature de
scenario frauduleux (fan-in massif, redistribution rapide, destination
etrangere, fan-out important) avec gt_is_fraud = 0.

La colonne why_looks_fraudulent documente, pour chaque instance, la signature
imitee. Le module 3 doit mesurer son taux de faux positifs dessus.
"""

from datetime import timedelta

from . import names as N
from ..shared.schema import DECOY_TYPES
from .world import (
    make_tx, pick_status, lognormal_amount, weighted_choice, month_label,
)


def generate_decoys(world, used=None):
    rng, cfg = world.rng, world.cfg
    used = used if used is not None else set()
    n = cfg.n_decoys
    plan = []
    for dtype, share in cfg.decoy_mix.items():
        plan += [dtype] * round(share * n)
    while len(plan) < n:
        plan.append("cagnotte_mariage")
    plan = plan[:n]
    rng.shuffle(plan)

    builders = {
        "bailleur_multi_loyers": _bailleur,
        "cagnotte_mariage": _cagnotte,
        "collecte_association": _collecte_assoc,
        "corridor_remise": _corridor,
        "vente_vehicule": _vente_vehicule,
        "tresorerie_entrepreneur": _tresorerie,
        "paie_entreprise": _paie,
    }

    decoys, txs = [], []
    for i, dtype in enumerate(plan, start=1):
        did = f"DEC_{i:03d}"
        split = "train" if rng.random() < cfg.fraud_train_ratio else "test"
        rec, dtx = builders[dtype](world, did, split, used)
        if not dtx:
            continue
        decoys.append(rec)
        txs += dtx
    return decoys, txs


# ---------------------------------------------------------------- utilitaires

def _normals(world, n, used):
    rng = world.rng
    cands = [
        p for p in world.persons
        if p["gt_role"] == "normal"
        and world.main_account[p["person_id"]] not in used
    ]
    if len(cands) < n:
        n = len(cands)
    return rng.sample(cands, n) if n > 0 else []


def _tag(txs, did, dtype, split):
    for t in txs:
        t["gt_is_fraud"] = 0
        t["gt_decoy_id"] = did
        t["gt_decoy_type"] = dtype
        t["gt_split"] = split
    return txs


def _record(did, dtype, start, end, hub, n_accounts, txs, split, desc, why):
    return {
        "decoy_id": did,
        "decoy_type": dtype,
        "decoy_type_fr": DECOY_TYPES[dtype],
        "start_ts": start.isoformat(),
        "end_ts": end.isoformat(),
        "hub_account": hub,
        "n_accounts": n_accounts,
        "n_transactions": len(txs),
        "total_amount": round(sum(t["amount"] for t in txs), 2),
        "gt_split": split,
        "description_fr": desc,
        "why_looks_fraudulent": why,
    }


# ------------------------------------------------------------------- faux amis

def _bailleur(world, did, split, used):
    """Un bailleur encaisse 12 a 22 loyers le meme jour: fan-in concentre."""
    rng = world.rng
    start = world.pick_scenario_start(24, split)
    n = rng.randrange(12, 23)
    tenants = _normals(world, n, used)
    if len(tenants) < 8:
        return None, []
    owner = _normals(world, 1, used | {world.main_account[t["person_id"]]
                                       for t in tenants})
    if not owner:
        return None, []
    hub = world.main_account[owner[0]["person_id"]]
    used.add(hub)

    txs = []
    for t in tenants:
        src = world.main_account[t["person_id"]]
        used.add(src)
        ts = start + timedelta(hours=rng.uniform(0, 14), minutes=rng.randrange(60))
        rent = round(min(t["declared_monthly_income"] * rng.uniform(0.2, 0.4), 2400), 2)
        txs.append(make_tx(
            ts, src, hub, rent, "rent",
            f"Loyer {month_label(start)}",
            weighted_choice(rng, [("web", 0.5), ("mobile", 0.46), ("branch", 0.04)]),
            pick_status(rng), split=split,
        ))
    _tag(txs, did, "bailleur_multi_loyers", split)
    end = max(t["ts"] for t in txs)
    return _record(
        did, "bailleur_multi_loyers", start, end, hub, len(tenants) + 1, txs,
        split,
        f"Un particulier bailleur a encaisse {len(tenants)} loyers le meme jour.",
        f"Convergence de flux: {len(tenants)} comptes emetteurs distincts vers "
        f"un meme beneficiaire en moins de 14 h. Signature identique a un "
        f"compte collecteur, mais les montants sont stables et recurrents et "
        f"les fonds ne ressortent pas.",
    ), txs


def _cagnotte(world, did, split, used):
    """Cagnotte: fan-in massif PUIS fan-out rapide vers des prestataires.

    Le faux ami le plus proche d'une arnaque au faux conseiller.
    """
    rng = world.rng
    collect_h = rng.uniform(24, 160)
    start = world.pick_scenario_start(collect_h + 24, split)
    n = rng.randrange(28, 81)
    donors = _normals(world, n, used)
    if len(donors) < 15:
        return None, []
    org = _normals(world, 1, used | {world.main_account[d["person_id"]]
                                     for d in donors})
    if not org:
        return None, []
    hub = world.main_account[org[0]["person_id"]]
    used.add(hub)

    txs = []
    for d in donors:
        src = world.main_account[d["person_id"]]
        used.add(src)
        ts = start + timedelta(hours=rng.uniform(0, collect_h),
                               minutes=rng.randrange(60))
        txs.append(make_tx(
            ts, src, hub, lognormal_amount(rng, 55, 0.7, 10, 400), "p2p",
            rng.choice(["Cagnotte mariage", "Cadeau commun", "Participation",
                        "Cagnotte anniversaire"]),
            weighted_choice(rng, [("mobile", 0.75), ("web", 0.25)]),
            pick_status(rng), split=split,
        ))

    collected = sum(t["amount"] for t in txs if t["status"] == "completed")
    ratio = rng.uniform(0.75, 0.95)
    n_vendors = rng.randrange(2, 5)
    vendors = rng.sample(world.merchant_accounts,
                         min(n_vendors, len(world.merchant_accounts)))
    last = max(t["ts"] for t in txs)
    lag = rng.uniform(0.5, 6.0)
    for v in vendors:
        ts = last + timedelta(hours=rng.uniform(lag, lag + 4))
        txs.append(make_tx(
            ts, hub, v, round(collected * ratio / len(vendors), 2), "transfer",
            rng.choice(["Acompte traiteur", "Reglement salle", "Photographe",
                        "Fleuriste", "Reglement prestataire"]),
            "web", "completed", split=split,
        ))
    _tag(txs, did, "cagnotte_mariage", split)
    end = max(t["ts"] for t in txs)
    return _record(
        did, "cagnotte_mariage", start, end, hub, len(donors) + 1 + len(vendors),
        txs, split,
        f"Une cagnotte a reuni {len(donors)} participants pour "
        f"{collected:,.0f} EUR, reverses a {len(vendors)} prestataires.".replace(",", " "),
        f"Collecte puis redistribution: {len(donors)} emetteurs distincts, "
        f"{ratio * 100:.0f} % des fonds ressortis en {lag:.1f} h vers "
        f"{len(vendors)} beneficiaires. C'est exactement la signature "
        f"fan-in + fan-out rapide d'un compte collecteur frauduleux.",
    ), txs


def _collecte_assoc(world, did, split, used):
    """Appel a dons: fan-in de tres grande ampleur sur un compte association."""
    rng = world.rng
    collect_h = rng.uniform(48, 120)
    start = world.pick_scenario_start(collect_h + 12, split)
    assoc = rng.choice(world.associations)
    hub = world.main_account[assoc["association_id"]]
    n = rng.randrange(120, 301)
    donors = _normals(world, n, used)
    if len(donors) < 40:
        return None, []

    txs = []
    for d in donors:
        src = world.main_account[d["person_id"]]
        ts = start + timedelta(hours=rng.uniform(0, collect_h),
                               minutes=rng.randrange(60))
        txs.append(make_tx(
            ts, src, hub, lognormal_amount(rng, 22, 0.8, 5, 500), "donation",
            rng.choice(["Don collecte", "Don urgence", "Soutien association"]),
            weighted_choice(rng, [("web", 0.62), ("mobile", 0.38)]),
            pick_status(rng), split=split,
        ))
    _tag(txs, did, "collecte_association", split)
    end = max(t["ts"] for t in txs)
    return _record(
        did, "collecte_association", start, end, hub, len(donors) + 1, txs,
        split,
        f"L'association {assoc['association_name']} a recu {len(donors)} dons "
        f"en {collect_h:.0f} h lors d'un appel a la generosite.",
        f"Fan-in extreme: {len(donors)} emetteurs distincts en {collect_h:.0f} h. "
        f"Le degre entrant depasse celui de la plupart des comptes mules du jeu. "
        f"Seuls le segment du beneficiaire, son anciennete et l'absence de "
        f"redistribution rapide permettent de distinguer ce cas.",
    ), txs


def _corridor(world, did, split, used):
    """Plusieurs proches envoient vers un meme compte etranger en 48 h."""
    rng = world.rng
    start = world.pick_scenario_start(60, split)
    retail_foreign = [b for b in world.foreign_banks if b["_profile"] == "retail"]
    bank = rng.choice(retail_foreign)
    family = _normals(world, rng.randrange(5, 13), used)
    if len(family) < 4:
        return None, []
    last_name = family[0]["last_name"]
    beneficiary = world._open_account(
        "person", "", f"{rng.choice(N.FIRST_NAMES)} {last_name}", bank,
        "courant", "particulier",
        (world.window_start - timedelta(days=rng.randrange(600, 5000))).date().isoformat(),
        lognormal_amount(rng, 1500, 1.0, 50),
    )
    hub = beneficiary["account_id"]

    txs = []
    for p in family:
        src = world.main_account[p["person_id"]]
        used.add(src)
        for _ in range(rng.randrange(1, 3)):
            ts = start + timedelta(hours=rng.uniform(0, 48),
                                   minutes=rng.randrange(60))
            txs.append(make_tx(
                ts, src, hub,
                lognormal_amount(rng, rng.uniform(150, 700), 0.4, 60, 1800),
                "remittance",
                rng.choice(["Soutien famille", "Aide parents", "Frais medicaux",
                            "Rentree scolaire"]),
                weighted_choice(rng, [("mobile", 0.7), ("web", 0.3)]),
                pick_status(rng), src_country="FR",
                dst_country=bank["country"], split=split,
            ))
    _tag(txs, did, "corridor_remise", split)
    end = max(t["ts"] for t in txs)
    return _record(
        did, "corridor_remise", start, end, hub, len(family) + 1, txs, split,
        f"{len(family)} membres d'une meme famille ont envoye des fonds vers un "
        f"compte en {bank['country']} sur 48 h.",
        f"Convergence de flux vers un compte etranger: {len(family)} emetteurs "
        f"distincts, destination hors de France, en moins de 48 h. Signature "
        f"d'un faux conseiller avec sortie a l'etranger, alors que le corridor "
        f"est recurrent et le beneficiaire ancien.",
    ), txs


def _vente_vehicule(world, did, split, used):
    """Gros encaissement unique puis transfert immediat: pass-through ~ 1."""
    rng = world.rng
    start = world.pick_scenario_start(72, split)
    people = _normals(world, 2, used)
    if len(people) < 2:
        return None, []
    seller, buyer = people
    src = world.main_account[buyer["person_id"]]
    hub = world.main_account[seller["person_id"]]
    used.update({src, hub})
    amount = round(rng.uniform(6_500, 21_000), 2)

    txs = [make_tx(
        start, src, hub, amount, "transfer",
        rng.choice(["Achat vehicule", "Vente voiture", "Reglement vehicule"]),
        weighted_choice(rng, [("web", 0.5), ("branch", 0.3), ("mobile", 0.2)]),
        "completed", split=split,
    )]
    sav = world.savings_account.get(seller["person_id"])
    ratio = rng.uniform(0.80, 0.98)
    if sav:
        ts = start + timedelta(hours=rng.uniform(0.5, 36))
        txs.append(make_tx(
            ts, hub, sav, round(amount * ratio, 2), "savings_transfer",
            "Virement epargne", "mobile", "completed", split=split,
        ))
    _tag(txs, did, "vente_vehicule", split)
    end = max(t["ts"] for t in txs)
    return _record(
        did, "vente_vehicule", start, end, hub, 3, txs, split,
        f"Vente d'un vehicule entre particuliers pour {amount:,.0f} EUR, "
        f"somme replacee en epargne.".replace(",", " "),
        f"Montant tres superieur a l'historique de l'emetteur, beneficiaire "
        f"inconnu jusque-la, et {ratio * 100:.0f} % des fonds reorientes en "
        f"moins de 36 h. Trois signaux de mule reunis sur une operation "
        f"parfaitement legitime.",
    ), txs


def _tresorerie(world, did, split, used):
    """Entrepreneur: rotations rapides entre ses propres comptes."""
    rng = world.rng
    start = world.pick_scenario_start(96, split)
    cands = [
        p for p in world.persons
        if p["gt_role"] == "normal"
        and p["csp"] == "artisan_commercant"
        and world.savings_account.get(p["person_id"])
        and world.main_account[p["person_id"]] not in used
    ]
    if not cands:
        return None, []
    p = rng.choice(cands)
    main = world.main_account[p["person_id"]]
    sav = world.savings_account[p["person_id"]]
    used.add(main)
    company = rng.choice([c for c in world.companies if c["size_band"] == "TPE"])
    pro = world.main_account[company["company_id"]]

    txs = []
    cursor = start
    n = rng.randrange(6, 15)
    for _ in range(n):
        cursor = cursor + timedelta(hours=rng.uniform(1, 12))
        legs = rng.choice([(pro, main), (main, sav), (sav, main), (main, pro)])
        amount = lognormal_amount(rng, rng.uniform(1200, 6000), 0.5, 200, 30_000)
        txs.append(make_tx(
            cursor, legs[0], legs[1], amount, "transfer",
            rng.choice(["Tresorerie", "Avance compte courant", "Remuneration",
                        "Regularisation", "Virement interne"]),
            weighted_choice(rng, [("web", 0.6), ("mobile", 0.4)]),
            "completed", split=split,
        ))
    _tag(txs, did, "tresorerie_entrepreneur", split)
    end = max(t["ts"] for t in txs)
    return _record(
        did, "tresorerie_entrepreneur", start, end, main, 3, txs, split,
        f"Un artisan a effectue {n} mouvements de tresorerie entre son compte "
        f"professionnel, son compte courant et son epargne en 4 jours.",
        f"Ratio flux sortant / flux entrant proche de 1, delai de "
        f"redistribution tres court, velocite elevee. Signature de compte de "
        f"passage, alors que tous les comptes appartiennent au meme titulaire.",
    ), txs


def _paie(world, did, split, used):
    """Versement groupe des salaires: fan-out massif en une heure."""
    rng = world.rng
    start = world.pick_scenario_start(12, split)
    cands = [c for c in world.companies if c["size_band"] in ("PME", "ETI")]
    if not cands:
        return None, []
    company = rng.choice(cands)
    hub = world.main_account[company["company_id"]]
    n = rng.randrange(35, 121)
    employees = _normals(world, n, used)
    if len(employees) < 20:
        return None, []

    txs = []
    for e in employees:
        ts = start + timedelta(minutes=rng.randrange(0, 75),
                               seconds=rng.randrange(60))
        txs.append(make_tx(
            ts, hub, world.main_account[e["person_id"]],
            round(e["declared_monthly_income"] * rng.uniform(0.96, 1.04), 2),
            "salary", f"Salaire {month_label(start)}", "web",
            pick_status(rng), split=split,
        ))
    _tag(txs, did, "paie_entreprise", split)
    end = max(t["ts"] for t in txs)
    return _record(
        did, "paie_entreprise", start, end, hub, len(employees) + 1, txs, split,
        f"{company['legal_name']} a verse {len(employees)} salaires en moins "
        f"de 75 minutes.",
        f"Fan-out extreme: {len(employees)} beneficiaires distincts depuis un "
        f"seul compte en 75 minutes. Signature de redistribution d'un compte "
        f"collecteur, poussee a l'extreme.",
    ), txs
