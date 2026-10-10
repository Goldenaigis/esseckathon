# FraudNet on-chain : notre L1 Avalanche

Chaque compte du jeu de données FraudNet devient un **wallet** sur une blockchain
Avalanche dédiée (une « L1 »). Chaque virement devient une **vraie transaction**
en euro tokenisé (`EURF`), signée par le wallet émetteur. Le Module 2 lit ensuite
le graphe des flux directement depuis la chaîne, et les banques publient leurs
alertes dans un registre partagé.

```
fraudnet/data/*.csv ──► 1 wallet par compte (7 046) + 1 par banque (24) + 1 admin
                        │
L1 Avalanche "fraudnet" │  jeton de gas natif : FNET
  ├─ EURToken (EURF)    │  soldes initiaux + 146 645 virements rejoués (event Payment)
  ├─ GasFunder          │  distribue le gas aux wallets par lots
  └─ FraudRegistry      │  alertes inter-banques (comptes hachés), notarisation des données
                        ▼
python fraudnet_chain.py export ──► onchain_transactions.csv ──► Module 2 (graphe, score)
python fraudnet_chain.py report ──► alertes publiées par une banque, consultables par toutes
```

Ce qui ne va **jamais** sur la chaîne : les noms, les colonnes `gt_` (vérité
terrain), le lien compte ↔ personne. `wallets.json` (compte → adresse) reste
chez la banque, comme un fichier KYC.

## Contenu

| Fichier | Rôle |
|---|---|
| `contracts/EURToken.sol` | euro de simulation, 2 décimales ; `pay(to, montant, tx_id, horodatage)` |
| `contracts/GasFunder.sol` | envoi du jeton natif à 100 wallets par transaction |
| `contracts/FraudRegistry.sol` | consortium de banques, `reportAlert` / `isFlagged` / `retractAlert` / `anchorDataset` |
| `scripts/1_wallets.js` | génère la phrase secrète et dérive tous les wallets → `wallets.json` |
| `scripts/2_deploy.js` | déploie les 3 contrats → `deployment.json` |
| `scripts/3_fund.js` | gas, soldes initiaux EURF, inscription des banques |
| `scripts/4_replay.js` | rejoue les virements (reprise automatique, sans doublon) |
| `python/fraudnet_chain.py` | export des virements on-chain, alertes, vérification, notarisation |

## Étapes

### 0. Prérequis (une fois)

```bash
cd ~/esseckathon/blockchain
npm install
python3 -m venv .venv && .venv/bin/pip install -r python/requirements.txt
cp -n .env.example .env
```

### 1. Installer avalanche-cli

```bash
curl -sSfL https://raw.githubusercontent.com/ava-labs/avalanche-cli/main/scripts/install.sh | sh -s
export PATH=~/bin:$PATH
avalanche --version
```

Ajoute `export PATH=~/bin:$PATH` à `~/.zshrc` pour ne pas le refaire à chaque terminal.

### 2. Générer les wallets

```bash
npm run wallets
```

Note l'**adresse ADMIN** affichée : elle reçoit le jeton de gas de la L1 à sa création.
La phrase secrète est enregistrée dans `.env` (jamais commitée).

### 3. Créer la L1

```bash
avalanche blockchain create fraudnet --evm --latest --evm-chain-id 20261 --evm-token FNET --proof-of-authority
```

Réponses à l'assistant :
- propriétaire du Validator Manager : colle l'**adresse ADMIN** ;
- valeurs par défaut : choisis de **personnaliser** (pas « test defaults ») ;
- airdrop : **Customize your airdrop**, adresse ADMIN, montant `1000000` ;
- le reste : valeurs proposées.

### 4. Démarrer la L1 en local

```bash
avalanche blockchain deploy fraudnet --local
```

À la fin, copie l'**RPC URL** (`http://127.0.0.1:9650/ext/bc/.../rpc`) dans `.env` :
`L1_RPC_URL=...`. Change aussi `CONSORTIUM_SALT`.

Arrêter / relancer plus tard : `avalanche network stop` / `avalanche network start`.

### 5. Déployer, financer, rejouer

```bash
npm run deploy      # ~10 s
npm run fund        # ~1 min : gas + soldes EURF + banques
npm run replay -- --limit 5000   # essai rapide
npm run replay      # tout le reste (~25 min, reprend où il s'est arrêté)
```

### 6. Utiliser la chaîne

```bash
PY=.venv/bin/python
$PY python/fraudnet_chain.py export --out onchain_transactions.csv   # entrée du Module 2
$PY python/fraudnet_chain.py anchor --bank BNK_01                    # notarise le jeu de données
$PY python/fraudnet_chain.py demo-alerts --limit 10                  # alertes de démo
$PY python/fraudnet_chain.py report --bank BNK_01 --alerts alerts_demo.csv
$PY python/fraudnet_chain.py check ACC_000909
$PY python/fraudnet_chain.py retract --bank BNK_01 ACC_000909        # faux positif
```

`onchain_transactions.csv` a les colonnes `tx_id, ts, src_account, dst_account,
amount` (comme `transactions.csv`, sans les `gt_`) plus les adresses, le bloc et le
hash de transaction. La jointure sur `tx_id` avec `transactions.csv` sert
uniquement à l'évaluation.

`demo-alerts` utilise la vérité terrain : à remplacer par la sortie du Module 2,
au même format (`account_id, score, pattern, evidence`).

## Notes techniques

- Seuls les virements `completed` sont rejoués (`pending` / `rejected` n'existent pas on-chain).
- Les soldes initiaux sont reconstruits depuis les soldes finaux. 1 575 comptes sont
  légèrement rehaussés : le générateur bornait les soldes à 0, ce qui créerait des
  découverts pendant le rejeu, qu'un ERC-20 refuse.
- L'horodatage d'origine est conservé dans l'événement `Payment` (`originalTs`) ;
  l'horodatage du bloc est celui du rejeu.
- Nonce déterministe : le k-ième virement d'un compte porte le nonce k. Relancer
  `npm run replay` après une coupure ne paie jamais deux fois.
- Tests : `npm test` (contrats). Pipeline validé sur 5 084 virements :
  export on-chain identique au CSV.
