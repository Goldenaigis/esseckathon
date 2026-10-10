"""Orchestrateur du generateur FraudNet.

    python -m fraudnet.generator.generate --out fraudnet/data

Produit 8 fichiers CSV + un manifest.json. Aucune dependance externe.
"""

import argparse
import csv
import json
import os
import random
import time
from datetime import datetime, timedelta

from ..shared.schema import DATA_FILES, SCHEMA_VERSION
from . import names as N
from .config import Config
from .decoys import generate_decoys
from .fraud import generate_fraud
from .legit import generate_legit
from .world import World, lognormal_amount


def _register_orphan_owners(world):
    """Cree les fiches des titulaires de comptes crees par les scenarios.

    Les comptes de mules et les beneficiaires etrangers sont ouverts a la
    volee; on leur attache une fiche personne pour garder l'integrite
    referentielle entre accounts et persons.
    """
    rng = world.rng
    csp_pool = ["employe", "etudiant", "sans_emploi", "ouvrier",
                "artisan_commercant", "cadre"]
    for a in world.accounts:
        if a["owner_type"] != "person" or a["owner_id"]:
            continue
        pid = world.next_id("person", "PER_", 6)
        first, last = (a["owner_name"].split(" ", 1) + [""])[:2]
        age = rng.randrange(19, 58)
        birth = world.window_start - timedelta(days=age * 365 + rng.randrange(365))
        csp = rng.choice(csp_pool)
        world.persons.append({
            "person_id": pid,
            "first_name": first,
            "last_name": last,
            "birth_date": birth.date().isoformat(),
            "age": age,
            "age_band": "18-30" if age < 30 else ("30-60" if age < 60 else "60+"),
            "csp": csp,
            "employer_id": "",
            "city": "" if a["country"] != "FR" else
                    N.CITIES[rng.randrange(len(N.CITIES))][0],
            "country": a["country"],
            "declared_monthly_income": round(rng.uniform(600, 3200), 2),
            "sim_digital_literacy": round(rng.uniform(0.3, 0.95), 3),
            "gt_role": a["gt_role"],
            "gt_scenario_id": a["gt_scenario_id"],
        })
        a["owner_id"] = pid
        world.main_account.setdefault(pid, a["account_id"])


def _finalize_transactions(world, txs):
    """Fenetre, tri, attribution des identifiants, partition."""
    start, end = world.window_start, world.window_end
    kept = [t for t in txs if start <= t["ts"] < end]
    for t in kept:
        t["ts"] = t["ts"].replace(microsecond=0)
    kept.sort(key=lambda t: (t["ts"], t["src_account"], t["dst_account"]))
    for i, t in enumerate(kept, start=1):
        t["tx_id"] = f"TX_{i:07d}"
        if not t["gt_split"]:
            t["gt_split"] = world.split_of(t["ts"])
    return kept


def _recompute_groups(records, txs, id_key, gt_key):
    """Recalcule les agregats apres filtrage sur la fenetre."""
    by_id = {}
    for t in txs:
        gid = t[gt_key]
        if gid:
            by_id.setdefault(gid, []).append(t)
    out = []
    for r in records:
        group = by_id.get(r[id_key], [])
        if not group:
            continue
        r["n_transactions"] = len(group)
        r["total_amount"] = round(sum(t["amount"] for t in group), 2)
        r["start_ts"] = min(t["ts"] for t in group).isoformat()
        r["end_ts"] = max(t["ts"] for t in group).isoformat()
        if "duration_hours" in r:
            s = datetime.fromisoformat(r["start_ts"])
            e = datetime.fromisoformat(r["end_ts"])
            r["duration_hours"] = round((e - s).total_seconds() / 3600, 2)
        out.append(r)
    return out


def _update_balances(world, txs):
    """Solde de fin de fenetre coherent avec les flux observes."""
    delta = {}
    for t in txs:
        if t["status"] != "completed":
            continue
        delta[t["src_account"]] = delta.get(t["src_account"], 0) - t["amount"]
        delta[t["dst_account"]] = delta.get(t["dst_account"], 0) + t["amount"]
    for a in world.accounts:
        a["balance"] = round(max(0.0, a["balance"] + delta.get(a["account_id"], 0)), 2)


def _write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            out = dict(r)
            for k, v in out.items():
                if isinstance(v, datetime):
                    out[k] = v.isoformat()
            w.writerow(out)


def run(cfg, out_dir):
    t0 = time.time()
    rng = random.Random(cfg.seed)
    world = World(cfg, rng).build()
    print(f"[1/6] Population: {len(world.persons)} personnes, "
          f"{len(world.companies)} entreprises, "
          f"{len(world.associations)} associations, "
          f"{len(world.accounts)} comptes")

    legit = generate_legit(world)
    print(f"[2/6] Flux legitimes: {len(legit)} transactions")

    used = set()
    scenarios, fraud_tx = generate_fraud(world, used)
    print(f"[3/6] Fraude: {len(scenarios)} scenarios, {len(fraud_tx)} transactions")

    decoys, decoy_tx = generate_decoys(world, used)
    print(f"[4/6] Faux amis: {len(decoys)} instances, {len(decoy_tx)} transactions")

    _register_orphan_owners(world)
    txs = _finalize_transactions(world, legit + fraud_tx + decoy_tx)
    scenarios = _recompute_groups(scenarios, txs, "scenario_id", "gt_scenario_id")
    decoys = _recompute_groups(decoys, txs, "decoy_id", "gt_decoy_id")
    world.finalize_accounts()
    _update_balances(world, txs)

    n_fraud = sum(t["gt_is_fraud"] for t in txs)
    print(f"[5/6] Total: {len(txs)} transactions, {n_fraud} frauduleuses "
          f"({100 * n_fraud / max(1, len(txs)):.2f} %)")

    os.makedirs(out_dir, exist_ok=True)
    tables = {
        "banks": world.banks,
        "persons": world.persons,
        "companies": world.companies,
        "associations": world.associations,
        "accounts": world.accounts,
        "transactions": txs,
        "scenarios": scenarios,
        "decoys": decoys,
    }
    for key, (fname, columns) in DATA_FILES.items():
        _write_csv(os.path.join(out_dir, fname), columns, tables[key])

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generation_seconds": round(time.time() - t0, 1),
        "config": cfg.to_dict(),
        "window": {
            "start": world.window_start.isoformat(),
            "end": world.window_end.isoformat(),
            "split_boundary": world.split_boundary.isoformat(),
        },
        "counts": {k: len(v) for k, v in tables.items()},
        "fraud_transactions": n_fraud,
        "fraud_rate": round(n_fraud / max(1, len(txs)), 5),
        "decoy_transactions": sum(1 for t in txs if t["gt_decoy_id"]),
        "files": {k: v[0] for k, v in DATA_FILES.items()},
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"[6/6] Ecrit dans {out_dir} en {manifest['generation_seconds']} s")
    return world, txs, scenarios, decoys


def main():
    cfg = Config()
    ap = argparse.ArgumentParser(description="Generateur de donnees FraudNet")
    ap.add_argument("--out", default="fraudnet/data")
    ap.add_argument("--seed", type=int, default=cfg.seed)
    ap.add_argument("--persons", type=int, default=cfg.n_persons)
    ap.add_argument("--companies", type=int, default=cfg.n_companies)
    ap.add_argument("--associations", type=int, default=cfg.n_associations)
    ap.add_argument("--transactions", type=int, default=cfg.target_transactions)
    ap.add_argument("--scenarios", type=int, default=None,
                    help="par defaut, mis a l'echelle du volume de transactions")
    ap.add_argument("--decoys", type=int, default=None,
                    help="par defaut, mis a l'echelle du volume de transactions")
    ap.add_argument("--days", type=int, default=cfg.window_days)
    ap.add_argument("--train-days", type=int, default=cfg.train_days)
    args = ap.parse_args()

    cfg.seed = args.seed
    cfg.n_persons = args.persons
    cfg.n_companies = args.companies
    cfg.n_associations = args.associations
    # Le nombre de scenarios suit le volume: sinon un jeu reduit se retrouve
    # avec un taux de fraude irrealiste et un probleme artificiellement facile.
    scale = args.transactions / cfg.target_transactions
    cfg.target_transactions = args.transactions
    cfg.n_fraud_scenarios = (args.scenarios if args.scenarios is not None
                             else max(7, round(cfg.n_fraud_scenarios * scale)))
    cfg.n_decoys = (args.decoys if args.decoys is not None
                    else max(7, round(cfg.n_decoys * scale)))
    cfg.window_days = args.days
    cfg.train_days = args.train_days
    run(cfg, args.out)


if __name__ == "__main__":
    main()
