"""
Generateur de donnees JOUET (le "faux M1") pour debloquer M2 (cartographie).

Ce module cree une base SQLite conforme au contrat de donnees (schemas.py)
contenant :
  - du bruit legitime (trafic bancaire normal),
  - un COMPTE COLLECTEUR en etoile (fan-in massif),
  - un SABLIER (collecte + redistribution rapide),
  - une CHAINE de relais (A -> B -> C -> D -> etranger),
  - un CYCLE financier (A -> B -> C -> A).

Quand la vraie equipe M1 livrera ses donnees, il suffira de pointer M2 sur
leur base SQLite : le schema des tables est identique, le code de M2 ne change pas.

Usage :
    python -m backend.module1_data.fixtures            # ecrit data/bank.db
    python -m backend.module1_data.fixtures --seed 7   # reproductible
"""
from __future__ import annotations

import argparse
import os
import random
import sqlite3
from datetime import datetime, timedelta

# Import tolerant : fonctionne lance comme module ou comme script.
try:
    from backend.common import schemas as S
except ModuleNotFoundError:  # lance directement depuis le dossier
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from backend.common import schemas as S


BANKS = ["BNP", "SocGen", "CreditAgricole", "LCL", "Revolut", "N26"]
COUNTRIES = ["FR", "FR", "FR", "FR", "BE", "DE", "ES"]  # FR majoritaire
FOREIGN = ["CY", "MT", "AE", "PA"]                      # destinations "a risque"
CHANNELS = ["mobile", "mobile", "web", "branch"]        # mobile majoritaire

T0 = datetime(2026, 1, 10, 8, 0, 0)  # debut de la fenetre simulee


class _Gen:
    """Petit etat partage : compteurs d'IDs + accumulateurs."""

    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.accounts: list[S.Account] = []
        self.transactions: list[S.Transaction] = []
        self._by_id: dict[str, S.Account] = {}
        self._acc_n = 0
        self._tx_n = 0

    # --- fabriques d'entites ------------------------------------------------
    def new_account(self, customer_type=S.CUSTOMER_INDIVIDUAL, country=None,
                    is_fraudster=0, dormant=False) -> str:
        self._acc_n += 1
        acc_id = f"ACC_{self._acc_n:06d}"
        age_days = self.rng.randint(5, 60) if dormant else self.rng.randint(90, 3650)
        opened = (T0 - timedelta(days=age_days)).strftime("%Y-%m-%d")
        acc = S.Account(
            account_id=acc_id,
            bank=self.rng.choice(BANKS),
            country=country or self.rng.choice(COUNTRIES),
            opened_date=opened,
            balance=round(self.rng.uniform(200, 25000), 2),
            customer_type=customer_type,
            is_fraudster=is_fraudster,
        )
        self.accounts.append(acc)
        self._by_id[acc_id] = acc
        return acc_id

    def new_tx(self, src, dst, amount, when, status=S.STATUS_LEGITIMATE,
               is_fraud=0, scenario_id=None, channel=None) -> str:
        self._tx_n += 1
        tx_id = f"TX_{self._tx_n:07d}"
        sc = self._country_of(src)
        dc = self._country_of(dst)
        self.transactions.append(S.Transaction(
            tx_id=tx_id,
            src_account=src,
            dst_account=dst,
            amount=round(float(amount), 2),
            timestamp=when.strftime("%Y-%m-%dT%H:%M:%S"),
            src_country=sc,
            dst_country=dc,
            channel=channel or self.rng.choice(CHANNELS),
            status=status,
            is_fraud=is_fraud,
            scenario_id=scenario_id,
        ))
        return tx_id

    def _country_of(self, acc_id) -> str:
        return self._by_id.get(acc_id).country if acc_id in self._by_id else "FR"

    def type_of(self, acc_id) -> str:
        a = self._by_id.get(acc_id)
        return a.customer_type if a else S.CUSTOMER_INDIVIDUAL


# --- Scenarios --------------------------------------------------------------

def _realistic_when(g: _Gen, days_span: int) -> datetime:
    """Horodatage plausible : jours ouvres favorises, pics en journee, creux la nuit."""
    day = g.rng.randint(0, days_span)
    # heures : forte densite 8h-20h, faible la nuit
    hour = g.rng.choices(
        population=list(range(24)),
        weights=[1, 1, 1, 1, 1, 2, 4, 7, 9, 10, 10, 9, 8, 9, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1],
        k=1,
    )[0]
    minute = g.rng.randint(0, 59)
    return T0 + timedelta(days=day, hours=hour, minutes=minute)


def legitimate_noise(g: _Gen, n_accounts=600, n_tx=5000, days_span=30):
    """
    Trafic normal realiste :
      - comptes ordinaires varies (individual / business / senior),
      - beneficiaires RECURRENTS (on paie souvent les memes : salaire, loyer, commerces),
      - montants log-normaux (majorite petits), horaires plausibles,
      - quelques anomalies NON frauduleuses (gros achat ponctuel legitime,
        compte dormant qui se reveille normalement).
    """
    accs = [g.new_account(customer_type=g.rng.choices(
        [S.CUSTOMER_INDIVIDUAL, S.CUSTOMER_BUSINESS, S.CUSTOMER_SENIOR],
        weights=[70, 20, 10], k=1)[0])
        for _ in range(n_accounts)]

    # chaque compte a 1 a 4 beneficiaires habituels -> transactions recurrentes
    habitual = {a: g.rng.sample([x for x in accs if x != a],
                                 k=g.rng.randint(1, 4)) for a in accs}

    for _ in range(n_tx):
        src = g.rng.choice(accs)
        # 70% vers un beneficiaire habituel, 30% vers un compte quelconque
        if g.rng.random() < 0.70 and habitual[src]:
            dst = g.rng.choice(habitual[src])
        else:
            dst = g.rng.choice([x for x in accs if x != src])
        amount = round(g.rng.lognormvariate(4.2, 0.9), 2)  # majorite petits montants
        g.new_tx(src, dst, amount, _realistic_when(g, days_span))

    # anomalies NON frauduleuses (pour ne pas confondre "inhabituel" et "fraude")
    for _ in range(max(3, n_accounts // 100)):
        s, d = g.rng.sample(accs, 2)
        g.new_tx(s, d, round(g.rng.uniform(8000, 15000), 2),
                 _realistic_when(g, days_span))  # gros achat legitime ponctuel
    return accs


def _pick_victims(g: _Gen, pool, k, prefer_senior=True):
    """Choisit k victimes parmi les comptes legitimes existants (plus credible)."""
    if not pool:
        return [g.new_account() for _ in range(k)]
    if prefer_senior:
        seniors = [a for a in pool if g.type_of(a) == S.CUSTOMER_SENIOR]
        others = [a for a in pool if a not in seniors]
        g.rng.shuffle(seniors)
        g.rng.shuffle(others)
        ordered = seniors + others
    else:
        ordered = list(pool)
        g.rng.shuffle(ordered)
    return ordered[:k]


def scenario_collector_star(g: _Gen, sid, pool, n_senders=None):
    """S1 - Etoile de collecte : n emetteurs (victimes) -> 1 collecteur, en ~2h."""
    n_senders = n_senders or g.rng.randint(12, 28)
    collector = g.new_account(customer_type=S.CUSTOMER_INDIVIDUAL,
                              is_fraudster=1, dormant=True)
    start = T0 + timedelta(days=g.rng.randint(1, 25), hours=g.rng.randint(8, 18))
    for sender in _pick_victims(g, pool, n_senders):
        amount = round(g.rng.uniform(300, 2500), 2)   # credible isolement
        when = start + timedelta(minutes=g.rng.randint(0, 120))
        g.new_tx(sender, collector, amount, when,
                 status=S.STATUS_CONFIRMED_FRAUD, is_fraud=1, scenario_id=sid)
    return collector, sid


def scenario_hourglass(g: _Gen, sid, pool, n_senders=None, n_mules=3):
    """S2 - Sablier : collecte (fan-in) PUIS redistribution rapide (fan-out)."""
    n_senders = n_senders or g.rng.randint(10, 18)
    hub = g.new_account(customer_type=S.CUSTOMER_INDIVIDUAL,
                        is_fraudster=1, dormant=True)
    start = T0 + timedelta(days=g.rng.randint(1, 25), hours=g.rng.randint(8, 16))
    total = 0.0
    for sender in _pick_victims(g, pool, n_senders):
        amount = round(g.rng.uniform(500, 3000), 2)
        total += amount
        when = start + timedelta(minutes=g.rng.randint(0, 90))
        g.new_tx(sender, hub, amount, when,
                 status=S.STATUS_CONFIRMED_FRAUD, is_fraud=1, scenario_id=sid)
    # redistribution rapide de ~85% vers quelques mules a l'etranger
    out_mules = [g.new_account(is_fraudster=1, country=g.rng.choice(FOREIGN),
                               dormant=True) for _ in range(n_mules)]
    redis = start + timedelta(hours=2, minutes=g.rng.randint(0, 40))
    share = (total * 0.85) / n_mules
    for m in out_mules:
        when = redis + timedelta(minutes=g.rng.randint(0, 20))
        g.new_tx(hub, m, round(share, 2), when,
                 status=S.STATUS_CONFIRMED_FRAUD, is_fraud=1, scenario_id=sid)
    return hub, sid


def scenario_relay_chain(g: _Gen, sid, pool, length=None):
    """S3 - Chaine de relais : A -> B -> C -> D -> etranger."""
    length = length or g.rng.randint(4, 6)
    # la source est une victime existante, les relais sont des comptes mules
    source = _pick_victims(g, pool, 1, prefer_senior=False)[0] if pool else \
        g.new_account(is_fraudster=1)
    chain = [source]
    chain += [g.new_account(is_fraudster=1, dormant=True) for _ in range(length - 2)]
    chain.append(g.new_account(is_fraudster=1, country=g.rng.choice(FOREIGN),
                               dormant=True))
    amount = round(g.rng.uniform(8000, 12000), 2)
    when = T0 + timedelta(days=g.rng.randint(1, 25), hours=g.rng.randint(8, 16))
    for a, b in zip(chain[:-1], chain[1:]):
        amount = round(amount * g.rng.uniform(0.95, 0.99), 2)  # petites "pertes"
        when = when + timedelta(minutes=g.rng.randint(10, 40))
        g.new_tx(a, b, amount, when,
                 status=S.STATUS_CONFIRMED_FRAUD, is_fraud=1, scenario_id=sid)
    return chain, sid


def scenario_cycle(g: _Gen, sid, size=None):
    """S4 - Cycle financier : A -> B -> C -> A (montants quasi identiques, rapide)."""
    size = size or g.rng.randint(3, 5)
    ring = [g.new_account(customer_type=S.CUSTOMER_BUSINESS, is_fraudster=1)
            for _ in range(size)]
    amount = round(g.rng.uniform(4000, 7000), 2)
    when = T0 + timedelta(days=g.rng.randint(1, 25), hours=g.rng.randint(8, 16))
    for i in range(size):
        a = ring[i]
        b = ring[(i + 1) % size]  # dernier -> premier => cycle
        when = when + timedelta(minutes=g.rng.randint(15, 45))
        g.new_tx(a, b, amount, when,
                 status=S.STATUS_CONFIRMED_FRAUD, is_fraud=1, scenario_id=sid)
    return ring, sid


def scenario_smurfing(g: _Gen, sid, pool, n_splits=None):
    """S5 - Fractionnement : un gros transfert eclate en N petits virements
    sous un seuil (ex. ~9900), vers un meme beneficiaire, en peu de temps."""
    n_splits = n_splits or g.rng.randint(8, 16)
    source = _pick_victims(g, pool, 1, prefer_senior=False)[0] if pool else \
        g.new_account(is_fraudster=1)
    beneficiary = g.new_account(is_fraudster=1, country=g.rng.choice(FOREIGN),
                                dormant=True)
    start = T0 + timedelta(days=g.rng.randint(1, 25), hours=g.rng.randint(8, 16))
    threshold = g.rng.choice([9900, 9500, 4900])  # juste sous un seuil "rond"
    for _ in range(n_splits):
        amount = round(threshold - g.rng.uniform(0, 400), 2)
        when = start + timedelta(minutes=g.rng.randint(0, 180))
        g.new_tx(source, beneficiary, amount, when,
                 status=S.STATUS_CONFIRMED_FRAUD, is_fraud=1, scenario_id=sid)
    return beneficiary, sid


# --- Ecriture SQLite --------------------------------------------------------

def build(seed: int = 42, n_accounts: int = 600, n_tx: int = 5000,
          days_span: int = 30, fraud_rings: int = 10) -> _Gen:
    """
    Construit une base realiste :
      - un fond de trafic legitime (n_accounts, n_tx),
      - `fraud_rings` instances de fraude reparties sur les 5 typologies,
        chacune avec un scenario_id UNIQUE (indispensable pour l'anti-fuite M3).
    """
    g = _Gen(seed)
    pool = legitimate_noise(g, n_accounts=n_accounts, n_tx=n_tx, days_span=days_span)

    # repartition variee des typologies (ponderee vers les plus "visuelles")
    builders = [
        ("S1_COLLECTOR", lambda sid: scenario_collector_star(g, sid, pool)),
        ("S2_HOURGLASS", lambda sid: scenario_hourglass(g, sid, pool)),
        ("S3_CHAIN",     lambda sid: scenario_relay_chain(g, sid, pool)),
        ("S4_CYCLE",     lambda sid: scenario_cycle(g, sid)),
        ("S5_SMURFING",  lambda sid: scenario_smurfing(g, sid, pool)),
    ]
    weights = [3, 3, 2, 1, 2]  # plus de collecteurs/sabliers/smurfing
    for i in range(fraud_rings):
        prefix, fn = g.rng.choices(builders, weights=weights, k=1)[0]
        fn(f"{prefix}_{i:02d}")  # scenario_id unique par instance
    return g


def write_sqlite(g: _Gen, db_path: str) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE accounts (
            account_id   TEXT PRIMARY KEY,
            bank         TEXT,
            country      TEXT,
            opened_date  TEXT,
            balance      REAL,
            customer_type TEXT,
            is_fraudster INTEGER
        );
        CREATE TABLE transactions (
            tx_id        TEXT PRIMARY KEY,
            src_account  TEXT,
            dst_account  TEXT,
            amount       REAL,
            timestamp    TEXT,
            src_country  TEXT,
            dst_country  TEXT,
            channel      TEXT,
            status       TEXT,
            is_fraud     INTEGER,
            scenario_id  TEXT
        );
        """
    )
    cur.executemany(
        "INSERT INTO accounts VALUES (:account_id,:bank,:country,:opened_date,"
        ":balance,:customer_type,:is_fraudster)",
        [a.to_dict() for a in g.accounts],
    )
    cur.executemany(
        "INSERT INTO transactions VALUES (:tx_id,:src_account,:dst_account,:amount,"
        ":timestamp,:src_country,:dst_country,:channel,:status,:is_fraud,:scenario_id)",
        [t.to_dict() for t in g.transactions],
    )
    con.commit()
    con.close()


PRESETS = {
    #            n_accounts, n_tx,  fraud_rings
    "small":   (120,   400,   4),
    "medium":  (600,   5000,  10),
    "large":   (2000,  20000, 25),
}


def main():
    ap = argparse.ArgumentParser(description="Generateur de donnees jouet (faux M1)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--db", default=os.path.join("data", "bank.db"))
    ap.add_argument("--size", choices=PRESETS.keys(), default="medium",
                    help="taille de la base (small/medium/large)")
    ap.add_argument("--accounts", type=int, help="nb de comptes legitimes (override)")
    ap.add_argument("--transactions", type=int, help="nb de transactions legitimes (override)")
    ap.add_argument("--fraud-rings", type=int, help="nb d'instances de fraude (override)")
    ap.add_argument("--days", type=int, default=30, help="fenetre temporelle en jours")
    args = ap.parse_args()

    n_acc, n_tx, rings = PRESETS[args.size]
    if args.accounts is not None:
        n_acc = args.accounts
    if args.transactions is not None:
        n_tx = args.transactions
    if args.fraud_rings is not None:
        rings = args.fraud_rings

    g = build(args.seed, n_accounts=n_acc, n_tx=n_tx,
              days_span=args.days, fraud_rings=rings)
    write_sqlite(g, args.db)

    frauds = sum(t.is_fraud for t in g.transactions)
    scenarios = sorted({t.scenario_id for t in g.transactions if t.scenario_id})
    by_type: dict[str, int] = {}
    for t in g.transactions:
        if t.scenario_id:
            key = t.scenario_id.rsplit("_", 1)[0]
            by_type[key] = by_type.get(key, 0) + 1

    print(f"OK -> {args.db}  (preset: {args.size})")
    print(f"   comptes       : {len(g.accounts)}")
    print(f"   transactions  : {len(g.transactions)}")
    print(f"   dont fraude   : {frauds} ({100*frauds/len(g.transactions):.2f}%)")
    print(f"   anneaux fraude: {len(scenarios)} instances")
    for k in sorted(by_type):
        print(f"      - {k:<14}: {by_type[k]} transactions")


if __name__ == "__main__":
    main()
