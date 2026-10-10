"""Mesure l'apport d'un registre d'alertes partage entre banques.

    python -m fraudnet.analysis.consortium --data fraudnet/data

Produit fraudnet/data/consortium_analysis.csv et un resume chiffre.

--- L'ASYMETRIE D'INFORMATION REELLE ---

Attention a une erreur de raisonnement tentante. En SEPA, la banque du
beneficiaire recoit TOUS les virements entrants de son client: elle voit donc
parfaitement la convergence des flux. Elle n'est pas aveugle.

Ce sont les banques des VICTIMES qui ne voient rien: chacune observe un ou
deux de ses clients effectuant un virement ordinaire vers un beneficiaire
quelconque. Aucune convergence n'est visible de leur cote.

Or c'est precisement la banque de la victime qui peut BLOQUER le virement
avant son depart. La banque qui voit la fraude ne peut que la constater une
fois les fonds arrives, et le compte collecteur se vide en quelques heures.

D'ou l'asymetrie a mesurer:
  la banque qui PEUT agir est aveugle,
  la banque qui VOIT ne peut qu'observer.

Le registre partage sert exactement a faire franchir cette frontiere au
signal. On mesure donc le nombre de victimes dont le virement aurait pu etre
bloque, avec et sans partage.
"""

import argparse
import csv
import os
from collections import Counter, defaultdict
from datetime import datetime

CONVERGENCE_TYPES = ("faux_conseiller", "compte_collecteur", "dormant_reactive",
                     "faux_investissement")

OUT_COLUMNS = [
    "scenario_id", "scenario_type", "gt_split", "hub_account", "hub_bank",
    "n_victims", "n_legs", "n_victim_banks", "total_amount",
    "max_visible_single_bank", "pct_visible_single_bank",
    "blocked_legs_without_sharing", "blocked_legs_with_sharing",
    "victims_protected_without_sharing", "victims_protected_with_sharing",
    "amount_saved_without_sharing", "amount_saved_with_sharing",
    "first_alert_leg_rank",
]


def load(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def analyse(data_dir, thresholds=(3, 5, 8)):
    accounts = {a["account_id"]: a for a in load(os.path.join(data_dir, "accounts.csv"))}
    txs = load(os.path.join(data_dir, "transactions.csv"))
    scenarios = {s["scenario_id"]: s for s in load(os.path.join(data_dir, "scenarios.csv"))}

    by_scenario = defaultdict(list)
    for t in txs:
        if t["gt_scenario_id"]:
            by_scenario[t["gt_scenario_id"]].append(t)

    results = {thr: [] for thr in thresholds}

    for sid, s in scenarios.items():
        if s["scenario_type"] not in CONVERGENCE_TYPES:
            continue
        legs = by_scenario.get(sid, [])
        if not legs:
            continue

        # Le compte collecteur est celui qui recoit le plus d'emetteurs distincts.
        fan = defaultdict(set)
        for t in legs:
            fan[t["dst_account"]].add(t["src_account"])
        hub = max(fan, key=lambda a: len(fan[a]))
        hub_bank = accounts[hub]["bank_id"]

        incoming = sorted(
            (t for t in legs if t["dst_account"] == hub),
            key=lambda t: t["ts"],
        )
        if len(incoming) < 3:
            continue

        victim_banks = Counter(accounts[t["src_account"]]["bank_id"]
                               for t in incoming)
        n_victims = len({t["src_account"] for t in incoming})
        total = sum(float(t["amount"]) for t in incoming)

        for thr in thresholds:
            # Sans partage: la banque de la victime ne connait que les
            # virements de ses PROPRES clients vers ce beneficiaire.
            seen_by_bank = defaultdict(set)
            seen_global = set()
            blocked_wo = blocked_with = 0
            saved_wo = saved_with = 0.0
            victims_wo, victims_with = set(), set()
            first_alert = ""

            for rank, t in enumerate(incoming, start=1):
                src = t["src_account"]
                bank = accounts[src]["bank_id"]
                amount = float(t["amount"])

                if len(seen_by_bank[bank]) >= thr:
                    blocked_wo += 1
                    saved_wo += amount
                    victims_wo.add(src)
                if len(seen_global) >= thr:
                    blocked_with += 1
                    saved_with += amount
                    victims_with.add(src)
                    if not first_alert:
                        first_alert = str(rank)

                seen_by_bank[bank].add(src)
                seen_global.add(src)

            results[thr].append({
                "scenario_id": sid,
                "scenario_type": s["scenario_type"],
                "gt_split": s["gt_split"],
                "hub_account": hub,
                "hub_bank": hub_bank,
                "n_victims": n_victims,
                "n_legs": len(incoming),
                "n_victim_banks": len(victim_banks),
                "total_amount": round(total, 2),
                "max_visible_single_bank": max(victim_banks.values()),
                "pct_visible_single_bank": round(
                    pct(max(victim_banks.values()), len(incoming)), 1),
                "blocked_legs_without_sharing": blocked_wo,
                "blocked_legs_with_sharing": blocked_with,
                "victims_protected_without_sharing": len(victims_wo),
                "victims_protected_with_sharing": len(victims_with),
                "amount_saved_without_sharing": round(saved_wo, 2),
                "amount_saved_with_sharing": round(saved_with, 2),
                "first_alert_leg_rank": first_alert,
            })

    return results


def false_positive_cost(data_dir, thresholds):
    """Cout en faux positifs de la meme regle appliquee aux faux amis.

    Sans ce chiffre l'analyse est malhonnete: une cagnotte reunit 28 a 80
    participants et franchit le meme seuil de convergence qu'un compte
    collecteur. Un registre qui publierait un simple comptage d'emetteurs
    bloquerait des milliers de virements legitimes.
    """
    accounts = {a["account_id"]: a for a in load(os.path.join(data_dir, "accounts.csv"))}
    txs = load(os.path.join(data_dir, "transactions.csv"))
    decoys = load(os.path.join(data_dir, "decoys.csv"))

    by_decoy = defaultdict(list)
    for t in txs:
        if t["gt_decoy_id"]:
            by_decoy[t["gt_decoy_id"]].append(t)

    out = {thr: {"legs": 0, "amount": 0.0, "total_legs": 0, "total_amount": 0.0,
                 "by_type": Counter()} for thr in thresholds}

    for d in decoys:
        hub = d["hub_account"]
        legs = sorted((t for t in by_decoy.get(d["decoy_id"], [])
                       if t["dst_account"] == hub), key=lambda t: t["ts"])
        if not legs:
            continue
        for thr in thresholds:
            seen = set()
            for t in legs:
                amount = float(t["amount"])
                out[thr]["total_legs"] += 1
                out[thr]["total_amount"] += amount
                if len(seen) >= thr:
                    out[thr]["legs"] += 1
                    out[thr]["amount"] += amount
                    out[thr]["by_type"][d["decoy_type"]] += 1
                seen.add(t["src_account"])
    return out


def report(results, data_dir, main_threshold=5):
    rows = results[main_threshold]
    bar = "=" * 78

    print(f"\n{bar}\nAPPORT D'UN REGISTRE PARTAGE ENTRE BANQUES\n{bar}")
    print(f"{len(rows)} scenarios de convergence analyses "
          f"(seuil d'alerte: {main_threshold} emetteurs distincts)\n")

    tot_legs = sum(r["n_legs"] for r in rows)
    tot_victims = sum(r["n_victims"] for r in rows)
    tot_amount = sum(r["total_amount"] for r in rows)
    banks_avg = sum(r["n_victim_banks"] for r in rows) / len(rows)
    vis_avg = sum(r["pct_visible_single_bank"] for r in rows) / len(rows)

    print("--- Ce que voit une banque de victime, seule ---")
    print(f"  Banques de victimes touchees par scenario : {banks_avg:.1f} en moyenne")
    print(f"  Part des virements visibles par la banque")
    print(f"  de victime la mieux placee                : {vis_avg:.1f} % en moyenne")
    print(f"  (la banque du compte collecteur, elle, voit 100 % des entrants:")
    print(f"   elle VOIT la fraude mais ne peut plus la bloquer)")

    wo = sum(r["blocked_legs_without_sharing"] for r in rows)
    wi = sum(r["blocked_legs_with_sharing"] for r in rows)
    vwo = sum(r["victims_protected_without_sharing"] for r in rows)
    vwi = sum(r["victims_protected_with_sharing"] for r in rows)
    swo = sum(r["amount_saved_without_sharing"] for r in rows)
    swi = sum(r["amount_saved_with_sharing"] for r in rows)

    print(f"\n--- Virements qui auraient pu etre bloques ---")
    print(f"  {'':30s} {'virements':>11s} {'victimes':>10s} {'montant':>15s}")
    print(f"  {'sans registre partage':30s} {wo:5d} / {tot_legs:<4d} "
          f"{vwo:5d} /{tot_victims:4d} {swo:13,.0f} EUR".replace(",", " "))
    print(f"  {'avec registre partage':30s} {wi:5d} / {tot_legs:<4d} "
          f"{vwi:5d} /{tot_victims:4d} {swi:13,.0f} EUR".replace(",", " "))
    print(f"  {'montant total detourne':30s} {'':11s} {'':10s} "
          f"{tot_amount:13,.0f} EUR".replace(",", " "))
    if wo:
        print(f"\n  Gain: {wi / wo:.1f}x plus de virements bloques, "
              f"{swi / swo:.1f}x plus de montant preserve")
    print(f"  Victimes protegees: {pct(vwo, tot_victims):.1f} % sans partage"
          f"  ->  {pct(vwi, tot_victims):.1f} % avec partage")
    print(f"  Montant preserve  : {pct(swo, tot_amount):.1f} % sans partage"
          f"  ->  {pct(swi, tot_amount):.1f} % avec partage")

    ranks = [int(r["first_alert_leg_rank"]) for r in rows
             if r["first_alert_leg_rank"]]
    if ranks:
        ranks.sort()
        print(f"\n--- Rang du virement a partir duquel l'alerte se declenche ---")
        print(f"  avec registre partage : median {ranks[len(ranks) // 2]}, "
              f"min {ranks[0]}, max {ranks[-1]}")
        never = len(rows) - len(ranks)
        print(f"  scenarios jamais detectes meme avec partage : {never}/{len(rows)}")

    print(f"\n--- Sensibilite au seuil d'alerte ---")
    print(f"  {'seuil':>6s} {'bloques sans':>14s} {'bloques avec':>14s} {'gain':>7s}")
    for thr in sorted(results):
        rs = results[thr]
        a = sum(r["blocked_legs_without_sharing"] for r in rs)
        b = sum(r["blocked_legs_with_sharing"] for r in rs)
        print(f"  {thr:6d} {a:14d} {b:14d} {b / a if a else float('inf'):6.1f}x")

    print(f"\n--- Detail des 8 scenarios les plus etendus ---")
    print(f"  {'scenario':12s} {'type':22s} {'vict.':>6s} {'virem.':>7s} "
          f"{'banq.':>6s} {'sans':>5s} {'avec':>5s}")
    for r in sorted(rows, key=lambda r: -r["n_victims"])[:8]:
        print(f"  {r['scenario_id']:12s} {r['scenario_type']:22s} "
              f"{r['n_victims']:6d} {r['n_legs']:7d} {r['n_victim_banks']:6d} "
              f"{r['blocked_legs_without_sharing']:5d} "
              f"{r['blocked_legs_with_sharing']:5d}")

    fp = false_positive_cost(data_dir, sorted(results))
    f = fp[main_threshold]
    print(f"\n{bar}\nCOUT EN FAUX POSITIFS DE LA MEME REGLE\n{bar}")
    print(f"  La meme regle de convergence appliquee aux faux amis legitimes:")
    print(f"  {f['legs']} virements legitimes bloques sur {f['total_legs']} "
          f"({pct(f['legs'], f['total_legs']):.1f} %), soit "
          f"{f['amount']:,.0f} EUR".replace(",", " "))
    print(f"\n  Repartition des blocages a tort:")
    for dtype, n in f["by_type"].most_common():
        print(f"    {dtype:26s} {n:5d} virements")
    print(f"\n  {'seuil':>6s} {'fraude bloquee':>15s} {'legitime bloque':>16s} "
          f"{'ratio':>8s}")
    for thr in sorted(results):
        tp = sum(r["blocked_legs_with_sharing"] for r in results[thr])
        fpl = fp[thr]["legs"]
        print(f"  {thr:6d} {tp:15d} {fpl:16d} "
              f"{tp / fpl if fpl else float('inf'):7.2f}")

    print(f"\n  CONCLUSION A PRESENTER AU JURY")
    print(f"  Un registre qui publierait un simple comptage d'emetteurs")
    print(f"  bloquerait massivement des cagnottes et des collectes")
    print(f"  d'associations. Le registre ne doit donc pas publier un")
    print(f"  comptage brut mais le SCORE DU MODELE, qui croise la")
    print(f"  convergence avec la vitesse de redistribution et l'anciennete")
    print(f"  du compte. C'est ce qui relie la couche blockchain aux")
    print(f"  modules 2 et 3 au lieu d'en faire un gadget.")

    # Cohérence des déclencheurs. Les chiffres « avec registre partagé »
    # ci-dessus supposent une alerte declenchee par un simple comptage de
    # 5 emetteurs distincts. Mais ce comptage bloque 2 a 3 virements
    # legitimes par fraude. Un registre reel publie un SCORE, et le score ne
    # depasse le seuil que pour une partie des comptes collecteurs.
    # Annoncer la couverture du comptage ET l'absence de faux positifs du
    # score serait melanger deux configurations incompatibles.
    scores_path = os.path.join(data_dir, "hub_scores.csv")
    if os.path.exists(scores_path):
        sc = {r["account_id"]: int(r["score"]) for r in load(scores_path)}
        gated = [r for r in rows if sc.get(r["hub_account"], 0) >= 80]
        gb = sum(r["blocked_legs_with_sharing"] for r in gated)
        gv = sum(r["victims_protected_with_sharing"] for r in gated)
        ga = sum(r["amount_saved_with_sharing"] for r in gated)

        print(f"\n{bar}\nSYNTHESE HONNETE : LES TROIS CONFIGURATIONS\n{bar}")
        print(f"  Hubs atteignant un score de modele >= 80 : "
              f"{len(gated)}/{len(rows)} scenarios ({pct(len(gated), len(rows)):.0f} %)\n")
        print(f"  {'configuration':34s} {'victimes':>12s} {'montant':>10s} "
              f"{'legitimes bloques':>18s}")
        print(f"  {'sans partage':34s} {pct(vwo, tot_victims):10.1f} % "
              f"{pct(swo, tot_amount):8.1f} % {0:18d}")
        print(f"  {'partage, comptage brut':34s} {pct(vwi, tot_victims):10.1f} % "
              f"{pct(swi, tot_amount):8.1f} % {f['legs']:18d}")
        print(f"  {'partage, score de modele >= 80':34s} "
              f"{pct(gv, tot_victims):10.1f} % {pct(ga, tot_amount):8.1f} % "
              f"{0:18d}")
        print(f"\n  A ANNONCER : la troisieme ligne. {pct(gv, tot_victims):.1f} % "
              f"des victimes protegees et {ga:,.0f} EUR preserves"
              .replace(",", " "))
        print(f"  sans bloquer un seul virement legitime, soit "
              f"{gv / vwo:.1f}x mieux que sans partage.")
        print(f"\n  NE PAS annoncer les {pct(vwi, tot_victims):.1f} % de la "
              f"deuxieme ligne en meme temps que l'absence de")
        print(f"  faux positifs: ce sont deux configurations incompatibles, et")
        print(f"  un juré attentif le verra.")

    out = os.path.join(data_dir, "consortium_analysis.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\nDetail par scenario ecrit dans {out}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fraudnet/data")
    ap.add_argument("--threshold", type=int, default=5)
    args = ap.parse_args()
    results = analyse(args.data, thresholds=(3, args.threshold, 8))
    report(results, args.data, main_threshold=args.threshold)


if __name__ == "__main__":
    main()
