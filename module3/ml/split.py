import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.config import PROCESSED
from ml.features.blocks import PERIMETER_INSTRUMENT

CALIB_FRACTION = 0.20


def load_features(path=None):
    path = Path(path) if path else PROCESSED / "features.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} introuvable. Lance d'abord ml/features/build.py.")
    return pd.read_parquet(path)


def scorable(df, instrument=PERIMETER_INSTRUMENT):
    """Périmètre scoré : les virements. Les paiements par carte et les prélèvements
    restent dans la matrice de variables comme historique comportemental, mais ne
    sont ni entraînés ni évalués."""
    return df[df["instrument"] == instrument].reset_index(drop=True)


def _group_key(df):
    """Un scénario de fraude ou un leurre forme un bloc indivisible."""
    scenario = df["gt_scenario_id"].where(df["gt_scenario_id"].notna(), None)
    decoy = df["gt_decoy_id"].where(df["gt_decoy_id"].notna(), None)
    return scenario.combine_first(decoy)


def make_splits(df, calib_fraction=CALIB_FRACTION):
    """Reprend `gt_split` de l'équipe et détache une tranche de calibration du train.

    La séparation train/test et l'intégrité des scénarios sont déjà garanties à la
    génération. Il reste à isoler de quoi calibrer les probabilités et choisir un
    seuil sans toucher au test.
    """
    df = df.sort_values(["ts_epoch", "tx_id"], kind="mergesort").reset_index(drop=True)
    df["split"] = df["gt_split"]

    train = df[df["gt_split"] == "train"]
    if train.empty:
        raise ValueError("aucune transaction d'entraînement dans gt_split.")

    boundary = float(np.quantile(train["ts_epoch"].to_numpy(), 1.0 - calib_fraction))
    groups = _group_key(df)

    # Les lignes isolées basculent sur l'horodatage ; un scénario ou un leurre bascule
    # en entier selon sa date de début, pour qu'aucun bloc ne soit coupé en deux.
    to_calib = (df["gt_split"] == "train") & (df["ts_epoch"] >= boundary)
    group_start = df.loc[groups.notna()].groupby(groups[groups.notna()])["ts_epoch"].min()
    if len(group_start):
        starts = groups.map(group_start)
        grouped = groups.notna() & (df["gt_split"] == "train")
        to_calib = np.where(grouped, starts >= boundary, to_calib)

    df.loc[np.asarray(to_calib) & (df["gt_split"] == "train").to_numpy(), "split"] = "calib"

    report = {
        "calib_boundary": str(pd.to_datetime(boundary, unit="s")),
        "counts": {
            name: {
                "rows": int(len(part)),
                "frauds": int(part["gt_is_fraud"].sum()),
                "decoys": int(part["gt_decoy_id"].notna().sum()),
            }
            for name, part in df.groupby("split")
        },
    }

    straddling = []
    for group, part in df[groups.notna()].groupby(groups[groups.notna()]):
        if part["split"].nunique() > 1:
            straddling.append(group)
    report["straddling_groups"] = sorted(straddling)

    return df, report


def describe(report):
    lines = [f"frontière de calibration : {report['calib_boundary']}"]
    for name in ("train", "calib", "test"):
        c = report["counts"].get(name)
        if c:
            rate = 100 * c["frauds"] / max(c["rows"], 1)
            lines.append(
                f"  {name:<6} {c['rows']:>7} lignes, {c['frauds']:>5} fraudes "
                f"({rate:.2f} %), {c['decoys']:>4} leurres"
            )
    if report["straddling_groups"]:
        lines.append(
            f"ATTENTION : {len(report['straddling_groups'])} scénarios ou leurres "
            f"à cheval sur deux tranches : {report['straddling_groups'][:5]}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    df, report = make_splits(scorable(load_features()))
    print(describe(report))
