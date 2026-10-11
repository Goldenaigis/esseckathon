# Notes pour Claude Code

Prototype de hackathon : détection de fraude bancaire par analyse de réseau, sur données
synthétiques. Quatre briques, quatre équipes. Ce fichier rassemble ce qui n'est pas
déductible du code et ce qui a coûté du temps à découvrir. Tout ce qui suit a été vérifié
le 11/10/2026.

## Arborescence, et le piège de nommage

```
esseckathon/                      <- racine du dépôt, à ouvrir dans l'éditeur
  esseckathon/fraudnet/           <- module 1 : génération de données (le double nom est voulu)
  esseckathon/blockchain/         <- L1 Avalanche, contrats, client Python
  module2/                        <- cartographie de graphe, FastAPI + Sigma.js
  module3/                        <- pipeline ML
```

Le dossier parent du dépôt contient aussi un `data/`, un `ml/` et un `notebooks/` qui ne
font pas partie du projet : c'est une ancienne copie de travail du module 3. Un clone
`esseckathon-v2` traîne également à côté, figé plusieurs commits en arrière. Ne pas les
confondre avec le dépôt.

## Environnement

Machine de référence : Windows 11, Git Bash, Python 3.14.2 dans
`C:/Users/mariu/AppData/Local/Python/pythoncore-3.14-64/python.exe`.

Trois choses à savoir avant la première commande :

- **`python` et `python3` nus ne marchent pas** : ce sont les raccourcis Microsoft Store,
  qui existent dans le PATH et sortent en code 49. Toujours le chemin complet. `run.sh`
  détecte l'interpréteur et écarte ces raccourcis ; ailleurs, c'est à la main.
- **Exporter `PYTHONUTF8=1` et `PYTHONIOENCODING=utf-8`** : les scripts impriment des
  accents, la console est en cp1252.
- **`module3/ml/features/build.py` se termine en code 1 environ une fois sur trois**, sans
  message ni traceback, quand sa sortie va directement au terminal. Avec redirection vers
  un fichier, il passe systématiquement. Cause non identifiée, probablement un verrou
  OneDrive sur `module3/data/processed/`. Lancer
  `python ml/features/build.py > /tmp/build.log 2>&1`.

Déjà installé côté Python : numpy, pandas, scikit-learn, pyarrow, joblib, pytest,
networkx, fastapi, uvicorn, httpx. `shap` et `lightgbm` sont absents, le module 3 a un
repli prévu (`explainer.backend == "ecart"`).

**Node et npm ne sont pas installés**, donc la partie blockchain ne peut pas tourner telle
quelle : ni `hardhat compile`, ni `npm test`, ni le client Python qui lit les ABI
produites par la compilation. WSL2 Ubuntu est installé et opérationnel, c'est la voie
documentée dans `esseckathon/blockchain/README.md`, section Windows.

## Interdits

**Ne jamais régénérer `esseckathon/fraudnet/data/`.** L'état de la blockchain (146 533
virements rejoués) en dépend, et il faut une heure pour le reconstruire. Pour tester le
générateur, utiliser `--out /tmp/quelquechose`.

**Ne pas modifier `esseckathon/fraudnet/generator/`** sans raison forte. Le jeu versionné
est reproductible byte-à-byte à graine fixée, et c'est une propriété qu'on perd au premier
changement. Vérifié : 7 fichiers sur 8 identiques à la régénération, le huitième diffère
d'un caractère à cause d'un changement de sommation des flottants entre Python 3.11 et
3.12.

**Aucune colonne `gt_` ou `sim_`, ni `age`, `age_band`, `birth_date`, ne doit devenir une
variable de modèle.** Le garde-fou est `fraudnet.shared.schema.assert_no_leakage`, à
appeler avant chaque `fit`. Il ne teste que des noms exacts : une variable dérivée et
renommée passe au travers, c'est exactement comment `src_owner_age` et `dst_owner_age`
s'étaient glissés dans le modèle.

**Le périmètre scoré est `instrument == "credit_transfer"`, jamais `tx_type`.** `tx_type`
est la finalité économique (loyer, salaire, don), `instrument` est le moyen de paiement.
Filtrer sur `tx_type` écarte 71 % des faux amis légitimes et rend le F1 flatteur et faux.
Les lignes `card` et `direct_debit` restent dans la matrice comme historique
comportemental, sans être ni entraînées ni évaluées.

## Lancer chaque brique

Toujours depuis la racine du dépôt, avec `PY` pointant sur l'interpréteur complet.

```bash
# Module 1, depuis esseckathon/
"$PY" -m fraudnet.generator.validate --data fraudnet/data     # 29 contrôles
"$PY" -m fraudnet.analysis.consortium --data fraudnet/data
"$PY" -m fraudnet.analysis.hub_scores  --data fraudnet/data

# Module 3, depuis module3/
"$PY" -m pytest ml/tests -q
"$PY" ml/features/build.py > /tmp/build.log 2>&1   # 50 s, redirection obligatoire
"$PY" ml/train.py && "$PY" ml/evaluate.py && "$PY" ml/score.py

# Module 2, depuis module2/
"$PY" -m backend.module1_data.fixtures --size medium
DATA_SOURCE=m1 "$PY" -m uvicorn backend.app:app --port 8000
```

`DATA_SOURCE` vaut `auto`, `m1` (les vrais CSV) ou `sqlite` (la base jouet). Sur la source
`m1`, `app.py` charge automatiquement `module3/ml/artifacts/account_scores.json` pour
colorer la carte, et l'expose dans `/api/meta` sous `score_source`.

Les sorties lourdes (`features.parquet`, les `.joblib`, `scores.csv`, `bank.db`) sont
exclues du dépôt et se régénèrent. Les artefacts JSON du module 3 sont versionnés : après
une régénération, `git diff` ne doit montrer que des champs de chronométrage. Toute autre
divergence est une régression.

## Chiffres de référence

À comparer après toute modification. Mesurés le 11/10/2026 sur le jeu versionné.

| Brique | Attendu |
|---|---|
| Module 1 | 29/29 contrôles ; 151 770 transactions, 7 060 comptes |
| Module 1, consortium | 49 scénarios ; 10,2 % puis 83,8 % puis 41,5 % ; 1 316 715 € ; 4,1x |
| Module 1, hub_scores | 500 comptes, 25 signalés au seuil 80, 100 % de précision, 46,3 % de rappel, 0/42 faux amis |
| Module 3 | 13 tests ; 38 variables ; 2 270 fraudes (1,50 %) |
| Module 3, variante `reseau` | PR-AUC 0,961, F1 0,887, rappel 0,861, précision 0,913, leurres 4,75 % |
| Module 3, `rf_control` | PR-AUC 0,965, F1 0,894 |
| Module 2, source m1 | 7 060 nœuds, 77 355 arêtes, payload 7,88 Mo en moins de 30 ms, démarrage 10 s |
| Blockchain | 11 tests Hardhat, 146 533 virements rejouables, demo-scenario 33/38 bloqués |

Baseline à battre, module 3 : F1 0,229 pour la meilleure règle naïve, 0,140 pour le
meilleur seuil de montant possible. Utiliser la PR-AUC, pas l'accuracy : à 1 fraude pour
22, prédire toujours « légitime » donne 95,7 % d'accuracy.

## Points ouverts, à ne pas découvrir en démo

**Le F1 du module 3 est porté à 80 % par un artefact du générateur.**
`dst_account_age_days` seule donne un F1 de 0,760, et la règle brute « destinataire ouvert
depuis moins de 60 jours » donne 0,786 avec 95,7 % de précision, parce que `_mule_account`
ouvre les comptes mules avec une ancienneté tirée entre 2 et 40 jours. En retirant cette
variable, le gain du bloc réseau passe de +0,067 à +0,156 de PR-AUC : la démonstration
honnête est plus forte que la flatteuse. La mesure complète est en commentaire dans
`module3/ml/features/blocks.py`.

**Deux des cinq typologies annoncées par le module 2 ne sont pas calculées sur les vraies
données.** En mode `fast`, actif dès 1 500 nœuds donc toujours sur les CSV de M1,
`betweenness` vaut 0 et `in_cycle` vaut False pour les 7 060 comptes. `simple_cycles` ne
termine pas en 60 s sur ce graphe. Le cycle financier et le rôle de pont restent à écrire,
probablement par une détection à la demande sur un sous-graphe.

**Le rappel de la classification des rôles est de 9 %** sur les vraies données : 27 comptes
détectés sur 306 fraudeurs ou mules. La précision est de 27/27, le rappel est faible.

**`pay()` dans `EURToken.sol` est ouvert à tout détenteur d'EURF**, avec un `txRef` et un
`originalTs` arbitraires, et `cmd_export` ne déduplique pas sur `tx_id`. C'est l'angle mort
de la thèse « la chaîne est la source de vérité ». Et `isFlagged` renvoie le maximum des
scores sans quorum ni expiration : une seule banque suffit à geler un bénéficiaire chez
les 23 autres. Corriger impose un redéploiement et un rejeu complet.

**L'affirmation « export on-chain identique au CSV, 0 différence » du README blockchain
n'est produite par aucun code.** Il n'existe ni sous-commande `verify` ni script de diff.
Soit on écrit les quinze lignes qui la justifient, soit on retire la phrase du pitch.

**Aucun chiffre des README n'est vérifié automatiquement.** Plusieurs étaient périmés
d'une génération du jeu de données avant l'audit. Tout revérifier après chaque
régénération.

**`alerts.json` est majoritairement in-sample** : 460 des 600 alertes sont des lignes
`train`. Le champ `split` est présent dans chaque fiche, le module 4 doit filtrer s'il veut
montrer des alertes qui prouvent quelque chose.

## Travailler sur ce dépôt

Une branche par ensemble cohérent de fonctionnalités, créée depuis un `main` à jour, puis
une pull request. Ne pas committer directement sur `main`.

```bash
git switch main && git pull
git switch -c feat/ma-feature
# travail, commits par petits bouts
git pull origin main          # intégrer ce que les autres ont poussé
git push -u origin feat/ma-feature
```

Le contrat de données entre les quatre modules est dans
`esseckathon/fraudnet/shared/schema.py` et documenté dans `module2/docs/DATA_CONTRACT.md`.
Ne pas réécrire un nom de colonne en dur ailleurs, et prévenir les quatre équipes avant de
modifier le contrat.
