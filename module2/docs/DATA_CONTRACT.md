# Contrat de données, interfaces entre modules

Ce document fige les formats échangés. Ne pas le modifier sans prévenir les
4 équipes. Il est le garde-fou contre l'échec classique du hackathon : 4 modules
qui ne s'intègrent pas.

Dernière vérification contre le code et les données réelles : 11/10/2026.

## Conventions communes

| Élément | Convention | Exemple |
|---|---|---|
| ID compte | `ACC_` + 6 chiffres | `ACC_000041` |
| ID transaction | `TX_` + 7 chiffres | `TX_0000123` |
| Score de risque | entier 0..100 | `94` |
| Type client | `individual` \| `business` \| `senior` | |
| Date | ISO `YYYY-MM-DD` | `2026-01-10` |
| Horodatage | ISO `YYYY-MM-DDTHH:MM:SS` | `2026-01-10T14:32:00` |

Le statut de transaction n'a pas de domaine commun. Les fixtures écrivent
`legitimate` / `suspicious` / `confirmed_fraud`, les CSV de M1 écrivent
`completed` / `pending` / `rejected`. Aucun code de M2 ne s'appuie dessus.

Le type `senior` n'existe que dans les fixtures. Sur les CSV de M1, les segments
valent `particulier` / `pro` / `association` et l'âge est dans `persons.csv`
(`age_band`) : `load_m1_csv._customer_type` ne produit donc que `individual` et
`business`.

Anti-fuite de données : `is_fraud`, `scenario_id`, `is_fraudster`, `gt_role`,
`gt_decoy_id` ne sont jamais des features du modèle M3. Ils servent à
l'évaluation et à la coloration de la démo. Dans le graphe NetworkX, la vérité
terrain de M1 est préfixée `truth_` sur les nœuds, et exportée sous `tr` / `td`
dans le payload WebGL.

---

## M1 vers tous : deux formats acceptés

### A. Base SQLite (`data/bank.db`), produite par les fixtures

Table `accounts` : `account_id` (TEXT PK), `bank`, `country` (ISO2),
`opened_date`, `balance` (REAL), `customer_type`, `is_fraudster` (INTEGER,
vérité terrain).

Table `transactions` : `tx_id` (TEXT PK), `src_account`, `dst_account`,
`amount` (REAL), `timestamp` (ISO), `src_country`, `dst_country`, `channel`,
`status`, `is_fraud` (INTEGER), `scenario_id` (TEXT, clé anti-fuite).

`backend/module1_data/fixtures.py` produit cette base. Lu par
`module2_graph/build_graph.py`.

### B. CSV de M1 (`esseckathon/fraudnet/data/`), lus en lecture seule

`module2_graph/load_m1_csv.py` lit `accounts.csv`, `transactions.csv` et
`persons.csv` sans les modifier, et applique ce mapping :

| CSV M1 | Attribut du graphe M2 |
|---|---|
| `accounts.account_id` | id du nœud |
| `accounts.bank_name` | `bank` |
| `accounts.country` | `country` |
| `accounts.opened_at` | `opened_date` |
| `accounts.account_age_days` | `account_age_days` |
| `accounts.balance` | `balance` |
| `accounts.owner_type` | `customer_type` (company et association vers business) |
| `accounts.owner_name` | `owner_name` |
| `persons.first_name` / `last_name` | `first_name` / `last_name` (joints par `owner_id`) |
| `accounts.gt_role` | `truth_role` (normal / victim / fraudster / mule) |
| `transactions.gt_decoy_id` | `truth_is_decoy` (les deux comptes du virement) |
| `transactions.tx_id` | clé de l'arête + `tx_id` |
| `transactions.ts` | `timestamp` |
| `transactions.amount`, `channel`, `status` | idem |
| `transactions.gt_is_fraud` | `is_fraud` |
| `transactions.gt_scenario_id` | `scenario_id` |

Volumes mesurés : 7 060 comptes, 151 770 transactions, 2 270 frauduleuses,
période du 11/08/2026 au 09/10/2026. Les colonnes `gt_*` non listées
(`gt_scenario_type`, `gt_decoy_type`, `gt_split`) ne sont pas importées.

Le split `gt_split` est temporel : `train` jusqu'au 24/09/2026 23:58, `test` à
partir du 25/09/2026 00:09. Le test représente 40 129 transactions, soit 26 %
du total.

---

## M2 vers M3 : features de graphe par compte

`compute_account_features(graph, fast=False, as_of=None)` renvoie
`{ account_id: {...} }`.

| Feature | Sens |
|---|---|
| fan_in / fan_out | nb de transactions entrantes / sortantes |
| distinct_senders / distinct_receivers | nb de comptes distincts |
| in_out_ratio | fan_in / fan_out (vaut fan_in si fan_out = 0) |
| total_in / total_out | montants cumulés |
| degree_centrality | centralité de degré |
| betweenness | centralité d'intermédiarité, 0.0 en mode `fast` |
| in_cycle | appartient à un cycle de blanchiment, toujours False en mode `fast` |
| redistribution_speed_min | délai en minutes entre la dernière réception et le premier renvoi qui la suit, `None` s'il n'y a pas de renvoi après |
| inbound_window_min | étendue en minutes entre le premier et le dernier virement entrant |
| inbound_burst | nb max de virements entrants reçus dans une même fenêtre de 6 h |
| same_amount_inflow | au moins 8 entrées de montants dans un rapport inférieur à 1,5 |
| role | collector / collector_redistributor / smurf_target / relay / cycle_member / normal |

### Fuite d'information future

Par défaut, les features couvrent toute la fenêtre du graphe passé en argument.
Comme le split de M1 est temporel, calculer les features sur le graphe complet
met 26 % de transactions postérieures à la période d'entraînement dans les
features d'entraînement. C'est une fuite.

Filtrer le graphe par split ne suffit pas non plus : les features deviennent
alors dépendantes de la longueur de la fenêtre (45 jours en train, 15 en test),
et un `fan_in` de 30 en train ne vaut plus un `fan_in` de 30 en test.

Le calcul point-in-time s'obtient avec `as_of` :

```python
feats_train = compute_account_features(g, fast=True, as_of="2026-09-24T23:59:59")
feats_test  = compute_account_features(g, fast=True, as_of="2026-10-09T23:59:59")
```

Seules les transactions horodatées à `as_of` ou avant comptent, les nœuds sont
tous conservés. Pour un scoring strictement causal au niveau transaction, il
faut appeler la fonction avec l'horodatage de la transaction visée, ce qui coûte
un recalcul complet par date (environ 5 s sur M1). En pratique, découper en quelques
dates de coupe et affecter chaque transaction à sa coupe précédente suffit.

### Mode `fast`

`fast=True` saute la betweenness et la détection de cycles. Coûts mesurés sur
M1 (7 060 nœuds, 77 355 arêtes agrégées) : betweenness échantillonnée à k=200
en 14 s, et `simple_cycles(length_bound=6)` dépasse 88 000 cycles sans terminer
en 60 s. En mode `fast`, `betweenness` vaut 0.0 et `in_cycle` vaut False pour
tous les comptes. M3 ne doit pas traiter ces deux colonnes comme informatives
quand le flag est actif. `app.py` l'active automatiquement au-delà de
1 500 nœuds.

---

## M3 vers M2 : scores de risque

`{ account_id: int(0..100) }`, écrit dans
`module3/ml/artifacts/account_scores.json`.

`backend/module2_graph/risk.py::load_m3_scores()` charge ce fichier, borne les
valeurs à 0..100 et renvoie `None` si le fichier est absent ou illisible.
`app.py` l'utilise en priorité sur la source `m1`, et retombe sinon sur la
vérité terrain de M1 (démo) ou sur le score heuristique (fixtures). La source
retenue est exposée dans `GET /api/meta` sous `score_source` :
`m3` | `truth_m1` | `heuristic`. Chemin surchargeable par `M3_SCORES`.

L'artefact n'est pas appliqué aux fixtures : elles réutilisent la même
numérotation `ACC_xxxxxx` sans être le même jeu de données.

État vérifié le 11/10/2026 : 7 052 comptes sur les 7 060 de M1, valeurs entières
de 0 à 100, aucune clé inconnue, 297 comptes au-dessus de 50. Les 8 comptes
absents sont laissés à 0.

Seuils de couleur côté front : rouge à partir de 50, jaune à partir de 25, vert
en dessous.

---

## M2 vers M4 : JSON du graphe

| Endpoint | Rôle |
|---|---|
| `GET /api/health` | `{status, n_accounts, n_transactions, n_fraud_transactions}` |
| `GET /api/meta` | `{source, fast, score_source, ...compteurs}` |
| `GET /api/graph/webgl` | graphe complet, payload compact |
| `POST /api/reload` | recharge tout et renvoie les compteurs |

Il n'y a pas d'endpoint par compte. Les endpoints `/api/graph`,
`/api/graph/full`, `/api/account/{id}/graph` et `/api/graph/suspicious` d'une
version antérieure ont été supprimés avec l'export Cytoscape, et renvoient 404.
Un compte inexistant n'a donc pas de code d'erreur dédié : le front travaille
sur le payload complet qu'il a déjà en mémoire.

Payload de `/api/graph/webgl`, clés courtes pour limiter la taille :

```json
{
  "nodes": [{
    "id": "ACC_000041", "x": -346.99, "y": -27.91,
    "s": 94, "r": "collector", "ci": "FR", "ct": "senior",
    "fi": 27, "fo": 0,
    "nm": "Boutique Perrigny SAS", "fn": "Leila", "ln": "Bertrand",
    "tr": "fraudster", "td": false
  }],
  "edges": [{
    "s": "ACC_000005", "t": "ACC_000041", "ts": "2026-01-12T09:14:00",
    "m": 1500.0, "c": 1, "f": 1
  }],
  "meta": {
    "n_nodes": 7060, "n_edges_raw": 151770, "n_edges": 77355,
    "t_min": "2026-08-11T00:19:20", "t_max": "2026-10-09T23:59:45"
  }
}
```

Nœuds : `s` = score de risque, `r` = rôle, `ci` = pays, `ct` = type client,
`fi` / `fo` = fan-in / fan-out, `nm` = raison sociale, `fn` / `ln` = prénom et
nom, `tr` / `td` = vérité terrain de M1 (affichage uniquement). `x` et `y` sont
les positions précalculées par `layout.py`, dans un repère d'environ 840 unités
de côté.

Arêtes : `s` / `t` = source et cible, `ts` = horodatage du premier virement du
couple, `m` = montant cumulé, `c` = nombre de transactions agrégées, `f` = 1 si
au moins une transaction du couple est frauduleuse. Les transactions parallèles
entre deux mêmes comptes sont agrégées : 151 770 transactions donnent
77 355 arêtes.

Taille mesurée sur M1 : 7,88 Mo, dont 6,6 Mo pour les arêtes. Le JSON est
sérialisé une fois au démarrage du serveur et renvoyé depuis le cache, en 30 ms.
