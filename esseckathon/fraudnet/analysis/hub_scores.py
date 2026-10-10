"""Score heuristique point-in-time des comptes en convergence de flux.

    python -m fraudnet.analysis.hub_scores --data fraudnet/data

AVERTISSEMENT DE PERIMETRE
Ceci n'est PAS le modele du module 3. C'est une heuristique transparente a
cinq composantes, destinee a rendre la demonstration blockchain honnete en
attendant les scores du vrai modele. A presenter comme telle: une regle
experte, pas un apprentissage. Le module 3 doit la remplacer.

LA DIFFICULTE QUE CE FICHIER RESOUD
La regle de graphe du rapport de qualite (fan-in x ratio de redistribution x
anciennete) atteint 93,9 % de precision, mais elle regarde toute la fenetre.
Or au moment ou une banque voudrait bloquer un virement, la redistribution
n'a PAS encore eu lieu: dans une arnaque au faux conseiller, le compte
collecteur ne se vide qu'apres le dernier virement de victime. Utiliser le
ratio de redistribution pour decider au 6e virement serait une fuite de
donnees pure et simple.

Le score ci-dessous n'utilise donc, a l'instant de decision, que ce qu'une
banque sait deja: la convergence observee, l'anciennete du compte
beneficiaire, l'absence d'historique, la dispersion des banques emettrices
et la nouveaute des relations. La redistribution n'entre dans le score que
si elle a effectivement commence avant l'instant de decision.
"""

import argparse
import csv
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta

TRIGGER_SENDERS = 5          # convergence declenchant l'evaluation
TRIGGER_WINDOW = timedelta(hours=24)
PUBLISH_THRESHOLD = 80       # score a partir duquel une banque publierait

PUBLISH_COLUMNS = ["account_id", "score", "pattern", "evidence"]
EVAL_COLUMNS = [
    "account_id", "score", "pattern", "decision_ts",
    "fan_in_24h", "account_age_days", "prior_tx_count", "n_sender_banks",
    "new_sender_ratio", "outflow_ratio_at_decision",
    "gt_role", "gt_scenario_id", "gt_scenario_type", "gt_decoy_type",
]


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def find_trigger(events):
    """Premier instant ou 5 emetteurs distincts apparaissent en 24 h."""
    window = []
    for ts, src in events:
        window.append((ts, src))
        while window and ts - window[0][0] > TRIGGER_WINDOW:
            window.pop(0)
        if len({s for _, s in window}) >= TRIGGER_SENDERS:
            return ts
    return None


def score_hub(feat):
    """Score 0-100. Chaque composante est explicable a un analyste."""
    parts = []
    s = 0.0

    # L'echelle est calibree pour qu'un compte collecteur recemment ouvert et
    # sans historique atteigne environ 90 au moment du declenchement. La
    # convergence pese peu ici: le score est evalue des le 5e emetteur, donc
    # fan_in_24h vaut presque toujours 5. Ce qui porte le signal a cet
    # instant, c'est la nouveaute du compte et l'absence d'historique.
    conv = min(22.0, 4.5 * (feat["fan_in_24h"] - (TRIGGER_SENDERS - 1)))
    s += conv
    parts.append(("convergence",
                  f"{feat['fan_in_24h']} emetteurs distincts en 24 h", conv))

    age = feat["account_age_days"]
    nov = 36.0 if age <= 90 else (20.0 if age <= 180 else 0.0)
    s += nov
    if nov:
        parts.append(("anciennete",
                      f"compte beneficiaire ouvert depuis {age} jours", nov))

    prior = feat["prior_tx_count"]
    hist = 24.0 if prior == 0 else (12.0 if prior < 10 else 0.0)
    s += hist
    if hist:
        parts.append(("historique",
                      f"{prior} operation(s) sur ce compte avant la rafale",
                      hist))

    disp = min(12.0, 3.0 * (feat["n_sender_banks"] - 1))
    s += disp
    parts.append(("dispersion",
                  f"emetteurs repartis sur {feat['n_sender_banks']} banques",
                  disp))

    newr = 12.0 * feat["new_sender_ratio"]
    s += newr
    parts.append(("nouveaute",
                  f"{feat['new_sender_ratio'] * 100:.0f} % d'emetteurs jamais "
                  f"vus avec ce compte", newr))

    # La redistribution ne compte que si elle a deja commence.
    redis = min(25.0, 25.0 * feat["outflow_ratio_at_decision"])
    s += redis
    if redis > 1:
        parts.append(("redistribution",
                      f"{feat['outflow_ratio_at_decision'] * 100:.0f} % des "
                      f"fonds deja ressortis", redis))

    score = int(round(min(100.0, s)))
    parts.sort(key=lambda p: -p[2])
    evidence = " ; ".join(f"{p[1]}" for p in parts[:3] if p[2] > 0)
    return score, evidence


def analyse(data_dir):
    accounts = {a["account_id"]: a for a in load(os.path.join(data_dir, "accounts.csv"))}
    txs = load(os.path.join(data_dir, "transactions.csv"))
    for t in txs:
        t["_ts"] = datetime.fromisoformat(t["ts"])
        t["amount"] = float(t["amount"])
    txs.sort(key=lambda t: t["_ts"])

    incoming = defaultdict(list)
    partners = defaultdict(set)
    touching = defaultdict(list)
    for t in txs:
        incoming[t["dst_account"]].append((t["_ts"], t["src_account"]))
        touching[t["dst_account"]].append(t)
        touching[t["src_account"]].append(t)

    decoy_hub_type = {}
    for d in load(os.path.join(data_dir, "decoys.csv")):
        decoy_hub_type[d["hub_account"]] = d["decoy_type"]

    rows = []
    for acct, events in incoming.items():
        trigger = find_trigger(events)
        if trigger is None:
            continue
        a = accounts[acct]
        lo = trigger - TRIGGER_WINDOW

        burst = [(ts, src) for ts, src in events if lo <= ts <= trigger]
        burst_senders = {src for _, src in burst}

        before = [t for t in touching[acct] if t["_ts"] < lo]
        prior_partners = set()
        for t in before:
            prior_partners.add(t["src_account"] if t["dst_account"] == acct
                               else t["dst_account"])

        inflow = sum(t["amount"] for t in touching[acct]
                     if t["dst_account"] == acct and lo <= t["_ts"] <= trigger
                     and t["status"] == "completed")
        outflow = sum(t["amount"] for t in touching[acct]
                      if t["src_account"] == acct and lo <= t["_ts"] <= trigger
                      and t["status"] == "completed")

        opened = datetime.fromisoformat(a["opened_at"])
        feat = {
            "fan_in_24h": len(burst_senders),
            "account_age_days": max(0, (trigger - opened).days),
            "prior_tx_count": len(before),
            "n_sender_banks": len({accounts[s]["bank_id"] for s in burst_senders}),
            "new_sender_ratio": (
                len(burst_senders - prior_partners) / len(burst_senders)
                if burst_senders else 0.0
            ),
            "outflow_ratio_at_decision": (outflow / inflow) if inflow else 0.0,
        }
        score, evidence = score_hub(feat)

        rows.append({
            "account_id": acct,
            "score": score,
            "pattern": ("fan_in_redistribution"
                        if feat["outflow_ratio_at_decision"] >= 0.5
                        else "fan_in_only"),
            "evidence": evidence,
            "decision_ts": trigger.isoformat(),
            "gt_role": a["gt_role"],
            "gt_scenario_id": a["gt_scenario_id"],
            "gt_scenario_type": "",
            "gt_decoy_type": decoy_hub_type.get(acct, ""),
            **feat,
        })

    scen_type = {s["scenario_id"]: s["scenario_type"]
                 for s in load(os.path.join(data_dir, "scenarios.csv"))}
    for r in rows:
        r["gt_scenario_type"] = scen_type.get(r["gt_scenario_id"], "")
    rows.sort(key=lambda r: -r["score"])
    return rows


def report(rows, data_dir):
    bar = "=" * 78
    print(f"\n{bar}\nSCORE HEURISTIQUE POINT-IN-TIME DES COMPTES EN CONVERGENCE"
          f"\n{bar}")
    print(f"{len(rows)} comptes ont atteint {TRIGGER_SENDERS} emetteurs "
          f"distincts en 24 h sur la periode.\n")

    mules = [r for r in rows if r["gt_role"] in ("mule", "fraudster")]
    decoys = [r for r in rows if r["gt_decoy_type"]]
    ordinary = [r for r in rows if r["gt_role"] == "normal"
                and not r["gt_decoy_type"]]

    print(f"  {'population':34s} {'n':>5s} {'score median':>13s} {'max':>5s} "
          f"{'>= 80':>7s}")
    for label, group in (("comptes mules / fraudeurs", mules),
                         ("hubs de faux amis legitimes", decoys),
                         ("comptes ordinaires", ordinary)):
        if not group:
            continue
        sc = sorted(r["score"] for r in group)
        above = sum(1 for r in group if r["score"] >= PUBLISH_THRESHOLD)
        print(f"  {label:34s} {len(group):5d} {sc[len(sc) // 2]:13d} "
              f"{sc[-1]:5d} {above:7d}")

    flagged = [r for r in rows if r["score"] >= PUBLISH_THRESHOLD]
    tp = sum(1 for r in flagged if r["gt_role"] in ("mule", "fraudster"))
    fp = len(flagged) - tp
    print(f"\n  Au seuil de publication {PUBLISH_THRESHOLD} :")
    print(f"    comptes signales        : {len(flagged)}")
    print(f"    dont mules / fraudeurs  : {tp}")
    print(f"    dont faux positifs      : {fp}")
    print(f"    precision               : {pct(tp, len(flagged)):.1f} %")
    print(f"    rappel sur les {len(mules)} mules : {pct(tp, len(mules)):.1f} %")
    fp_decoys = [r for r in flagged if r["gt_decoy_type"]]
    print(f"    faux amis signales      : {len(fp_decoys)}/{len(decoys)}")
    if fp_decoys:
        for r in fp_decoys[:5]:
            print(f"      {r['account_id']} {r['gt_decoy_type']} "
                  f"score {r['score']}")

    print(f"\n  Compromis selon le seuil de publication :")
    print(f"    {'seuil':>6s} {'signales':>9s} {'mules':>6s} {'faux pos.':>10s} "
          f"{'precision':>10s} {'rappel':>8s} {'faux amis':>10s}")
    for thr in (50, 60, 70, 75, 80, 85, 90):
        fl = [r for r in rows if r["score"] >= thr]
        t = sum(1 for r in fl if r["gt_role"] in ("mule", "fraudster"))
        d = sum(1 for r in fl if r["gt_decoy_type"])
        print(f"    {thr:6d} {len(fl):9d} {t:6d} {len(fl) - t:10d} "
              f"{pct(t, len(fl)):9.1f} % {pct(t, len(mules)):7.1f} % {d:10d}")

    missed = [r for r in mules if r["score"] < PUBLISH_THRESHOLD]
    if missed:
        old = sum(1 for r in missed if r["account_age_days"] > 180)
        print(f"\n  Mules manquees : {len(missed)}, dont {old} sur des comptes "
              f"anciens")
        print(f"  (mules recrutees parmi des clients existants: l'anciennete et")
        print(f"   l'historique ne les trahissent pas. Limite connue, a traiter")
        print(f"   par un indicateur de rupture comportementale au module 2.)")

    print(f"\n  Scores des hubs de faux amis, par type :")
    by_type = defaultdict(list)
    for r in decoys:
        by_type[r["gt_decoy_type"]].append(r["score"])
    for dtype, scores in sorted(by_type.items(), key=lambda x: -max(x[1])):
        scores.sort()
        print(f"    {dtype:26s} n={len(scores):3d}  median {scores[len(scores) // 2]:3d}"
              f"  max {scores[-1]:3d}")

    pub = os.path.join(data_dir, "hub_scores.csv")
    with open(pub, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PUBLISH_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    ev = os.path.join(data_dir, "hub_scores_eval.csv")
    with open(ev, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EVAL_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\n  {pub}       publiable, aucune colonne gt_")
    print(f"  {ev}  evaluation, avec verite terrain")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fraudnet/data")
    args = ap.parse_args()
    report(analyse(args.data), args.data)


if __name__ == "__main__":
    main()
