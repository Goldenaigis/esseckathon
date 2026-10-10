"""Rapport de qualite du jeu de donnees.

    python -m fraudnet.generator.validate --data fraudnet/data

Verifie l'integrite, puis mesure les proprietes qui rendent le jeu
non trivial: recouvrement des montants, recouvrement du degre entrant entre
mules et faux amis, part des fraudes indetectables transaction par transaction.
"""

import argparse
import csv
import json
import os
import statistics as st
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from ..shared.schema import (
    ACCOUNTS_COLUMNS, TRANSACTIONS_COLUMNS, assert_no_leakage,
    feature_safe_columns,
)

OK = "  ok   "
WARN = " ALERTE"
FAIL = " ECHEC "


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def quantile(values, q):
    if not values:
        return 0.0
    s = sorted(values)
    i = min(len(s) - 1, max(0, int(q * (len(s) - 1))))
    return s[i]


def _rule_metrics(items, predicate):
    tp = fp = fn = 0
    for t in items:
        hit, fraud = predicate(t), t["gt_is_fraud"] == 1
        if hit and fraud:
            tp += 1
        elif hit:
            fp += 1
        elif fraud:
            fn += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1, tp, fp


def section(title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


_FAILED = []


def check(cond, label, detail=""):
    """Enregistre le resultat. Tout controle en echec est bloquant."""
    print(f"[{OK if cond else FAIL}] {label}" + (f"  -> {detail}" if detail else ""))
    if not cond:
        _FAILED.append(label)
    return cond


def run(data_dir):
    accounts = load(os.path.join(data_dir, "accounts.csv"))
    txs = load(os.path.join(data_dir, "transactions.csv"))
    persons = load(os.path.join(data_dir, "persons.csv"))
    companies = load(os.path.join(data_dir, "companies.csv"))
    assocs = load(os.path.join(data_dir, "associations.csv"))
    scenarios = load(os.path.join(data_dir, "scenarios.csv"))
    decoys = load(os.path.join(data_dir, "decoys.csv"))
    with open(os.path.join(data_dir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)

    for t in txs:
        t["amount"] = float(t["amount"])
        t["gt_is_fraud"] = int(t["gt_is_fraud"])
        t["_ts"] = datetime.fromisoformat(t["ts"])

    acct_ids = {a["account_id"] for a in accounts}
    role = {a["account_id"]: a["gt_role"] for a in accounts}
    _FAILED.clear()

    # ------------------------------------------------------------ integrite
    section("1. INTEGRITE REFERENTIELLE ET STRUCTURE")

    missing = {t["src_account"] for t in txs if t["src_account"] not in acct_ids}
    missing |= {t["dst_account"] for t in txs if t["dst_account"] not in acct_ids}
    check(not missing, "Tous les comptes des transactions existent",
                          f"{len(missing)} manquants" if missing else "")

    owners = ({p["person_id"] for p in persons}
              | {c["company_id"] for c in companies}
              | {a["association_id"] for a in assocs})
    orphan = [a["account_id"] for a in accounts if a["owner_id"] not in owners]
    check(not orphan, "Tous les comptes ont un titulaire declare",
                          f"{len(orphan)} orphelins" if orphan else "")

    self_loops = [t for t in txs if t["src_account"] == t["dst_account"]]
    check(not self_loops, "Aucune transaction d'un compte vers lui-meme",
                          f"{len(self_loops)} trouvees" if self_loops else "")

    w_start = datetime.fromisoformat(manifest["window"]["start"])
    w_end = datetime.fromisoformat(manifest["window"]["end"])
    boundary = datetime.fromisoformat(manifest["window"]["split_boundary"])
    out_of_range = [t for t in txs if not (w_start <= t["_ts"] < w_end)]
    check(not out_of_range, "Toutes les transactions sont dans la fenetre",
                          f"{len(out_of_range)} hors bornes" if out_of_range else "")

    ids = [t["tx_id"] for t in txs]
    check(len(set(ids)) == len(ids), "Identifiants de transaction uniques")
    check(
        all(txs[i]["_ts"] <= txs[i + 1]["_ts"] for i in range(len(txs) - 1)),
        "Transactions triees chronologiquement",
    )

    # ------------------------------------------------------- anti-fuite
    section("2. PROTECTION ANTI-FUITE")

    safe_tx = feature_safe_columns(TRANSACTIONS_COLUMNS)
    safe_acct = feature_safe_columns(ACCOUNTS_COLUMNS)
    try:
        assert_no_leakage(safe_tx, "transactions")
        assert_no_leakage(safe_acct, "accounts")
        check(True, "Les colonnes jugees exploitables ne contiennent aucun gt_/sim_")
    except ValueError as e:
        check(False, "Colonnes exploitables", str(e))
    print(f"         transactions exploitables ({len(safe_tx)}): {', '.join(safe_tx)}")
    print(f"         comptes exploitables ({len(safe_acct)}): {', '.join(safe_acct)}")

    for group_key, label in (("gt_scenario_id", "scenario"), ("gt_decoy_id", "faux ami")):
        by_group = defaultdict(set)
        for t in txs:
            if t[group_key]:
                by_group[t[group_key]].add(t["gt_split"])
        bad = [g for g, s in by_group.items() if len(s) > 1]
        check(
            not bad, f"Aucun {label} a cheval sur train/test",
            f"{len(bad)} concernes: {bad[:5]}" if bad else "",
        )

    train = [t for t in txs if t["gt_split"] == "train"]
    test = [t for t in txs if t["gt_split"] == "test"]
    bad_split = [t for t in txs
                 if not t["gt_scenario_id"] and not t["gt_decoy_id"]
                 and t["gt_split"] != ("train" if t["_ts"] < boundary else "test")]
    check(not bad_split,
                          "Partition temporelle coherente pour les flux ordinaires")

    # ------------------------------------------------------- distributions
    section("3. VOLUMETRIE ET EQUILIBRE DES CLASSES")

    fraud = [t for t in txs if t["gt_is_fraud"] == 1]
    legit = [t for t in txs if t["gt_is_fraud"] == 0]
    decoy_tx = [t for t in txs if t["gt_decoy_id"]]

    print(f"         transactions           : {len(txs)}")
    print(f"         comptes                : {len(accounts)}")
    print(f"         fraude                 : {len(fraud)} ({pct(len(fraud), len(txs)):.2f} %)")
    print(f"         faux amis legitimes    : {len(decoy_tx)} ({pct(len(decoy_tx), len(txs)):.2f} %)")
    print(f"         train / test           : {len(train)} / {len(test)}")
    print(f"         fraude train           : {sum(t['gt_is_fraud'] for t in train)} "
          f"({pct(sum(t['gt_is_fraud'] for t in train), len(train)):.2f} %)")
    print(f"         fraude test            : {sum(t['gt_is_fraud'] for t in test)} "
          f"({pct(sum(t['gt_is_fraud'] for t in test), len(test)):.2f} %)")

    # Un jeu de developpement reduit garde un minimum d'instances par type
    # pour rester evaluable, ce qui gonfle mecaniquement le taux de fraude.
    dev_sample = len(txs) < 50_000
    hi = 0.05 if dev_sample else 0.03
    check(0.005 <= len(fraud) / len(txs) <= hi,
          f"Taux de fraude dans la plage visee (0,5 - {hi * 100:.0f} %)"
          + (" [jeu de developpement reduit]" if dev_sample else ""))
    check(sum(t["gt_is_fraud"] for t in test) >= 150,
          "Assez de fraudes en test pour une evaluation stable",
          f"{sum(t['gt_is_fraud'] for t in test)} transactions")

    print("\n         Repartition par type de scenario:")
    by_type = Counter(t["gt_scenario_type"] for t in fraud)
    inst = Counter(s["scenario_type"] for s in scenarios)
    for stype, n in by_type.most_common():
        n_train = sum(1 for s in scenarios
                      if s["scenario_type"] == stype and s["gt_split"] == "train")
        n_test = inst[stype] - n_train
        print(f"           {stype:22s} {n:5d} tx  |  {inst[stype]:3d} instances "
              f"(train {n_train}, test {n_test})")
    missing_test = [s for s, c in inst.items()
                    if not any(x["scenario_type"] == s and x["gt_split"] == "test"
                               for x in scenarios)]
    check(not missing_test, "Chaque type de scenario est present en test",
          f"absents: {missing_test}" if missing_test else "")

    print("\n         Repartition des faux amis:")
    for dtype, n in Counter(d["decoy_type"] for d in decoys).most_common():
        ntx = sum(1 for t in decoy_tx if t["gt_decoy_type"] == dtype)
        print(f"           {dtype:26s} {n:3d} instances  |  {ntx:5d} tx")

    # ------------------------------------------------ non-trivialite
    section("4. NON-TRIVIALITE (le jeu n'est pas separable naivement)")

    # Une banque ne score pas les paiements par carte avec le meme modele que
    # les virements. La comparaison pertinente se fait au sein du perimetre
    # reellement scorable.
    scorable = {"transfer", "p2p", "remittance", "savings_transfer"}
    legit_s = [t for t in legit if t["tx_type"] in scorable]

    fa = [t["amount"] for t in fraud]
    la = [t["amount"] for t in legit]
    ls = [t["amount"] for t in legit_s]
    print(f"         montant fraude            median {st.median(fa):9.2f}   "
          f"p10 {quantile(fa, 0.10):8.2f}   p90 {quantile(fa, 0.90):10.2f}")
    print(f"         montant legitime (tous)   median {st.median(la):9.2f}   "
          f"p10 {quantile(la, 0.10):8.2f}   p90 {quantile(la, 0.90):10.2f}")
    print(f"         montant legitime (virem.) median {st.median(ls):9.2f}   "
          f"p10 {quantile(ls, 0.10):8.2f}   p90 {quantile(ls, 0.90):10.2f}")
    print(f"         perimetre scorable: {len(legit_s)} virements legitimes "
          f"contre {len(fraud)} frauduleux "
          f"(1 fraude pour {len(legit_s) / max(1, len(fraud)):.0f})")

    lo, hi = quantile(fa, 0.10), quantile(fa, 0.90)
    overlap = pct(sum(1 for a in ls if lo <= a <= hi), len(ls))
    check(
        overlap > 35,
        "Les virements legitimes recouvrent la plage des fraudes",
        f"{overlap:.1f} % des virements legitimes dans [p10, p90] de la fraude",
    )
    # Benchmark des regles naives. C'est le vrai critere de non-trivialite:
    # si une regle a une variable atteint un bon F1, le modele et le graphe
    # n'ont rien a demontrer. Ces chiffres servent aussi de ligne de base
    # dans la page Performances et dans le pitch.
    bench = [t for t in txs
             if t["gt_split"] == "test" and t["tx_type"] in scorable]
    emi = {"LT", "MT", "CY", "LV", "BG", "EE", "AE"}
    rules = [
        ("montant >= 500 EUR", lambda t: t["amount"] >= 500),
        ("montant >= 1 000 EUR", lambda t: t["amount"] >= 1000),
        ("montant >= 3 000 EUR", lambda t: t["amount"] >= 3000),
        ("destination hors de France", lambda t: t["dst_country"] != "FR"),
        ("destination en etabl. de paiement", lambda t: t["dst_country"] in emi),
        ("montant >= 1 000 ET etranger",
         lambda t: t["amount"] >= 1000 and t["dst_country"] != "FR"),
        ("canal mobile ET montant >= 800",
         lambda t: t["channel"] == "mobile" and t["amount"] >= 800),
    ]
    print(f"\n         Regles naives sur le jeu de test ({len(bench)} virements, "
          f"{sum(t['gt_is_fraud'] for t in bench)} fraudes):")
    print(f"           {'regle':36s} {'prec.':>7s} {'rappel':>7s} {'F1':>7s} "
          f"{'alertes':>8s}")
    best_f1, best_name = 0.0, ""
    for name, pred in rules:
        prec, rec, f1, tp, fp = _rule_metrics(bench, pred)
        print(f"           {name:36s} {prec:6.1%} {rec:6.1%} {f1:6.3f} "
              f"{tp + fp:8d}")
        if f1 > best_f1:
            best_f1, best_name = f1, name
    # Meilleur seuil de montant possible, choisi avec la verite terrain
    # (donc optimiste): plafond de ce qu'une regle de montant peut faire.
    oracle_f1 = 0.0
    for q in range(50, 100):
        thr = quantile([t["amount"] for t in bench], q / 100)
        _, _, f1, _, _ = _rule_metrics(bench, lambda t, s=thr: t["amount"] >= s)
        oracle_f1 = max(oracle_f1, f1)
    print(f"\n         Meilleure regle de montant possible (seuil choisi avec")
    print(f"         la verite terrain, donc optimiste) : F1 = {oracle_f1:.3f}")
    print(f"         Meilleure regle naive              : {best_name} "
          f"(F1 = {best_f1:.3f})")
    check(oracle_f1 < 0.55,
          "Aucune regle a une seule variable ne resout le probleme",
          f"plafond des regles de montant: F1 {oracle_f1:.3f}. Le modele et "
          f"le graphe doivent faire nettement mieux.")
    print(f"\n         -> objectif pour le module 3: depasser nettement "
          f"F1 = {max(oracle_f1, best_f1):.3f}")

    f_foreign = pct(sum(1 for t in fraud if t["dst_country"] != "FR"), len(fraud))
    l_foreign = pct(sum(1 for t in legit if t["dst_country"] != "FR"), len(legit))
    ls_foreign = pct(sum(1 for t in legit_s if t["dst_country"] != "FR"),
                     len(legit_s))
    print(f"\n         destination etrangere: fraude {f_foreign:.1f} %  |  "
          f"legitime tous {l_foreign:.1f} %  |  legitime virements {ls_foreign:.1f} %")
    check(ls_foreign > 8.0 and f_foreign < 95.0,
          "'Etranger' n'est pas un predicteur exploitable seul",
          f"rapport des taux = {f_foreign / max(0.01, ls_foreign):.1f}x")

    emi = {"LT", "MT", "CY", "LV", "BG", "EE", "AE"}
    f_emi = pct(sum(1 for t in fraud if t["dst_country"] in emi), len(fraud))
    l_emi = pct(sum(1 for t in legit_s if t["dst_country"] in emi), len(legit_s))
    print(f"         destination en etablissement de paiement: fraude "
          f"{f_emi:.1f} %  |  legitime virements {l_emi:.1f} %")
    check(l_emi > 3.0, "Les pays d'etablissements de paiement sont aussi "
                       "utilises legitimement")

    fr_countries = Counter(t["dst_country"] for t in fraud if t["dst_country"] != "FR")
    lg_countries = Counter(t["dst_country"] for t in legit if t["dst_country"] != "FR")
    shared = set(fr_countries) & set(lg_countries)
    check(len(shared) >= 4, "Les pays de destination se recoupent",
          f"{len(shared)} pays communs: {sorted(shared)}")

    chans_f = Counter(t["channel"] for t in fraud)
    chans_l = Counter(t["channel"] for t in legit)
    print(f"         canal fraude   : "
          + "  ".join(f"{k} {pct(v, len(fraud)):.0f} %" for k, v in chans_f.most_common()))
    print(f"         canal legitime : "
          + "  ".join(f"{k} {pct(v, len(legit)):.0f} %" for k, v in chans_l.most_common()))

    # ------------------------------------ degre entrant: mules vs faux amis
    section("5. RECOUVREMENT DU DEGRE ENTRANT (mules contre faux amis)")

    incoming = defaultdict(list)
    for t in txs:
        incoming[t["dst_account"]].append((t["_ts"], t["src_account"]))

    fan_in_24h = {}
    for acct, evts in incoming.items():
        evts.sort()
        best, left = 0, 0
        window = []
        for ts, src in evts:
            window.append((ts, src))
            while window and ts - window[0][0] > timedelta(hours=24):
                window.pop(0)
            best = max(best, len({s for _, s in window}))
        fan_in_24h[acct] = best

    decoy_hub = {d["hub_account"]: d["decoy_type"] for d in decoys}
    mule_accts = [a for a, r in role.items() if r in ("mule", "fraudster")]
    mule_fan = sorted((fan_in_24h.get(a, 0) for a in mule_accts), reverse=True)
    decoy_fan = sorted((fan_in_24h.get(a, 0) for a in decoy_hub), reverse=True)
    normal_fan = sorted(
        (fan_in_24h.get(a, 0) for a, r in role.items()
         if r == "normal" and a not in decoy_hub), reverse=True
    )

    print(f"         fan-in 24 h des comptes mules/fraudeurs : "
          f"median {st.median(mule_fan) if mule_fan else 0:.0f}  max {mule_fan[0] if mule_fan else 0}")
    print(f"         fan-in 24 h des hubs de faux amis       : "
          f"median {st.median(decoy_fan) if decoy_fan else 0:.0f}  max {decoy_fan[0] if decoy_fan else 0}")
    print(f"         fan-in 24 h des comptes ordinaires      : "
          f"median {st.median(normal_fan) if normal_fan else 0:.0f}  max {normal_fan[0] if normal_fan else 0}")

    check(decoy_fan and mule_fan and decoy_fan[0] >= st.median(mule_fan),
          "Au moins un faux ami depasse le fan-in median des mules")

    print("\n         Top 15 des comptes par fan-in 24 h (la colonne verite doit")
    print("         melanger fraude et legitime, sinon le probleme est trivial):")
    top = sorted(fan_in_24h.items(), key=lambda kv: -kv[1])[:15]
    print(f"           {'compte':12s} {'fan-in':>7s}  {'role':10s} verite")
    for acct, v in top:
        if acct in decoy_hub:
            truth = f"LEGITIME ({decoy_hub[acct]})"
        elif role.get(acct) in ("mule", "fraudster"):
            truth = "FRAUDE (mule)"
        else:
            truth = "legitime (flux ordinaire)"
        print(f"           {acct:12s} {v:7d}  {role.get(acct, '?'):10s} {truth}")
    n_legit_top = sum(1 for a, _ in top
                      if a in decoy_hub or role.get(a) == "normal")
    check(n_legit_top >= 4,
          "Le classement par fan-in seul ne suffit pas a trouver les mules",
          f"{n_legit_top}/15 des plus forts fan-in sont legitimes")

    # Le signal de graphe existe, mais il est combinatoire. Cette regle a trois
    # variables prefigure le jeu de variables du module 2.
    inflow, outflow = defaultdict(float), defaultdict(float)
    for t in txs:
        if t["status"] != "completed":
            continue
        inflow[t["dst_account"]] += t["amount"]
        outflow[t["src_account"]] += t["amount"]
    age_at_start = {}
    for a in accounts:
        opened = datetime.fromisoformat(a["opened_at"])
        age_at_start[a["account_id"]] = (w_start - opened).days

    receivers = [a["account_id"] for a in accounts if inflow.get(a["account_id"], 0) > 0]

    def passthrough(acct):
        return outflow.get(acct, 0) / inflow[acct] if inflow.get(acct) else 0.0

    # La cible pertinente au niveau compte est le compte collecteur, pas
    # chaque compte de sortie: une jambe de sortie ne recoit que 2 a 4
    # virements et n'est pas detectable par un critere de convergence.
    collectors = {a for a in receivers
                  if role.get(a) in ("mule", "fraudster")
                  and fan_in_24h.get(a, 0) >= 5}
    items = [{"gt_is_fraud": int(a in collectors), "_a": a} for a in receivers]

    nested = [
        ("fan-in 24 h >= 5",
         lambda a: fan_in_24h.get(a, 0) >= 5),
        ("  + ratio sortant/entrant >= 0,60",
         lambda a: fan_in_24h.get(a, 0) >= 5 and passthrough(a) >= 0.60),
        ("  + compte ouvert depuis <= 120 j",
         lambda a: fan_in_24h.get(a, 0) >= 5 and passthrough(a) >= 0.60
         and age_at_start.get(a, 9999) <= 120),
    ]
    print(f"\n         Regles de graphe emboitees, cible = les "
          f"{len(collectors)} comptes collecteurs frauduleux:")
    print(f"           {'regle':36s} {'prec.':>7s} {'rappel':>7s} {'F1':>7s} "
          f"{'signales':>9s}")
    scores = []
    for name, pred in nested:
        prec, rec, f1, tp, fp = _rule_metrics(items, lambda it, p=pred: p(it["_a"]))
        scores.append((prec, rec, f1))
        print(f"           {name:36s} {prec:6.1%} {rec:6.1%} {f1:6.3f} "
              f"{tp + fp:9d}")
    check(scores[0][0] < 0.30 and scores[2][0] > 2.5 * max(0.01, scores[0][0]),
          "Le signal de graphe est combinatoire, pas unidimensionnel",
          f"la precision passe de {scores[0][0]:.1%} a {scores[2][0]:.1%} en "
          f"ajoutant deux variables de reseau")

    flagged = [d for d in decoy_hub if nested[2][1](d)]
    print(f"           faux amis encore signales a tort par la regle "
          f"complete: {len(flagged)}/{len(decoy_hub)}")
    recruited = [a for a in collectors if age_at_start.get(a, 0) > 120]
    print(f"           collecteurs manques par le critere d'anciennete "
          f"(mules recrutees parmi des clients existants): "
          f"{len(recruited)}/{len(collectors)}")
    print(f"           -> le module 2 devra ajouter un indicateur de rupture")
    print(f"              comportementale pour recuperer ces cas")

    # ---------------------------------------- these du projet
    section("6. THESE DU PROJET: la transaction isolee ne suffit pas")

    legit_by_src = defaultdict(list)
    for t in legit:
        legit_by_src[t["src_account"]].append(t["amount"])

    unremarkable = 0
    considered = 0
    for t in fraud:
        hist = legit_by_src.get(t["src_account"])
        if not hist or len(hist) < 5:
            continue
        considered += 1
        p95 = quantile(hist, 0.95)
        if t["amount"] <= p95 and t["dst_country"] == "FR":
            unremarkable += 1
    print(f"         Transactions frauduleuses dont l'emetteur a un historique : {considered}")
    print(f"         ... dont le montant reste sous son p95 habituel et la")
    print(f"         destination est domestique : {unremarkable} "
          f"({pct(unremarkable, considered):.1f} %)")
    check(pct(unremarkable, considered) > 15,
          "Une part notable des fraudes est anodine vue isolement",
          "c'est precisement ce que l'analyse de graphe doit rattraper")

    regime_of = {}
    for s in scenarios:
        try:
            regime_of[s["scenario_id"]] = json.loads(
                s["params_json"]).get("amount_regime", "n/a")
        except (ValueError, KeyError):
            regime_of[s["scenario_id"]] = "n/a"
    by_regime = defaultdict(lambda: [0, 0])
    for t in fraud:
        hist = legit_by_src.get(t["src_account"])
        if not hist or len(hist) < 5:
            continue
        r = regime_of.get(t["gt_scenario_id"], "n/a")
        by_regime[r][1] += 1
        if t["amount"] <= quantile(hist, 0.95) and t["dst_country"] == "FR":
            by_regime[r][0] += 1
    print("\n         Detail par regime de montant du scenario:")
    for r in ("discret", "standard", "eleve", "n/a"):
        if r not in by_regime:
            continue
        anodines, tot = by_regime[r]
        print(f"           regime {r:9s} {anodines:4d}/{tot:4d} anodines "
              f"({pct(anodines, tot):5.1f} %)")
    disc = by_regime.get("discret", [0, 1])
    check(pct(disc[0], disc[1]) > 40,
          "Le regime 'discret' produit bien des fraudes invisibles isolement",
          f"{pct(disc[0], disc[1]):.1f} % des fraudes en regime discret sont "
          f"indiscernables au niveau transaction")

    victim_first = []
    for s in scenarios:
        if s["scenario_type"] not in ("faux_conseiller", "compte_collecteur",
                                      "dormant_reactive"):
            continue
        n = int(s["n_victim_accounts"])
        if n:
            victim_first.append(n)
    if victim_first:
        print(f"\n         Nombre de victimes par scenario de convergence: "
              f"median {st.median(victim_first):.0f}, min {min(victim_first)}, "
              f"max {max(victim_first)}")
        print(f"         -> metrique a produire par le module 3: 'alerte levee")
        print(f"            apres combien de victimes'")

    # ---------------------------------------- temporalite
    section("7. REALISME TEMPOREL")

    hours = Counter(t["_ts"].hour for t in txs)
    peak = max(hours, key=hours.get)
    trough = min(hours, key=hours.get)
    print(f"         heure de pointe {peak} h ({hours[peak]} tx), "
          f"heure creuse {trough} h ({hours[trough]} tx)")
    check(hours[peak] > 3 * hours[trough], "Cycle jour/nuit present")

    wk = sum(1 for t in txs if t["_ts"].weekday() >= 5)
    virements = [t for t in txs
                 if t["tx_type"] not in ("retail", "large_purchase")]
    wk_vir = sum(1 for t in virements if t["_ts"].weekday() >= 5)
    print(f"         part du week-end, toutes operations : {pct(wk, len(txs)):.1f} % "
          f"(les paiements par carte sont plus nombreux le week-end)")
    print(f"         part du week-end, virements seuls  : "
          f"{pct(wk_vir, len(virements)):.1f} % (attendu nettement < 28,6 %)")
    check(pct(wk_vir, len(virements)) < 22.0,
          "Les virements sont concentres sur les jours ouvres")

    dom = Counter(t["_ts"].day for t in txs if t["tx_type"] == "salary")
    if dom:
        print(f"         jours de versement des salaires: "
              f"{sorted(d for d, c in dom.items() if c > 50)}")

    types = Counter(t["tx_type"] for t in txs)
    print("\n         Repartition par type d'operation:")
    for k, v in types.most_common():
        print(f"           {k:20s} {v:7d}  ({pct(v, len(txs)):5.2f} %)")

    # ---------------------------------------- conclusion
    section("CONCLUSION")
    if not _FAILED:
        print("  Les 25 controles passent. Le jeu de donnees est exploitable")
        print("  par les modules 2, 3 et 4.")
    else:
        print(f"  {len(_FAILED)} controle(s) en echec, a corriger avant de")
        print("  livrer aux autres equipes:")
        for label in _FAILED:
            print(f"    - {label}")
        print("\n  Si le volume a ete reduit en ligne de commande, verifier que")
        print("  --scenarios et --decoys ont ete mis a l'echelle: trop de")
        print("  scenarios pour peu de transactions gonfle le taux de fraude et")
        print("  rend le probleme artificiellement facile.")
    return len(_FAILED)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fraudnet/data")
    args = ap.parse_args()
    raise SystemExit(1 if run(args.data) else 0)


if __name__ == "__main__":
    main()
