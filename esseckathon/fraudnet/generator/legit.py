"""Generation des comportements legitimes.

Trois familles:
  - flux structurels recurrents (salaires, loyers, factures, epargne)
  - flux legitimes de montant eleve et flux transfrontaliers legitimes:
    ce sont les negatifs difficiles, indispensables pour que le modele
    n'apprenne pas "gros montant = fraude" ni "etranger = fraude"
  - flux de remplissage (depenses courantes, virements entre proches)

Les virements structurels sont decales au prochain jour ouvre: en SEPA rien
ne regle le week-end.
"""

from datetime import timedelta

from . import names as N
from .world import (
    make_tx, pick_status, ts_on, next_business_day, lognormal_amount,
    weighted_choice, month_label,
)


def generate_legit(world):
    txs = []
    txs += _salaries(world)
    txs += _rents(world)
    txs += _utilities(world)
    txs += _savings(world)
    txs += _big_transfers(world)
    txs += _remittances(world)
    txs += _neobank(world)
    txs += _travel_abroad(world)
    txs += _cross_border_b2b(world)
    txs += _b2b(world)
    txs += _donations(world)
    txs += _refunds(world)
    txs += _large_purchases(world)

    structural = len(txs)
    remaining = max(0, world.cfg.target_transactions - structural)
    remaining = int(remaining * 0.96)  # marge pour la fraude et les faux amis
    n_retail = int(remaining * 0.82)
    txs += _retail(world, n_retail)
    txs += _p2p(world, remaining - n_retail)
    return txs


# ---------------------------------------------------------------- structurels

def _salaries(world):
    rng = world.rng
    txs = []
    paydays = {c["company_id"]: rng.choice([27, 28, 29, 30, 1, 2])
               for c in world.companies}

    for p in world.persons:
        emp = p["employer_id"]
        if not emp:
            continue
        src = world.employer_account[emp]
        dst = world.main_account[p["person_id"]]
        for d in world.days():
            if d.day != paydays[emp]:
                continue
            ts = ts_on(rng, next_business_day(d), "business")
            txs.append(make_tx(
                ts, src, dst,
                p["declared_monthly_income"] * rng.uniform(0.96, 1.05),
                "salary", f"Salaire {month_label(d)} {d.year}", "web",
                pick_status(rng), split=world.split_of(ts),
            ))

    payers = [world.main_account[c["company_id"]] for c in world.companies
              if c["size_band"] == "ETI"][:6]
    payers = payers or [world.main_account[world.companies[0]["company_id"]]]
    for p in world.persons:
        if p["csp"] != "retraite":
            continue
        src = rng.choice(payers)
        dst = world.main_account[p["person_id"]]
        for d in world.days():
            if d.day != 9:
                continue
            ts = ts_on(rng, next_business_day(d), "business")
            txs.append(make_tx(
                ts, src, dst,
                p["declared_monthly_income"] * rng.uniform(0.99, 1.01),
                "salary", f"Pension retraite {month_label(d)}", "web",
                pick_status(rng), split=world.split_of(ts),
            ))
    return txs


def _rents(world):
    rng, cfg = world.rng, world.cfg
    txs = []
    sci = [c["company_id"] for c in world.companies
           if c["sector"] == "immobilier_sci"]
    rich = [p["person_id"] for p in world.persons
            if p["declared_monthly_income"] > 2800]
    landlord_persons = rng.sample(rich, min(220, len(rich))) if rich else []
    landlords = ([world.main_account[c] for c in sci]
                 + [world.main_account[p] for p in landlord_persons])

    for p in world.persons:
        if rng.random() > cfg.tenant_ratio:
            continue
        dst = rng.choice(landlords)
        src = world.main_account[p["person_id"]]
        if src == dst:
            continue
        rent = round(
            min(p["declared_monthly_income"] * rng.uniform(0.22, 0.42), 2600), 2
        )
        day_of_month = rng.choice([1, 2, 3, 4, 5])
        for d in world.days():
            if d.day != day_of_month:
                continue
            ts = ts_on(rng, next_business_day(d), "diurnal")
            txs.append(make_tx(
                ts, src, dst, rent, "rent", f"Loyer {month_label(d)} {d.year}",
                weighted_choice(rng, [("web", 0.5), ("mobile", 0.45),
                                      ("branch", 0.05)]),
                pick_status(rng), split=world.split_of(ts),
            ))
    return txs


def _utilities(world):
    rng = world.rng
    txs = []
    billers = [world.main_account[c["company_id"]] for c in world.companies
               if c["sector"] in ("energie_telecom", "assurance", "sante")]
    if not billers:
        return txs
    for p in world.persons:
        src = world.main_account[p["person_id"]]
        for dst in rng.sample(billers, min(rng.randrange(2, 5), len(billers))):
            amount = lognormal_amount(
                rng, max(18, p["declared_monthly_income"] * 0.025), 0.5, 6, 400
            )
            day_of_month = rng.randrange(1, 29)
            for d in world.days():
                if d.day != day_of_month:
                    continue
                ts = ts_on(rng, next_business_day(d), "business")
                txs.append(make_tx(
                    ts, src, dst, amount * rng.uniform(0.97, 1.08), "utility",
                    rng.choice(N.MERCHANT_LABELS["energie_telecom"]), "web",
                    pick_status(rng), split=world.split_of(ts),
                ))
    return txs


def _savings(world):
    rng = world.rng
    txs = []
    by_id = {p["person_id"]: p for p in world.persons}
    for pid, sav in world.savings_account.items():
        src = world.main_account[pid]
        person = by_id[pid]
        day_of_month = rng.choice([3, 4, 5, 6, 7, 8])
        amount = round(person["declared_monthly_income"] * rng.uniform(0.04, 0.20), 2)
        for d in world.days():
            if d.day != day_of_month:
                continue
            ts = ts_on(rng, d, "evening")
            txs.append(make_tx(
                ts, src, sav, amount, "savings_transfer", "Virement epargne",
                "mobile", pick_status(rng), split=world.split_of(ts),
            ))
    return txs


# --------------------------------------------------- negatifs difficiles (1/2)

def _big_transfers(world):
    """Virements legitimes de montant eleve.

    Sans eux, le montant devient a lui seul un predicteur de fraude. On couvre
    aussi le cas "beneficiaire inconnu + gros montant", qui est la signature
    naive d'une mule mais arrive tous les jours.
    """
    rng = world.rng
    txs = []
    by_id = {p["person_id"]: p for p in world.persons}
    pros = [world.main_account[c["company_id"]] for c in world.companies
            if c["sector"] in ("batiment", "immobilier_sci", "conseil",
                               "commerce_equipement", "transport")]
    tax_offices = [world.main_account[c["company_id"]] for c in world.companies
                   if c["size_band"] == "ETI"][:4]
    tax_offices = tax_offices or pros[:1]

    foreign = _ensure_foreign_companies(world)
    kinds = [
        ("aide_famille", 0.17), ("remboursement_pret", 0.14),
        ("acompte_pro", 0.16), ("impots", 0.12),
        ("retrait_epargne", 0.12), ("achat_occasion", 0.13),
        ("virement_etranger", 0.12), ("solde_notaire", 0.04),
    ]

    for p in world.persons:
        if rng.random() > 0.80:
            continue
        src = world.main_account[p["person_id"]]
        income = p["declared_monthly_income"]
        for _ in range(rng.randrange(1, 8)):
            kind = weighted_choice(rng, kinds)
            d = rng.choice(world.days())
            contacts = world.contacts.get(p["person_id"]) or []
            dst_country = "FR"

            if kind == "aide_famille" and contacts:
                dst = world.main_account[rng.choice(contacts)]
                amount = lognormal_amount(rng, max(400, income * 0.45), 0.7, 300, 9000)
                label, ttype, prof = (
                    rng.choice(["Aide famille", "Cadeau", "Soutien", "Avance"]),
                    "transfer", "evening",
                )
            elif kind == "remboursement_pret" and contacts:
                dst = world.main_account[rng.choice(contacts)]
                amount = lognormal_amount(rng, max(350, income * 0.3), 0.7, 250, 6000)
                label, ttype, prof = "Remboursement pret", "transfer", "evening"
            elif kind == "acompte_pro":
                dst = rng.choice(pros)
                amount = lognormal_amount(rng, max(900, income * 1.6), 0.9, 600, 30_000)
                label, ttype, prof = (
                    rng.choice(["Acompte travaux", "Acompte commande",
                                "Reglement devis", "Solde chantier"]),
                    "transfer", "business",
                )
            elif kind == "impots":
                dst = rng.choice(tax_offices)
                amount = lognormal_amount(rng, max(300, income * 0.7), 0.7, 200, 12_000)
                label, ttype, prof = (
                    rng.choice(["Impot sur le revenu", "Taxe fonciere",
                                "Cotisations", "Taxe habitation"]),
                    "transfer", "business",
                )
            elif kind == "retrait_epargne" and world.savings_account.get(p["person_id"]):
                dst = src
                src = world.savings_account[p["person_id"]]
                amount = lognormal_amount(rng, max(600, income * 1.2), 0.9, 400, 25_000)
                label, ttype, prof = "Retrait epargne", "savings_transfer", "diurnal"
            elif kind == "achat_occasion":
                other = rng.choice(world.persons)["person_id"]
                if other == p["person_id"]:
                    continue
                dst = world.main_account[other]
                amount = lognormal_amount(rng, 1400, 1.0, 400, 22_000)
                label, ttype, prof = (
                    rng.choice(["Achat occasion", "Vente materiel",
                                "Achat velo", "Achat mobilier", "Reglement"]),
                    "transfer", "diurnal",
                )
            elif kind == "virement_etranger":
                dst, dst_country, _ = rng.choice(foreign)
                amount = lognormal_amount(rng, max(500, income * 0.9), 1.0,
                                          200, 45_000)
                label, ttype, prof = (
                    rng.choice(["Frais scolarite", "Location vacances",
                                "Achat import", "Reglement sejour",
                                "Honoraires", "Achat en ligne etranger"]),
                    "transfer", "diurnal",
                )
            else:
                dst = world.main_account[p["person_id"]]
                src = rng.choice(pros)
                amount = lognormal_amount(rng, 22_000, 1.0, 3_000, 180_000)
                label, ttype, prof = (
                    rng.choice(["Solde notaire", "Indemnite", "Succession",
                                "Cession parts"]),
                    "transfer", "business",
                )

            if src == dst:
                continue
            ts = ts_on(rng, d, prof)
            txs.append(make_tx(
                ts, src, dst, amount, ttype, label,
                weighted_choice(rng, [("web", 0.52), ("mobile", 0.36),
                                      ("branch", 0.12)]),
                pick_status(rng), src_country="FR", dst_country=dst_country,
                split=world.split_of(ts),
            ))
            src = world.main_account[p["person_id"]]
    return txs


# --------------------------------------------------- negatifs difficiles (2/2)

def _ensure_foreign_companies(world, n=70):
    """Pool de commercants et fournisseurs etrangers (crees une seule fois)."""
    if getattr(world, "_foreign_merchants", None):
        return world._foreign_merchants
    rng = world.rng
    accounts = []
    for _ in range(n):
        bank = rng.choice(world.foreign_banks)
        cid = world.next_id("company", "CMP_", 5)
        sector = weighted_choice(
            rng, [("commerce_alimentaire", 0.2), ("restauration", 0.2),
                  ("transport", 0.15), ("loisirs_culture", 0.15),
                  ("commerce_equipement", 0.15), ("logistique_b2b", 0.15)]
        )
        name = (f"{rng.choice(N.COMPANY_PREFIX)} "
                f"{rng.choice(N.COMPANY_ROOT)} {bank['country']}")
        world.companies.append({
            "company_id": cid,
            "legal_name": name,
            "legal_form": "ETR",
            "sector": sector,
            "size_band": weighted_choice(rng, [("TPE", 0.6), ("PME", 0.4)]),
            "n_employees": rng.randrange(2, 120),
            "created_at": (world.window_start
                           - timedelta(days=rng.randrange(500, 9000))).date().isoformat(),
            "city": "",
            "country": bank["country"],
            "declared_monthly_revenue": lognormal_amount(rng, 90_000, 1.0, 5_000),
            "is_merchant": 1,
            "gt_role": "normal",
            "gt_scenario_id": "",
        })
        acct = world._open_account(
            "company", cid, name, bank, "pro", "pro",
            (world.window_start - timedelta(days=rng.randrange(400, 8000))).date().isoformat(),
            lognormal_amount(rng, 60_000, 1.0, 1_000),
        )
        world.main_account[cid] = acct["account_id"]
        accounts.append((acct["account_id"], bank["country"], sector))
    world._foreign_merchants = accounts
    return accounts


def _remittances(world):
    """Envois reguliers vers l'etranger, vers un beneficiaire stable."""
    rng, cfg = world.rng, world.cfg
    txs = []
    retail_foreign = [b for b in world.foreign_banks if b["_profile"] == "retail"]
    for p in world.persons:
        if rng.random() > cfg.remittance_ratio:
            continue
        n_benef = weighted_choice(rng, [(1, 0.7), (2, 0.3)])
        benefs = []
        for _ in range(n_benef):
            bank = rng.choice(retail_foreign)
            acct = world._open_account(
                "person", "", f"{rng.choice(N.FIRST_NAMES)} {p['last_name']}",
                bank, "courant", "particulier",
                (world.window_start
                 - timedelta(days=rng.randrange(400, 6000))).date().isoformat(),
                lognormal_amount(rng, 900, 1.0, 10),
            )
            benefs.append((acct["account_id"], bank["country"]))

        src = world.main_account[p["person_id"]]
        amount = lognormal_amount(
            rng, max(80, p["declared_monthly_income"] * 0.12), 0.35, 40, 1200
        )
        for benef, country in benefs:
            day_of_month = rng.randrange(5, 26)
            for d in world.days():
                if d.day != day_of_month:
                    continue
                ts = ts_on(rng, next_business_day(d), "evening")
                txs.append(make_tx(
                    ts, src, benef, amount * rng.uniform(0.9, 1.1), "remittance",
                    rng.choice(["Soutien famille", "Aide parents",
                                "Frais scolarite", "Virement famille"]),
                    weighted_choice(rng, [("mobile", 0.7), ("web", 0.25),
                                          ("branch", 0.05)]),
                    pick_status(rng), src_country="FR", dst_country=country,
                    split=world.split_of(ts),
                ))
    return txs


def _neobank(world):
    """Compte secondaire chez un etablissement de paiement etranger.

    Cas tres courant en pratique (licences LT, MT, DE) et structurellement
    identique a un virement vers un compte de mule a l'etranger. Negatif
    difficile par excellence.
    """
    rng = world.rng
    txs = []
    emi = [b for b in world.foreign_banks if b["_profile"] == "emi"]
    if not emi:
        return txs
    foreign_merchants = _ensure_foreign_companies(world)

    for p in world.persons:
        lit = p["sim_digital_literacy"]
        if rng.random() > 0.08 + 0.26 * lit:
            continue
        bank = rng.choice(emi)
        acct = world._open_account(
            "person", p["person_id"], f"{p['first_name']} {p['last_name']}", bank,
            "courant", "particulier",
            (world.window_start
             - timedelta(days=rng.randrange(60, 2200))).date().isoformat(),
            lognormal_amount(rng, 450, 1.0, 5),
        )
        src = world.main_account[p["person_id"]]
        dst = acct["account_id"]
        day_of_month = rng.randrange(1, 28)
        for d in world.days():
            if d.day != day_of_month:
                continue
            ts = ts_on(rng, d, "evening")
            txs.append(make_tx(
                ts, src, dst,
                lognormal_amount(rng, max(60, p["declared_monthly_income"] * 0.10),
                                 0.6, 20, 3000),
                "transfer", "Alimentation compte", "mobile", pick_status(rng),
                src_country="FR", dst_country=bank["country"],
                split=world.split_of(ts),
            ))
        for _ in range(rng.randrange(2, 12)):
            d = rng.choice(world.days())
            ts = ts_on(rng, d, "diurnal")
            m_acct, m_country, m_sector = rng.choice(foreign_merchants)
            txs.append(make_tx(
                ts, dst, m_acct,
                lognormal_amount(rng, 32, 0.9, 3, 900), "retail",
                rng.choice(N.MERCHANT_LABELS.get(m_sector, ["Achat"])),
                "mobile", pick_status(rng),
                src_country=bank["country"], dst_country=m_country,
                split=world.split_of(ts),
            ))
    return txs


def _travel_abroad(world):
    """Sejours a l'etranger: rafale de depenses hors de France."""
    rng = world.rng
    txs = []
    merchants = _ensure_foreign_companies(world)
    for p in world.persons:
        if rng.random() > 0.20:
            continue
        days = world.days()
        start_idx = rng.randrange(0, max(1, len(days) - 12))
        length = rng.randrange(3, 13)
        trip = days[start_idx:start_idx + length]
        local = rng.sample(merchants, min(rng.randrange(3, 9), len(merchants)))
        src = world.main_account[p["person_id"]]
        for d in trip:
            for _ in range(rng.randrange(0, 4)):
                m_acct, m_country, m_sector = rng.choice(local)
                ts = ts_on(rng, d, "diurnal")
                txs.append(make_tx(
                    ts, src, m_acct,
                    lognormal_amount(
                        rng, max(12, p["declared_monthly_income"] * 0.02), 0.9,
                        4, 2500),
                    "retail", rng.choice(N.MERCHANT_LABELS.get(m_sector, ["Achat"])),
                    weighted_choice(rng, [("mobile", 0.7), ("web", 0.3)]),
                    pick_status(rng), src_country="FR", dst_country=m_country,
                    split=world.split_of(ts),
                ))
    return txs


def _cross_border_b2b(world):
    """Fournisseurs etrangers: virements professionnels transfrontaliers."""
    rng = world.rng
    txs = []
    merchants = _ensure_foreign_companies(world)
    domestic = [c for c in world.companies if c["country"] == "FR"]
    for c in domestic:
        if rng.random() > 0.30:
            continue
        src = world.main_account[c["company_id"]]
        suppliers = rng.sample(merchants, min(rng.randrange(1, 4), len(merchants)))
        for _ in range(rng.randrange(1, 9)):
            m_acct, m_country, _ = rng.choice(suppliers)
            d = rng.choice(world.days())
            ts = ts_on(rng, next_business_day(d), "business")
            txs.append(make_tx(
                ts, src, m_acct,
                lognormal_amount(rng, c["declared_monthly_revenue"] * 0.05, 0.9,
                                 100, 300_000),
                "b2b_invoice", f"Facture import {rng.randrange(1000, 9999)}",
                "web", pick_status(rng), src_country="FR", dst_country=m_country,
                split=world.split_of(ts),
            ))
    return txs


# ---------------------------------------------------------------- autres flux

def _b2b(world):
    rng = world.rng
    txs = []
    domestic = [c for c in world.companies if c["country"] == "FR"]
    accounts = [world.main_account[c["company_id"]] for c in domestic]
    suppliers = {
        c["company_id"]: rng.sample(accounts, min(rng.randrange(2, 9), len(accounts)))
        for c in domestic
    }
    for c in domestic:
        src = world.main_account[c["company_id"]]
        rate = {"TPE": 0.10, "PME": 0.45, "ETI": 1.6}[c["size_band"]]
        for d in world.days():
            if d.weekday() >= 5:
                continue
            n = int(rng.gauss(rate, 0.8)) if rate > 1 else (1 if rng.random() < rate else 0)
            for _ in range(max(0, n)):
                dst = rng.choice(suppliers[c["company_id"]])
                if dst == src:
                    continue
                ts = ts_on(rng, d, "business")
                txs.append(make_tx(
                    ts, src, dst,
                    lognormal_amount(rng, c["declared_monthly_revenue"] * 0.04,
                                     0.9, 50, 400_000),
                    "b2b_invoice", f"Facture {rng.randrange(1000, 9999)}", "web",
                    pick_status(rng), split=world.split_of(ts),
                ))
    return txs


def _donations(world):
    rng = world.rng
    txs = []
    assoc = [world.main_account[a["association_id"]] for a in world.associations]
    if not assoc:
        return txs
    for p in world.persons:
        if rng.random() > 0.18:
            continue
        src = world.main_account[p["person_id"]]
        for _ in range(rng.randrange(1, 4)):
            ts = ts_on(rng, rng.choice(world.days()), "evening")
            txs.append(make_tx(
                ts, src, rng.choice(assoc),
                lognormal_amount(rng, 25, 0.8, 5, 400), "donation", "Don",
                weighted_choice(rng, [("web", 0.6), ("mobile", 0.4)]),
                pick_status(rng), split=world.split_of(ts),
            ))
    return txs


def _refunds(world):
    rng = world.rng
    txs = []
    payers = [world.main_account[c["company_id"]] for c in world.companies
              if c["country"] == "FR"
              and c["sector"] in ("assurance", "sante", "commerce_equipement")]
    if not payers:
        return txs
    for p in world.persons:
        if rng.random() > 0.22:
            continue
        for _ in range(rng.randrange(1, 3)):
            ts = ts_on(rng, rng.choice(world.days()), "business")
            txs.append(make_tx(
                ts, rng.choice(payers), world.main_account[p["person_id"]],
                lognormal_amount(rng, 95, 1.0, 8, 4000), "refund",
                "Remboursement", "web", pick_status(rng),
                split=world.split_of(ts),
            ))
    return txs


def _large_purchases(world):
    """Anomalie legitime: un achat exceptionnellement eleve."""
    rng = world.rng
    txs = []
    for p in world.persons:
        if rng.random() > 0.10:
            continue
        ts = ts_on(rng, rng.choice(world.days()), "diurnal")
        txs.append(make_tx(
            ts, world.main_account[p["person_id"]],
            rng.choice(world.merchant_accounts),
            p["declared_monthly_income"] * rng.uniform(1.8, 6.5),
            "large_purchase",
            rng.choice(["Achat mobilier", "Travaux", "Voyage", "Electromenager",
                        "Achat velo electrique", "Reparation vehicule"]),
            weighted_choice(rng, [("web", 0.45), ("mobile", 0.35),
                                  ("branch", 0.20)]),
            pick_status(rng), split=world.split_of(ts),
        ))
    return txs


# ---------------------------------------------------------------- remplissage

def _retail(world, n):
    rng = world.rng
    txs = []
    persons = world.persons
    weights = [0.4 + p["declared_monthly_income"] / 2500.0 for p in persons]
    days = world.days()
    day_weights = [1.15 if d.weekday() >= 5 else 1.0 for d in days]
    sector_of = {c["company_id"]: c["sector"] for c in world.companies}

    for _ in range(max(0, n)):
        p = rng.choices(persons, weights=weights, k=1)[0]
        d = rng.choices(days, weights=day_weights, k=1)[0]
        habitual = world.habitual_merchants[p["person_id"]]
        dst = (rng.choice(habitual) if habitual and rng.random() < 0.90
               else rng.choice(world.merchant_accounts))
        src = world.main_account[p["person_id"]]
        if dst == src:
            continue
        sector = sector_of.get(world.account(dst)["owner_id"], "commerce_alimentaire")
        ts = ts_on(rng, d, "diurnal")
        txs.append(make_tx(
            ts, src, dst,
            lognormal_amount(rng, max(9, p["declared_monthly_income"] * 0.013),
                             0.85, 2, 1800),
            "retail", rng.choice(N.MERCHANT_LABELS.get(sector, ["Achat"])),
            weighted_choice(rng, [("mobile", 0.58), ("web", 0.34),
                                  ("branch", 0.08)]),
            pick_status(rng), split=world.split_of(ts),
        ))
    return txs


def _p2p(world, n):
    rng = world.rng
    txs = []
    persons = [p for p in world.persons if world.contacts.get(p["person_id"])]
    days = world.days()
    day_weights = [1.45 if d.weekday() >= 5 else 1.0 for d in days]

    for _ in range(max(0, n)):
        p = rng.choice(persons)
        dst = world.main_account.get(rng.choice(world.contacts[p["person_id"]]))
        src = world.main_account[p["person_id"]]
        if not dst or dst == src:
            continue
        d = rng.choices(days, weights=day_weights, k=1)[0]
        ts = ts_on(rng, d, "evening")
        txs.append(make_tx(
            ts, src, dst,
            lognormal_amount(rng, max(12, p["declared_monthly_income"] * 0.018),
                             0.95, 3, 2500),
            "p2p", rng.choice(N.P2P_LABELS),
            weighted_choice(rng, [("mobile", 0.78), ("web", 0.20),
                                  ("branch", 0.02)]),
            pick_status(rng), split=world.split_of(ts),
        ))
    return txs
