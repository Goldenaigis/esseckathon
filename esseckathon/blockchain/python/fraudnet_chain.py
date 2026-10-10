"""Pont entre FraudNet et la L1 Avalanche FraudNet.

Commandes (depuis le dossier blockchain/) :
  python python/fraudnet_chain.py export  --out onchain_transactions.csv
  python python/fraudnet_chain.py anchor  --bank BNK_01
  python python/fraudnet_chain.py demo-alerts --out alerts_demo.csv --limit 10
  python python/fraudnet_chain.py report  --bank BNK_01 --alerts alerts_demo.csv
  python python/fraudnet_chain.py check   ACC_000123
  python python/fraudnet_chain.py retract --bank BNK_01 ACC_000123

- export : lit les evenements Payment du jeton EURF et reconstruit la table des
  virements a partir de la chaine (entree du module 2), puis joint sur tx_id les
  variables hors chaine (instrument, tx_type, channel...). Jamais de colonne gt_.
- Les alertes sont publiees sous la forme keccak256("<CONSORTIUM_SALT>:<account_id>"),
  signees par le wallet de la banque qui les emet.
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT.parent / "fraudnet" / "data"
ARTIFACTS = ROOT / "artifacts" / "contracts"
LOG_CHUNK = 2000

# Meme ordre que l'enum Pattern de FraudRegistry.sol (et PATTERN_TYPES de shared/schema.py)
PATTERNS = (
    "fan_in_redistribution",
    "smurfing",
    "layering_chain",
    "dormant_reactivation",
    "cycle",
    "fan_in_only",
)

# Type de scenario (verite terrain) -> motif, pour les alertes de demo uniquement
SCENARIO_TO_PATTERN = {
    "compte_collecteur": "fan_in_redistribution",
    "smurfing": "smurfing",
    "chaine_mules": "layering_chain",
    "dormant_reactive": "dormant_reactivation",
    "cycle": "cycle",
    "faux_conseiller": "fan_in_only",
    "faux_investissement": "fan_in_only",
}


# ----------------------------------------------------------------- connexion

class Chain:
    def __init__(self):
        load_dotenv(ROOT / ".env")
        self.salt = os.getenv("CONSORTIUM_SALT", "")
        self.mnemonic = os.getenv("MNEMONIC", "")
        rpc = os.getenv("L1_RPC_URL", "")
        if not rpc:
            sys.exit("L1_RPC_URL manquant dans .env")
        self.wallets = self._json(ROOT / "wallets.json", "lance 'npm run wallets'")
        self.deployment = self._json(ROOT / "deployment.json", "lance 'npm run deploy'")
        self.w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 60}))
        # les blocs Avalanche (Subnet-EVM) ont un extraData plus long que sur Ethereum
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        if not self.w3.is_connected():
            sys.exit(f"Impossible de joindre {rpc} : la L1 est-elle demarree ? (avalanche network start)")
        self.token = self._contract("EURToken")
        self.registry = self._contract("FraudRegistry")
        self.address_to_account = {
            Web3.to_checksum_address(v["address"]): k for k, v in self.wallets["accounts"].items()
        }

    @staticmethod
    def _json(path, hint):
        if not path.exists():
            sys.exit(f"{path.name} introuvable : {hint}")
        return json.loads(path.read_text())

    def _contract(self, name):
        abi = json.loads((ARTIFACTS / f"{name}.sol" / f"{name}.json").read_text())["abi"]
        return self.w3.eth.contract(address=self.deployment["contracts"][name], abi=abi)

    def bank_account(self, bank_id):
        if bank_id not in self.wallets["banks"]:
            sys.exit(f"Banque inconnue : {bank_id}")
        Account.enable_unaudited_hdwallet_features()
        index = self.wallets["banks"][bank_id]["index"]
        return Account.from_mnemonic(self.mnemonic, account_path=f"m/44'/60'/0'/0/{index}")

    def account_hash(self, account_id):
        if not self.salt:
            sys.exit("CONSORTIUM_SALT manquant dans .env")
        return Web3.keccak(text=f"{self.salt}:{account_id}")

    def send(self, signer, fn):
        tx = fn.build_transaction({
            "from": signer.address,
            "nonce": self.w3.eth.get_transaction_count(signer.address),
            "chainId": self.w3.eth.chain_id,
        })
        tx_hash = self.w3.eth.send_raw_transaction(signer.sign_transaction(tx).raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status != 1:
            sys.exit(f"Transaction echouee : {tx_hash.hex()}")
        return "0x" + tx_hash.hex().removeprefix("0x")


# ------------------------------------------------------------------ commandes

# Variables hors chaine jointes sur tx_id (jamais les colonnes gt_ : verite terrain).
# `label` est exclu : dans le jeu 60 jours, 21 libelles n'apparaissent que sur des
# fraudes et la colonne resout le probleme a elle seule (F1 0,949) -> fuite.
OFFCHAIN_FEATURES = ("instrument", "tx_type", "channel", "currency", "src_country", "dst_country")


def cmd_export(args):
    c = Chain()
    features = {}
    if not args.chain_only:
        with open(DATA_DIR / "transactions.csv", newline="") as f:
            for r in csv.DictReader(f):
                features[r["tx_id"]] = [r.get(k, "") for k in OFFCHAIN_FEATURES]
    last = c.w3.eth.block_number
    event = c.token.events.Payment
    n = 0
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tx_id", "ts", "src_account", "dst_account", "amount",
                    "src_address", "dst_address", "block_number", "onchain_tx_hash"]
                   + ([] if args.chain_only else list(OFFCHAIN_FEATURES)))
        for start in range(0, last + 1, LOG_CHUNK):
            logs = event.get_logs(from_block=start, to_block=min(start + LOG_CHUNK - 1, last))
            for log in logs:
                e = log["args"]
                tx_id = e["txRef"].rstrip(b"\0").decode()
                row = [
                    tx_id,
                    datetime.fromtimestamp(e["originalTs"], tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                    c.address_to_account.get(e["from"], ""),
                    c.address_to_account.get(e["to"], ""),
                    f"{e['amount'] / 100:.2f}",
                    e["from"], e["to"], log["blockNumber"], "0x" + log["transactionHash"].hex().removeprefix("0x"),
                ]
                if not args.chain_only:
                    row += features.get(tx_id, [""] * len(OFFCHAIN_FEATURES))
                w.writerow(row)
                n += 1
            print(f"\r  blocs {min(start + LOG_CHUNK - 1, last)}/{last} - {n} virements", end="")
    print(f"\n{n} virements on-chain exportes dans {args.out}")


def cmd_anchor(args):
    c = Chain()
    digest = hashlib.sha256()
    for f in sorted(DATA_DIR.glob("*.csv")) + [DATA_DIR / "manifest.json"]:
        digest.update(f.name.encode())
        digest.update(f.read_bytes())
    manifest = json.loads((DATA_DIR / "manifest.json").read_text())
    label = f"fraudnet schema {manifest.get('schema_version')} seed {manifest['config'].get('seed')}"
    tx = c.send(c.bank_account(args.bank), c.registry.functions.anchorDataset(digest.digest(), label))
    print(f"Jeu de donnees notarise : sha256={digest.hexdigest()} (tx {tx})")


def cmd_demo_alerts(args):
    """Alertes fabriquees depuis la verite terrain (mules du split test).

    A remplacer par la sortie du module 2 : meme format de CSV.
    """
    scenarios = {r["scenario_id"]: r for r in csv.DictReader(open(DATA_DIR / "scenarios.csv", newline=""))}
    rows = []
    for r in csv.DictReader(open(DATA_DIR / "accounts.csv", newline="")):
        scn = scenarios.get(r["gt_scenario_id"])
        if r["gt_role"] == "mule" and scn and scn["gt_split"] == "test":
            rows.append({
                "account_id": r["account_id"],
                "score": 90,
                "pattern": SCENARIO_TO_PATTERN[scn["scenario_type"]],
                "evidence": f"{scn['scenario_id']} {scn['description_fr']}",
            })
        if len(rows) >= args.limit:
            break
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["account_id", "score", "pattern", "evidence"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} alertes de demo ecrites dans {args.out}")


def load_hub_scores():
    """Scores point-in-time des comptes beneficiaires (heuristique du Module 1, a remplacer
    par le modele du Module 3). Format : account_id, score, pattern, evidence. Aucune colonne gt_."""
    path = DATA_DIR / "hub_scores.csv"
    if not path.exists():
        sys.exit("hub_scores.csv introuvable (fraudnet/analysis/hub_scores.py)")
    return {r["account_id"]: r for r in csv.DictReader(open(path, newline=""))}


def cmd_publish_scores(args):
    """Publie les scores >= seuil, chacun au nom de la banque qui tient le compte."""
    c = Chain()
    bank_of = {r["account_id"]: r["bank_id"] for r in csv.DictReader(open(DATA_DIR / "accounts.csv", newline=""))}
    rows = [r for r in load_hub_scores().values() if int(r["score"]) >= args.min_score]
    for r in rows:
        bank = bank_of[r["account_id"]]
        tx = c.send(c.bank_account(bank), c.registry.functions.reportAlert(
            c.account_hash(r["account_id"]), int(r["score"]), PATTERNS.index(r["pattern"]),
            hashlib.sha256(r["evidence"].encode()).digest()))
        print(f"{bank} signale {r['account_id']} (score {r['score']}, {r['pattern']}) tx {tx[:12]}...")
    print(f"{len(rows)} alertes publiees (score >= {args.min_score})")


def cmd_demo_scenario(args):
    """Rejoue un scenario de fraude du point de vue des banques des victimes.

    Avant chaque virement vers le compte collecteur, la banque de la victime interroge
    isFlagged sur la chaine. La banque du collecteur publie le score du modele au rang
    ou l'alerte se declenche (first_alert_leg_rank de consortium_analysis.csv), avec le
    score point-in-time de hub_scores.csv, seulement s'il atteint le seuil.
    Puis contraste avec un faux ami (cagnotte...) et son propre score.
    Demo : s'appuie sur la verite terrain pour choisir le scenario, jamais en production.
    """
    c = Chain()
    analysis = {r["scenario_id"]: r for r in csv.DictReader(open(DATA_DIR / "consortium_analysis.csv", newline=""))}
    if args.scenario not in analysis:
        sys.exit(f"Scenario absent de consortium_analysis.csv : {args.scenario}")
    a = analysis[args.scenario]
    hub, hub_bank, alert_rank = a["hub_account"], a["hub_bank"], int(a["first_alert_leg_rank"])
    scn = next(r for r in csv.DictReader(open(DATA_DIR / "scenarios.csv", newline="")) if r["scenario_id"] == args.scenario)
    bank_of = {r["account_id"]: r["bank_id"] for r in csv.DictReader(open(DATA_DIR / "accounts.csv", newline=""))}
    legs = sorted(
        (r for r in csv.DictReader(open(DATA_DIR / "transactions.csv", newline=""))
         if r["gt_scenario_id"] == args.scenario and r["dst_account"] == hub and r["status"] == "completed"),
        key=lambda r: r["ts"],
    )
    scores = load_hub_scores()
    hub_hash = c.account_hash(hub)
    collector = c.bank_account(hub_bank)

    # remise a zero pour pouvoir rejouer la demo
    if c.registry.functions.getReport(hub_hash, collector.address).call()[0]:
        c.send(collector, c.registry.functions.retractAlert(hub_hash))

    banks = sorted({bank_of[l["src_account"]] for l in legs})
    print(f"\n=== {args.scenario} : {scn['scenario_type_fr']} ===")
    print(f"Compte collecteur {hub} chez {hub_bank} | {len(legs)} virements entrants de "
          f"{len({l['src_account'] for l in legs})} victimes reparties dans {len(banks)} banques")
    hs = scores.get(hub)
    print(f"Score point-in-time du hub : {hs['score'] if hs else 'absent'} ({hs['evidence'] if hs else '-'})")
    print(f"Seuil de publication et de blocage : score >= {args.threshold}\n")

    sent = blocked = 0
    saved = 0.0
    for k, leg in enumerate(legs, start=1):
        if k == alert_rank:
            if hs and int(hs["score"]) >= args.threshold:
                tx = c.send(collector, c.registry.functions.reportAlert(
                    hub_hash, int(hs["score"]), PATTERNS.index(hs["pattern"]),
                    hashlib.sha256(hs["evidence"].encode()).digest()))
                print(f"  >>> {hub_bank} (banque du collecteur) publie le score {hs['score']}, "
                      f"{hs['pattern']} (tx {tx[:12]}...)")
            else:
                print(f"  >>> {hub_bank} calcule le score : {hs['score'] if hs else '?'} < {args.threshold}, "
                      f"rien n'est publie")
        flagged, count, max_score, _ = c.registry.functions.isFlagged(hub_hash).call()
        bank = bank_of[leg["src_account"]]
        if flagged and max_score >= args.threshold:
            blocked += 1
            saved += float(leg["amount"])
            verdict = f"BLOQUE (signale par {count} banque, score {max_score})"
        else:
            sent += 1
            verdict = "envoye (aucun signalement)"
        print(f"  {k:>2}. {leg['ts'][5:16]}  {bank} verifie {hub} avant {float(leg['amount']):>9.2f} EUR -> {verdict}")

    total = sum(float(l["amount"]) for l in legs)
    eur = lambda x: f"{x:,.2f}".replace(",", " ")
    print(f"\nResultat : {blocked}/{len(legs)} virements bloques, {eur(saved)} EUR preserves "
          f"sur {eur(total)} EUR ({100 * saved / total:.0f} %)")

    if args.decoy:
        d = next(r for r in csv.DictReader(open(DATA_DIR / "decoys.csv", newline="")) if r["decoy_id"] == args.decoy)
        flagged, count, max_score, _ = c.registry.functions.isFlagged(c.account_hash(d["hub_account"])).call()
        print(f"\n=== Contraste : {args.decoy} {d['decoy_type_fr']} ===")
        print(f"Compte {d['hub_account']} : {d['n_accounts']} participants, {eur(float(d['total_amount']))} EUR")
        ds = scores.get(d["hub_account"])
        print(f"  Une regle de seuil (>= 5 emetteurs) le bloquerait comme un collecteur.")
        print(f"  Score point-in-time : {ds['score'] if ds else 'absent'} ({ds['evidence'] if ds else '-'})")
        print(f"  {ds['score'] if ds else '?'} < {args.threshold} : la banque ne publie rien. isFlagged -> "
              f"{'SIGNALE' if flagged else 'aucun signalement'}, les virements des invites passent.")


def cmd_report(args):
    c = Chain()
    bank = c.bank_account(args.bank)
    for a in csv.DictReader(open(args.alerts, newline="")):
        tx = c.send(bank, c.registry.functions.reportAlert(
            c.account_hash(a["account_id"]),
            int(a["score"]),
            PATTERNS.index(a["pattern"]),
            hashlib.sha256(a["evidence"].encode()).digest(),
        ))
        print(f"{args.bank} signale {a['account_id']} (score {a['score']}, {a['pattern']}) tx {tx}")


def cmd_check(args):
    c = Chain()
    flagged, count, max_score, _ = c.registry.functions.isFlagged(c.account_hash(args.account_id)).call()
    if flagged:
        print(f"ALERTE {args.account_id} : signale par {count} banque(s), score max {max_score}")
    else:
        print(f"{args.account_id} : aucun signalement actif")


def cmd_retract(args):
    c = Chain()
    tx = c.send(c.bank_account(args.bank), c.registry.functions.retractAlert(c.account_hash(args.account_id)))
    print(f"{args.bank} retire son signalement sur {args.account_id} (tx {tx})")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("export", help="reconstruit la table des virements depuis la chaine")
    s.add_argument("--out", default="onchain_transactions.csv")
    s.add_argument("--chain-only", action="store_true",
                   help="uniquement les champs lus sur la chaine, sans les variables jointes depuis transactions.csv")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("anchor", help="notarise le jeu de donnees")
    s.add_argument("--bank", default="BNK_01")
    s.set_defaults(func=cmd_anchor)

    s = sub.add_parser("demo-alerts", help="genere un CSV d'alertes de demo")
    s.add_argument("--out", default="alerts_demo.csv")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(func=cmd_demo_alerts)

    s = sub.add_parser("report", help="publie les alertes d'un CSV au nom d'une banque")
    s.add_argument("--bank", default="BNK_01")
    s.add_argument("--alerts", required=True)
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("publish-scores", help="publie les scores de hub_scores.csv au-dessus du seuil")
    s.add_argument("--min-score", type=int, default=80)
    s.set_defaults(func=cmd_publish_scores)

    s = sub.add_parser("demo-scenario", help="rejoue un scenario vu des banques des victimes")
    s.add_argument("scenario", nargs="?", default="SCN_049")
    s.add_argument("--decoy", default="DEC_001", help="faux ami a montrer en contraste ('' pour aucun)")
    s.add_argument("--threshold", type=int, default=80)
    s.set_defaults(func=cmd_demo_scenario)

    s = sub.add_parser("check", help="verifie si un compte est signale")
    s.add_argument("account_id")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("retract", help="retire un signalement (faux positif)")
    s.add_argument("--bank", default="BNK_01")
    s.add_argument("account_id")
    s.set_defaults(func=cmd_retract)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
