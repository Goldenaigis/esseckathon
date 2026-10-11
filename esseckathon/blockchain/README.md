# FraudNet on-chain : notre L1 Avalanche

Chaque compte du jeu de données FraudNet devient un **wallet** sur une blockchain
Avalanche dédiée (une « L1 »). Chaque virement devient une **vraie transaction**
en euro tokenisé (`EURF`), signée par le wallet émetteur. Le Module 2 lit ensuite
le graphe des flux directement depuis la chaîne, et les banques publient leurs
alertes dans un registre partagé.

```
fraudnet/data/*.csv ──► 1 wallet par compte (7 060) + 1 par banque (24) + 1 admin
                        │
L1 Avalanche "fraudnet" │  jeton de gas natif : FNET
  ├─ EURToken (EURF)    │  soldes initiaux + 146 533 virements rejoués (event Payment)
  ├─ GasFunder          │  distribue le gas aux wallets par lots
  └─ FraudRegistry      │  alertes inter-banques (comptes hachés), notarisation des données
                        ▼
python fraudnet_chain.py export ──► onchain_transactions.csv ──► Module 2 (graphe, score)
python fraudnet_chain.py report ──► alertes publiées par une banque, consultables par toutes
```

Ce qui ne va **jamais** sur la chaîne : les noms, les colonnes `gt_` (vérité
terrain), le lien compte ↔ personne. `wallets.json` (compte → adresse) reste
chez la banque, comme un fichier KYC.

Dans le registre d'alertes, les comptes sont **pseudonymisés** par
`keccak256(sel du consortium + account_id)` : aucune donnée personnelle en clair,
mais ce n'est pas une anonymisation (le RGPD s'applique toujours, et qui connaît le
sel peut énumérer les identifiants). En production : intersection privée
d'ensembles (PSI) entre banques.

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
| `scripts/5_registry.js` | redéploie uniquement FraudRegistry et réinscrit les banques (`npm run registry`) |
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
npm run fund        # ~10 min : gas + soldes EURF + banques (~150 transactions séquentielles)
npm run replay -- --limit 5000   # essai rapide
npm run replay      # tout le reste (1 528 lots, 30 à 60 min, reprend où il s'est arrêté)
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

`onchain_transactions.csv` contient :
- lu sur la chaîne : `tx_id, ts, src_account, dst_account, amount`, les adresses,
  le bloc et le hash de transaction ;
- joint hors chaîne sur `tx_id` : `instrument, tx_type, channel, currency,
  src_country, dst_country` (variables du Module 2 ; le périmètre scorable
  est `instrument == "credit_transfer"`). `--chain-only` pour ne garder que la chaîne.
- `label` (libellé du virement) est **volontairement exclu** : dans le jeu 60 jours,
  21 libellés n'apparaissent que sur des fraudes et cette colonne seule atteint
  F1 0,949 (fuite de données, corrigée dans le jeu 1 an).

Jamais de colonne `gt_` : la jointure avec `transactions.csv` sur ces colonnes sert
uniquement à l'évaluation.

`demo-alerts` utilise la vérité terrain : à remplacer par la sortie du Module 2,
au même format (`account_id, score, pattern, evidence`).

## Démo principale : un scénario vu des banques des victimes

```bash
$PY python/fraudnet_chain.py demo-scenario              # SCN_049 par défaut (jeu de test) ; --decoy DEC_001
```

Rejoue les 38 virements vers le compte collecteur `ACC_006950` (26 victimes, 8
banques). Avant chaque virement, la banque de la victime interroge `isFlagged` sur
la chaîne. Au 6e virement, la banque du collecteur calcule le score point-in-time
(86) et le publie car il dépasse le seuil de 80. Résultat on-chain : 33/38
virements bloqués, 7 025,92 EUR préservés (88 %), identique à
`fraudnet/data/consortium_analysis.csv`. Contraste : la cagnotte `DEC_001`
(84 participants) obtient 26, la banque ne publie rien, les invités passent.

Message : la banque qui **peut** bloquer (celle de la victime) ne voit qu'un virement
ordinaire ; la banque qui **voit** la convergence (celle du collecteur) ne peut que
constater. Le registre fait passer le signal de l'une à l'autre. Il publie un
**score**, pas un comptage d'émetteurs : une règle de seuil partagée bloquerait plus
de 2 virements légitimes (cagnottes, associations) par fraude.

Sur les 49 scénarios de convergence (analyse du Module 1,
`python -m fraudnet.analysis.consortium --data fraudnet/data`) :

| Configuration | Victimes protégées | Montant préservé | Virements légitimes bloqués |
|---|---|---|---|
| Sans partage | 10,2 % | 8,7 % | 0 |
| Partage d'un comptage brut (≥ 5 émetteurs) | 83,8 % | 81,2 % | **2 346** |
| **Partage du score ≥ 80 (ce registre)** | **41,5 %** | **40,0 %** | **0** |

Le résultat à annoncer est la **troisième ligne** : 41,5 % des victimes protégées et
1 316 715 EUR préservés sans bloquer un seul virement légitime, soit 4,1 fois mieux
que sans partage. La deuxième ligne est le repoussoir : elle montre pourquoi on
partage un score et pas une règle de seuil. Ne jamais citer 83,8 % avec « zéro faux
positif » : ce sont deux configurations différentes.

Seuls 22 des 49 hubs atteignent 80 ; les 27 autres sont des comptes anciens avec
historique (mules recrutées parmi des clients existants). Un indicateur de rupture
de comportement au Module 2 est le levier pour remonter ces chiffres. Abaisser le
seuil à 75 augmente la couverture mais fait apparaître des faux positifs.

### Les scores : `fraudnet/data/hub_scores.csv`

**Heuristique point-in-time du Module 1, à remplacer par le modèle du Module 3** (ce
n'est pas un modèle appris). Calculée à l'instant où le compte atteint 5 émetteurs
distincts en 24 h, avec uniquement l'information disponible à cet instant :
convergence, ancienneté du compte, absence d'historique, dispersion des banques
émettrices, nouveauté des émetteurs, redistribution déjà commencée.

- Le score plafonne à 88 : seuil de publication et de blocage à **80**.
- Au seuil 80 : 25 comptes signalés, aucun faux positif parmi eux, 0 faux ami sur 42,
  sur trois tirages différents. Formulation honnête : « sur notre jeu de test,
  aucun faux positif parmi les comptes signalés » (19 à 25 comptes, données
  synthétiques), pas « 100 % en production ».
- Rappel 46 % : une mule recrutée parmi des clients existants (compte ancien, avec
  historique) reste sous le seuil. C'est la rupture de comportement que le Module 2
  doit détecter.
- Exemple : le hub de SCN_062 n'obtient que 23 à l'instant de décision ; il n'est
  donc pas signalé, d'où le choix de SCN_049 pour la démo.

```bash
$PY python/fraudnet_chain.py publish-scores --min-score 80   # chaque banque publie pour ses clients
```

## Démo du registre d'alertes (retrait d'un faux positif)

```bash
$PY python/fraudnet_chain.py check ACC_001359                          # aucun signalement
$PY python/fraudnet_chain.py report --bank BNK_01 --alerts a90.csv     # score 90
$PY python/fraudnet_chain.py report --bank BNK_02 --alerts a60.csv     # score 60
$PY python/fraudnet_chain.py check ACC_001359                          # 2 banques, max 90
$PY python/fraudnet_chain.py retract --bank BNK_01 ACC_001359          # faux positif
$PY python/fraudnet_chain.py check ACC_001359                          # 1 banque, max 60
```

`isFlagged` recalcule à chaque lecture sur les seuls signalements actifs de membres
actuels : un retrait ou l'exclusion d'une banque fait redescendre le score.

## Notes techniques

- Seuls les virements `completed` sont rejoués (`pending` / `rejected` n'existent pas on-chain).
- Les soldes initiaux sont reconstruits depuis les soldes finaux. 1 543 comptes sont
  légèrement rehaussés : ils dépensent avant d'encaisser dans la fenêtre, donc leur solde
  reconstruit passerait sous zéro pendant le rejeu, ce qu'un ERC-20 refuse. Le rehaussement
  est exactement le découvert maximal de chaque compte, vérifié par simulation : plus aucun
  solde négatif sur les 146 533 virements.
- L'horodatage d'origine est conservé dans l'événement `Payment` (`originalTs`) ;
  l'horodatage du bloc est celui du rejeu.
- Nonce déterministe : le k-ième virement d'un compte porte le nonce k. Relancer
  `npm run replay` après une coupure ne paie jamais deux fois.
- Tests : `npm test` (11 tests). Pipeline validé sur la L1 : 146 533 virements
  rejoués, export on-chain identique au CSV (0 différence, 0 manquant).
- Avalanche (Subnet-EVM) : web3.py a besoin de `ExtraDataToPOAMiddleware`.

## Windows (Git Bash)

Les commandes ci-dessus supposent macOS ou Linux. Sous Windows, trois choses ne
marchent pas telles quelles : `curl ... | sh` (le script d'installation d'avalanche-cli
ne reconnait que linux et darwin), `export PATH=~/bin:$PATH` (`~/bin` n'est pas vu par
les programmes Windows) et `.venv/bin/python` (c'est `.venv/Scripts/python.exe`).

### Ce qu'il faut installer

| Etape | Commande | Temps |
|---|---|---|
| Node.js 22 LTS | `winget install OpenJS.NodeJS.LTS` puis rouvrir le terminal | 5 min |
| Dependances npm | `cd esseckathon/blockchain && npm ci` | 3 min |
| Compilation | `npx hardhat compile` (telecharge solc 0.8.24) | 2 min |
| Tests | `npm test` | 1 min |
| venv Python | `python -m venv .venv && .venv/Scripts/python.exe -m pip install -r python/requirements.txt` | 2 min |
| L1 Avalanche | voir ci-dessous | 30 a 45 min |

`package-lock.json` contient bien le binaire natif `@nomicfoundation/edr-win32-x64-msvc`,
donc `npm ci` suffit, sans Visual Studio Build Tools. Les deux etapes npm et la
compilation ont besoin du reseau.

Python : teste sur 3.14.2 avec `web3==7.6.0`, les roues sont disponibles, rien a compiler.
Exporter `PYTHONUTF8=1` avant tout appel (`accounts.csv` contient des accents et
l'encodage par defaut de la console est cp1252).

### La L1 : passer par WSL2

avalanche-cli ne s'installe pas sous Windows natif. Le plus court est WSL2 :

```bash
wsl --install -d Ubuntu          # redemarrage necessaire, 15 min
# dans Ubuntu :
curl -sSfL https://raw.githubusercontent.com/ava-labs/avalanche-cli/main/scripts/install.sh | sh -s
export PATH=~/bin:$PATH
avalanche blockchain create fraudnet --evm --latest --evm-chain-id 20261 --evm-token FNET --proof-of-authority
avalanche blockchain deploy fraudnet --local
```

Le reste (npm, scripts, Python) peut rester sous Windows : WSL2 expose ses ports sur
`localhost`, donc l'URL RPC `http://127.0.0.1:9650/ext/bc/.../rpc` est joignable des
deux cotes. Compter 8 Go de RAM libres et le telechargement d'avalanchego au premier
`deploy --local`. Si la place manque, tout faire dans WSL2 (y compris `npm ci`) et
copier le dossier dedans.

### Temps reels des etapes du pipeline

```bash
npm run wallets                  # 7 085 derivations HD, 30 s
npm run deploy                   # 10 s
npm run fund                     # 10 min : ~150 transactions sequentielles + 14 000 appels RPC
npm run replay -- --limit 5000   # 2 min, pour verifier la chaine avant de lancer le reste
npm run replay                   # 1 528 lots pour 146 533 virements, 30 a 60 min
PY=.venv/Scripts/python.exe
$PY python/fraudnet_chain.py export --out onchain_transactions.csv   # 5 a 15 min
$PY python/fraudnet_chain.py demo-scenario                           # 1 min
```

Pour la demo du jury, `demo-scenario` n'a besoin que de `deploy` et de `fund` : les
146 533 virements ne servent qu'au Module 2. Lancer le rejeu complet la veille.
