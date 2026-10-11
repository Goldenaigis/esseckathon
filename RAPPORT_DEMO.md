# Rapport — réintégration des 3 fonctionnalités de démo (Module 2)

Réintégration des 3 fonctionnalités de démonstration par-dessus la version de M2
issue de l'audit mergé dans `main`, sans écraser les corrections de l'audit.
Branche de travail : `module2-demo`. **Aucun commit, aucun push** (laissé dans le
working tree pour validation).

## Périmètre respecté

- Modifications strictement limitées à `module2/`.
- Aucun fichier de M1 (`esseckathon/`, `fraudnet/`) ni de M3 (`module3/`) touché
  (vérifié via `git status`).
- Lecture seule des artefacts M3 (`module3/ml/artifacts/`).

## Ce qui a été réintégré

### 1. Bouton « ▶ Démo » — simulation « arnaque à l'instant T »
- **Backend** : endpoint `GET /api/demo` renvoyant `build_demo(state.graph,
  state.scores, state.alerts)` (fichier `demo_scenario.py` déjà en place).
- **Front** : bouton `▶ Démo` dans l'en-tête, overlay modale deux colonnes
  « 🔴 Sans notre système » / « 🟢 Avec notre système », bouton « Lancer la
  simulation » qui anime deux compteurs de temps (sans système = l'argent
  s'évapore vers `hours_until_exit`, perte totale ; avec système = alerte à
  T+`detection_minutes`, `salvageable` sauvé), verdict chiffré, bouton « Voir le
  compte dans la carte » → `selectNode(hub)`.
- **Récit** (français) : fausse voix/vidéo IA, N victimes virent des sommes
  modérées (sous les seuils de vérification bancaire — **pas** de montant médian
  par victime, seulement le total), fonds renvoyés à l'étranger. Disclaimer
  « Données synthétiques · une alerte n'est pas une preuve de fraude. »

### 2. Mode « 🧪 Test IA » — rejeu temporel sur le split test
- **Backend** : `state.test_timeline` chargé via `load_test_timeline()` quand
  `score_source == 'm3'` ; endpoint `GET /api/test-timeline` renvoyant
  `{available, n_alerts, t_min, t_max, alerts[]}` (alertes `split=test` triées
  par `ts`, chacune : `account` (=dst), `score`, `ts`, `pattern`).
- **Front** : bouton `🧪 Test IA` qui bascule un mode où le graphe n'affiche QUE
  les comptes des alertes test (gris neutres au départ) ; bandeau avec bouton
  « Rejouer » qui avance le temps et « allume » en rouge chaque compte à la date
  réelle de son alerte ; compteur « X/N détectés » + horodatage ; révélation par
  petits lots (~10 s au total) ; sortie propre (« Quitter »). Le `nodeReducer`
  Sigma gère ce mode (test révélé = rouge, test non révélé = gris, autres =
  caché), et le `edgeReducer` masque toutes les arêtes.
- **Non-superposition** : ouvrir la démo ferme le mode Test IA et inversement ;
  la liste des comptes à risque se ferme aussi à l'ouverture de l'un ou l'autre.

### 3. Liste « Comptes à risque » SANS plafond
- `renderRiskList()` n'a plus de `slice(0, 500)` ni de message « … N de plus ».
  Tous les comptes au-dessus du seuil sont affichés, en **rendu progressif par
  lots** (`RL_BATCH = 300` lignes, lot suivant chargé au scroll) pour ne pas
  figer le navigateur, avec un **clic délégué** (un seul écouteur sur `#rl-items`).

### Bonus réintégré : fiche d'alerte M3 au clic
- Endpoint `GET /api/account/{id}/alert` (404 si pas d'alerte / M3 inactif).
- Affichage dans le panneau de détail (`renderAccountAlert`) : pattern,
  principaux facteurs (`top_factors`), comptes liés (`related_accounts`)
  cliquables (navigation).

## Adaptations faites vs l'audit

- **Structure du `state` (tuple assigné d'un coup)** : ajout propre de
  `self.alerts` et `self.test_timeline` dans le même tuple de publication atomique
  de `_State.reload()`, sans changer la logique existante.
- **Chargement des scores M3 non dupliqué** : l'audit lit les scores dans
  `risk.py` (`load_m3_scores`). De `load_m3.py` on n'utilise QUE
  `load_alerts_by_account` (fiche d'alerte) et `load_test_timeline` (mode Test
  IA). `load_m3.py` détecte le dossier `module3/ml/artifacts/` par remontée +
  repli (comme `risk.py` avec `_REPO_ROOT`).
- **Alertes chargées uniquement quand `score_source == 'm3'`** (cohérent avec le
  branchement M3 de l'audit ; sinon `{}` et `[]`, on n'invente rien).
- **Champs de `demo_scenario.py` vérifiés** contre `load_m1_csv.py` actuel :
  `scenario_id` et `timestamp`/`amount` sur les arêtes, `country`/`first_name`/
  `last_name`/`owner_name`/`opened_date` sur les nœuds — tous présents, aucune
  adaptation nécessaire.
- Front : adaptation au `graph-sigma.js` actuel (objet `state`, reducers Sigma,
  `selectNode`, `showPanel`, `window.__fg`) sans copier l'ancienne base.

## Points de vérification passés

- `node --check module2/frontend/js/graph-sigma.js` → OK.
- Backend testé via `fastapi.testclient.TestClient` (démarrage réel de l'app ASGI) :
  - `GET /api/meta` → `score_source == "m3"` (7060 comptes).
  - `GET /api/demo` → `available: true`, `hub == ACC_006771`, `hub_score == 100`,
    28 victimes, total 59 695,91 €, `0 <= salvage_ratio <= 1`.
  - `GET /api/test-timeline` → `available: true`, **111** alertes, triées par `ts`.
  - `GET /api/account/ACC_006771/alert` → 200 (pattern + 12 comptes liés) ;
    compte inconnu → 404.
  - `GET /` → 200 (HTML) ; `/css/webgl.css` et `/js/graph-sigma.js` servis ;
    `#demo-btn` et `#testai-btn` présents dans le HTML servi.
- Données de validation confirmées sur les vraies données M1/M3 : 7052 comptes
  scorés, **301** à risque ≥ 50, hub démo `ACC_006771` score 100, **111** alertes
  `split=test`.
- `git status` : seuls des fichiers `module2/` modifiés (+ ce rapport à la racine).

## Points restant fragiles / à noter

- **`run.sh` exige Python ≥ 3.10** mais l'environnement a Python 3.9. Le serveur
  a donc été lancé/validé directement via `python3 -m uvicorn` / `TestClient`
  (comme indiqué par l'orchestrateur). `run.sh` n'a pas été modifié (hors
  périmètre de la demande).
- **Validation front = statique** (`node --check` + présence des éléments dans le
  HTML servi). Le rendu WebGL Sigma lui-même n'a pas été exécuté dans un
  navigateur ; la logique DOM/anim repose sur les hooks `window.__fg`.
- **`salvage_ratio == 1.0`** sur le scénario `SCN_001` : les sorties réelles
  (`t_first_exit` ~17 h après la 1re entrée) tombent toutes après l'alerte
  T+6 min, donc rien n'est encore sorti au moment de l'alerte → on sauve 100 %.
  C'est le reflet honnête des vraies dates du scénario, pas une valeur forcée.
- Les deux fichiers backend (`demo_scenario.py`, `load_m3.py`) étaient déjà
  pré-placés et stagés ; ils n'ont pas été recréés, seulement câblés.
