import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ml.config import ARTIFACTS, PROCESSED, require_data
from ml.features.blocks import ALL_FEATURES, CARRY, GROUND_TRUTH
from ml.features.causal import compute_causal_features

from fraudnet.shared.schema import assert_no_leakage


def load_raw(data_dir=None):
    data_dir = Path(data_dir) if data_dir else require_data()
    accounts = pd.read_csv(data_dir / "accounts.csv", parse_dates=["opened_at"])
    banks = pd.read_csv(data_dir / "banks.csv")
    persons = pd.read_csv(data_dir / "persons.csv")
    transactions = pd.read_csv(data_dir / "transactions.csv", parse_dates=["ts"])
    return accounts, banks, persons, transactions


def _codes(series, mapping=None):
    values = series.astype(str)
    if mapping is None:
        mapping = {v: i for i, v in enumerate(sorted(values.unique()))}
    return values.map(mapping).fillna(-1).astype(int), mapping


def build_features(accounts, banks, persons, transactions, maps=None):
    maps = dict(maps) if maps else {}
    tx = transactions.copy()
    tx = tx.sort_values(["ts", "tx_id"], kind="mergesort").reset_index(drop=True)
    tx["ts_epoch"] = tx["ts"].astype("int64") / 1e9

    domestic = dict(zip(banks["bank_id"], banks["is_domestic"].astype(int)))
    acc = accounts.set_index("account_id")
    opened = acc["opened_at"]
    person_age = persons.set_index("person_id")["age"]
    person_csp = persons.set_index("person_id")["csp"]

    for side, column in (("src", "src_account"), ("dst", "dst_account")):
        ids = tx[column]
        age = (tx["ts"] - ids.map(opened)).dt.total_seconds() / 86400.0
        # 86 comptes du jeu ont une date d'ouverture postérieure à la fenêtre : une
        # ancienneté négative n'a pas de sens, on la déclare inconnue.
        tx[f"{side}_account_age_days"] = age.where(age >= 0)
        tx[f"{side}_owner_name"] = ids.map(acc["owner_name"])
        # NaN pour les comptes entreprise/association : persons.csv ne couvre que les
        # titulaires personnes physiques.
        owner_id = ids.map(acc["owner_id"])
        tx[f"{side}_owner_age"] = owner_id.map(person_age)
        tx[f"{side}_owner_csp"] = owner_id.map(person_csp)

    tx["dst_bank_is_domestic"] = tx["dst_account"].map(acc["bank_id"]).map(domestic).fillna(0).astype(int)
    for name, source in (
        ("channel_code", tx["channel"]),
        ("dst_product_code", tx["dst_account"].map(acc["product"])),
        ("dst_segment_code", tx["dst_account"].map(acc["segment"])),
        ("dst_owner_type_code", tx["dst_account"].map(acc["owner_type"])),
        ("src_owner_csp_code", tx["src_owner_csp"]),
        ("dst_owner_csp_code", tx["dst_owner_csp"]),
    ):
        tx[name], maps[name] = _codes(source, maps.get(name))

    tx["log_amount"] = np.log1p(tx["amount"].clip(lower=0))
    tx["hour"] = tx["ts"].dt.hour
    tx["dayofweek"] = tx["ts"].dt.dayofweek
    tx["is_weekend"] = (tx["dayofweek"] >= 5).astype(int)
    tx["is_cross_border"] = (tx["src_country"] != tx["dst_country"]).astype(int)

    causal = compute_causal_features(tx)
    out = pd.concat([tx, causal], axis=1)

    keep = list(dict.fromkeys(CARRY + ALL_FEATURES))
    keep += [c for c in GROUND_TRUTH if c in out.columns and c not in keep]
    out = out[keep]

    assert_no_leakage(ALL_FEATURES, "variables du modele")
    missing = [c for c in ALL_FEATURES if c not in out.columns]
    if missing:
        raise AssertionError(f"Variables déclarées mais non calculées : {missing}")
    duplicated = out.columns[out.columns.duplicated()].tolist()
    if duplicated:
        raise AssertionError(f"Colonnes dupliquées : {duplicated}")

    return out, maps


def main():
    accounts, banks, persons, transactions = load_raw()
    started = time.perf_counter()
    features, maps = build_features(accounts, banks, persons, transactions)
    elapsed = time.perf_counter() - started

    PROCESSED.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    features.to_parquet(PROCESSED / "features.parquet", index=False)
    (ARTIFACTS / "category_maps.json").write_text(
        json.dumps(maps, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    fraud = int(features["gt_is_fraud"].sum())
    print(f"{len(features)} transactions, {len(ALL_FEATURES)} variables, {elapsed:.1f} s")
    print(f"fraudes : {fraud} ({100 * fraud / len(features):.2f} %)")
    print(f"fenêtre : {features['ts'].min()} -> {features['ts'].max()}")
    print(f"écrit dans {PROCESSED / 'features.parquet'}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
