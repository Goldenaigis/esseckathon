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
        self._acc_n = 0
        self._tx_n = 0

    # --- fabriques d'entites ------------------------------------------------
    def new_account(self, customer_type=S.CUSTOMER_INDIVIDUAL, country=None,
                    is_fraudster=0, dormant=False) -> str:
        self._acc_n += 1
        acc_id = f"ACC_{self._acc_n:06d}"
        age_days = self.rng.randint(5, 60) if dormant else self.rng.randint(90, 3650)
        opened = (T0 - timedelta(days=age_days)).strftime("%Y-%m-%d")
        self.accounts.append(S.Account(
            account_id=acc_id,
            bank=self.rng.choice(BANKS),
            country=country or self.rng.choice(COUNTRIES),
            opened_date=opened,
            balance=round(self.rng.uniform(200, 25000), 2),
            customer_type=customer_type,
            is_fraudster=is_fraudster,
        ))
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
        for a in self.accounts:
            if a.account_id == acc_id:
                return a.country
        return "FR"


# --- Scenarios --------------------------------------------------------------

def legitimate_noise(g: _Gen, n_accounts=40, n_tx=120):
    """Trafic normal : virements entre comptes ordinaires, montants plausibles."""
    accs = [g.new_account(customer_type=g.rng.choice(
        [S.CUSTOMER_INDIVIDUAL, S.CUSTOMER_INDIVIDUAL, S.CUSTOMER_BUSINESS]))
        for _ in range(n_accounts)]
    for _ in range(n_tx):
        src, dst = g.rng.sample(accs, 2)
        amount = round(g.rng.lognormvariate(4.0, 0.9), 2)  # majorite petits montants
        when = T0 + timedelta(minutes=g.rng.randint(0, 60 * 24 * 7))
        g.new_tx(src, dst, amount, when)
    # Une anomalie NON frauduleuse : un gros achat ponctuel legitime.
    big_src, big_dst = g.rng.sample(accs, 2)
    g.new_tx(big_src, big_dst, 9800.0, T0 + timedelta(hours=30))
    return accs


def scenario_collector_star(g: _Gen, n_senders=27):
    """S1 - Etoile de collecte : n emetteurs -> 1 collecteur, en ~2h."""
    sid = "S1_COLLECTOR"
    collector = g.new_account(customer_type=S.CUSTOMER_INDIVIDUAL,
                              is_fraudster=1, dormant=True)
    start = T0 + timedelta(days=2, hours=9)
    for i in range(n_senders):
        # melange de profils, dont des seniors (cible classique)
        ctype = g.rng.choice([S.CUSTOMER_SENIOR, S.CUSTOMER_SENIOR,
                              S.CUSTOMER_INDIVIDUAL])
        sender = g.new_account(customer_type=ctype)
        amount = round(g.rng.uniform(300, 2500), 2)   # credible isolement
        when = start + timedelta(minutes=g.rng.randint(0, 120))
        g.new_tx(sender, collector, amount, when,
                 status=S.STATUS_CONFIRMED_FRAUD, is_fraud=1, scenario_id=sid)
    return collector, sid


def scenario_hourglass(g: _Gen, n_senders=15, n_mules=3):
    """S2 - Sablier : collecte (fan-in) PUIS redistribution rapide (fan-out)."""
    sid = "S2_HOURGLASS"
    hub = g.new_account(customer_type=S.CUSTOMER_INDIVIDUAL,
                        is_fraudster=1, dormant=True)
    start = T0 + timedelta(days=3, hours=10)
    total = 0.0
    for i in range(n_senders):
        sender = g.new_account(customer_type=g.rng.choice(
            [S.CUSTOMER_SENIOR, S.CUSTOMER_INDIVIDUAL]))
        amount = round(g.rng.uniform(500, 3000), 2)
        total += amount
        when = start + timedelta(minutes=g.rng.randint(0, 90))
        g.new_tx(sender, hub, amount, when,
                 status=S.STATUS_CONFIRMED_FRAUD, is_fraud=1, scenario_id=sid)
    # redistribution rapide de ~85% vers quelques mules a l'etranger
    out_mules = [g.new_account(is_fraudster=1, country=g.rng.choice(FOREIGN),
                               dormant=True) for _ in range(n_mules)]
    redis = start + timedelta(hours=2, minutes=10)  # peu apres la collecte
    share = (total * 0.85) / n_mules
    for m in out_mules:
        when = redis + timedelta(minutes=g.rng.randint(0, 20))
        g.new_tx(hub, m, round(share, 2), when,
                 status=S.STATUS_CONFIRMED_FRAUD, is_fraud=1, scenario_id=sid)
    return hub, sid


def scenario_relay_chain(g: _Gen, length=5):
    """S3 - Chaine de relais : A -> B -> C -> D -> etranger."""
    sid = "S3_CHAIN"
    chain = [g.new_account(is_fraudster=1, dormant=True) for _ in range(length - 1)]
    chain.append(g.new_account(is_fraudster=1, country=g.rng.choice(FOREIGN),
                               dormant=True))
    amount = round(g.rng.uniform(8000, 12000), 2)
    when = T0 + timedelta(days=4, hours=11)
    for a, b in zip(chain[:-1], chain[1:]):
        amount = round(amount * g.rng.uniform(0.95, 0.99), 2)  # petites "pertes"
        when = when + timedelta(minutes=g.rng.randint(10, 40))
        g.new_tx(a, b, amount, when,
                 status=S.STATUS_CONFIRMED_FRAUD, is_fraud=1, scenario_id=sid)
    return chain, sid


def scenario_cycle(g: _Gen, size=4):
    """S4 - Cycle financier : A -> B -> C -> A."""
    sid = "S4_CYCLE"
    ring = [g.new_account(customer_type=S.CUSTOMER_BUSINESS, is_fraudster=1)
            for _ in range(size)]
    amount = round(g.rng.uniform(4000, 7000), 2)
    when = T0 + timedelta(days=5, hours=14)
    for i in range(size):
        a = ring[i]
        b = ring[(i + 1) % size]  # dernier -> premier => cycle
        when = when + timedelta(minutes=g.rng.randint(15, 45))
        g.new_tx(a, b, amount, when,
                 status=S.STATUS_CONFIRMED_FRAUD, is_fraud=1, scenario_id=sid)
    return ring, sid


# --- Ecriture SQLite --------------------------------------------------------

def build(seed: int = 42) -> _Gen:
    g = _Gen(seed)
    legitimate_noise(g)
    scenario_collector_star(g)
    scenario_hourglass(g)
    scenario_relay_chain(g)
    scenario_cycle(g)
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


def main():
    ap = argparse.ArgumentParser(description="Generateur de donnees jouet (faux M1)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--db", default=os.path.join("data", "bank.db"))
    args = ap.parse_args()

    g = build(args.seed)
    write_sqlite(g, args.db)
    print(f"OK -> {args.db}")
    print(f"   comptes      : {len(g.accounts)}")
    print(f"   transactions : {len(g.transactions)}")
    frauds = sum(t.is_fraud for t in g.transactions)
    print(f"   dont fraude  : {frauds} ({100*frauds/len(g.transactions):.1f}%)")


if __name__ == "__main__":
    main()
