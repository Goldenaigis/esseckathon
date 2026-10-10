# FraudNet — dictionnaire de données

Version du schéma : **1.0.0**. Source unique de vérité : `fraudnet/shared/schema.py`.
Aucun nom de colonne ne doit être réécrit en dur ailleurs dans le projet.

Toutes les données sont **synthétiques**. Aucune information bancaire réelle,
aucun nom de personne ou d'entreprise réel, aucun IBAN valide.

---

## 1. Modèle de données

Les quatre entités demandées (personnes, entreprises, associations, banques)
sont des tables de **titulaires**. Elles ne contiennent pas les virements.

```
persons ─────┐
companies ───┼──> accounts <────── transactions (src_account, dst_account)
associations ┘        │
                    banks
```

Pourquoi : un virement n'appartient pas à une personne, il relie **deux
comptes**. Si on stockait les virements dans chaque table de titulaire, on les
dupliquerait trois fois et ni le graphe du module 2 ni l'apprentissage du
module 3 ne seraient possibles. `accounts` et `transactions` sont les deux
pivots ; les autres tables apportent le contexte du titulaire.

Un titulaire peut détenir plusieurs comptes (courant, épargne, compte
secondaire chez un établissement de paiement étranger). C'est ce qui permet de
générer des mouvements internes légitimes qui ressemblent à du passage de
fonds.

---

## 2. Conventions transverses

| Convention | Signification | Règle d'équipe |
|---|---|---|
| préfixe `gt_` | vérité terrain | **jamais** une variable du modèle |
| préfixe `sim_` | paramètre de simulation qu'une banque ne possède pas | jamais une variable du modèle |
| `SENSITIVE_COLUMNS` | `age`, `age_band`, `birth_date` | exclues des variables pour raison d'équité |

Avant tout `fit`, le module 3 appelle :

```python
from fraudnet.shared.schema import assert_no_leakage
assert_no_leakage(X.columns, "entrainement")   # lève une erreur si fuite
```

Autres conventions :

- horodatages **ISO 8601**, UTC, à la seconde, sans fuseau explicite
- montants en **EUR**, deux décimales, toujours positifs (le sens est porté
  par `src_account` → `dst_account`)
- pays au format **ISO 3166-1 alpha-2**
- identifiants : `ACC_nnnnnn`, `TX_nnnnnnn`, `PER_nnnnnn`, `CMP_nnnnn`,
  `ASO_nnnn`, `BNK_nn` (France) / `EXT_nn` (étranger), `SCN_nnn`, `DEC_nnn`
- `TX_nnnnnnn` est attribué **après tri chronologique** : l'ordre des
  identifiants suit le temps

---

## 3. `transactions.csv` — table centrale

Une ligne = un virement ou un paiement. C'est aussi la **liste d'arêtes** du
graphe du module 2 : aucun fichier supplémentaire n'est nécessaire.

| Colonne | Type | Description |
|---|---|---|
| `tx_id` | str | identifiant, croissant dans le temps |
| `ts` | datetime | horodatage ISO 8601 |
| `src_account` | str → `accounts` | compte émetteur |
| `dst_account` | str → `accounts` | compte destinataire |
| `amount` | float | montant en EUR |
| `currency` | str | toujours `EUR` |
| `src_country` | str | pays du compte émetteur |
| `dst_country` | str | pays du compte destinataire |
| `channel` | enum | `mobile`, `web`, `branch` |
| `status` | enum | `completed` (96,5 %), `pending`, `rejected` |
| `tx_type` | enum | voir ci-dessous |
| `label` | str | libellé saisi par le client, exploitable dans l'interface |
| `gt_is_fraud` | 0/1 | **vérité terrain** |
| `gt_scenario_id` | str | `SCN_nnn` si la transaction appartient à un scénario de fraude |
| `gt_scenario_type` | enum | type du scénario |
| `gt_decoy_id` | str | `DEC_nnn` si la transaction appartient à un faux ami légitime |
| `gt_decoy_type` | enum | type du faux ami |
| `gt_split` | enum | `train` ou `test` |

`tx_type` : `retail`, `utility`, `p2p`, `transfer`, `b2b_invoice`, `salary`,
`savings_transfer`, `rent`, `donation`, `refund`, `remittance`,
`large_purchase`.

**Périmètre scorable.** Une banque ne score pas un paiement par carte avec le
même modèle qu'un virement. Le module 3 doit entraîner et évaluer sur
`tx_type ∈ {transfer, p2p, remittance, savings_transfer}` — environ 32 000
virements légitimes pour 2 200 frauduleux. Les lignes `retail` et `utility`
restent indispensables : elles constituent l'**historique comportemental** qui
permet de dire si un montant est inhabituel pour un émetteur donné.

---

## 4. `accounts.csv`

Attributs **statiques et déclaratifs** uniquement — ce qu'un système bancaire
connaît à l'ouverture du compte.

| Colonne | Type | Description |
|---|---|---|
| `account_id` | str | clé primaire |
| `owner_type` | enum | `person`, `company`, `association` |
| `owner_id` | str | clé étrangère vers la table de titulaires correspondante |
| `owner_name` | str | nom d'affichage, pratique pour l'interface |
| `bank_id` | str → `banks` | banque de rattachement |
| `bank_name` | str | dénomination de la banque |
| `country` | str | pays de domiciliation du compte |
| `iban_masked` | str | IBAN fictif masqué |
| `product` | enum | `courant`, `epargne`, `pro` |
| `segment` | enum | `particulier`, `pro`, `association` |
| `opened_at` | date | **date d'ouverture : la seule source correcte pour l'ancienneté** |
| `account_age_days` | int | ancienneté arrêtée à la fin de la fenêtre, **informatif** |
| `balance` | float | solde en fin de fenêtre, cohérent avec les flux, **informatif** |
| `gt_role` | enum | `normal`, `victim`, `mule`, `fraudster` |
| `gt_scenario_id` | str | scénario auquel le compte participe |

### Pourquoi aucun indicateur comportemental agrégé ici

Le cahier des charges prévoyait des « indicateurs comportementaux agrégés » sur
le compte. Nous les avons **volontairement exclus**. Une colonne comme
« nombre d'émetteurs distincts » calculée sur toute la fenêtre contient de
l'information postérieure à la transaction que l'on cherche à scorer : c'est
une fuite de données, et elle est invisible dans les métriques — le modèle
paraît excellent en test et s'effondre en production.

Le module 2 calcule ces variables **point-in-time** : pour scorer une
transaction à l'instant `t`, il n'utilise que les transactions antérieures à
`t`. `opened_at` et les attributs statiques sont utilisables sans précaution ;
`account_age_days` et `balance` sont là pour le tableau de bord, pas pour le
modèle.

---

## 5. Tables de titulaires

### `persons.csv`

| Colonne | Description |
|---|---|
| `person_id` | clé primaire |
| `first_name`, `last_name` | noms fictifs |
| `birth_date`, `age`, `age_band` | **sensibles**, exclus des variables |
| `csp` | catégorie socio-professionnelle (9 modalités) |
| `employer_id` | → `companies`, vide si sans emploi, étudiant ou retraité |
| `city`, `country` | localisation |
| `declared_monthly_income` | revenu déclaré, cohérent avec la CSP |
| `sim_digital_literacy` | aisance numérique 0–1, **simulation seulement** |
| `gt_role`, `gt_scenario_id` | vérité terrain |

`age` et `sim_digital_literacy` servent à **choisir les victimes** des arnaques
au faux conseiller, pas à les détecter. Un modèle qui s'appuierait sur l'âge
pour prédire la fraude serait discriminatoire : il signalerait les personnes
âgées plutôt que les comportements frauduleux. `csp`, `city` et `country`
restent utilisables mais sont à surveiller (`FAIRNESS_WATCH_COLUMNS`).

### `companies.csv`

`company_id`, `legal_name`, `legal_form` (`SAS`, `SARL`, `SCI`, `ETR`…),
`sector` (14 modalités), `size_band` (`TPE`/`PME`/`ETI`), `n_employees`,
`created_at`, `city`, `country`, `declared_monthly_revenue`, `is_merchant`,
`gt_role`, `gt_scenario_id`.

`is_merchant = 1` : l'entreprise encaisse des paiements de particuliers.
`legal_form = ETR` et `country != FR` : fournisseur ou commerçant étranger.

### `associations.csv`

`association_id`, `association_name`, `cause`, `created_at`, `city`,
`country`, `n_members`, `declared_annual_budget`, `gt_role`,
`gt_scenario_id`.

### `banks.csv`

`bank_id`, `bank_name`, `bic`, `country`, `is_domestic`, `n_accounts`.

8 banques françaises, 16 banques étrangères. Parmi les étrangères, certaines
sont des **établissements de paiement** (LT, MT, CY, LV, BG, EE, AE) et
d'autres des banques de détail (PT, MA, SN, RO, DE, ES, NL, PL, GB). Les deux
catégories reçoivent des flux légitimes **et** frauduleux : le pays de
destination n'est donc pas un raccourci exploitable.

---

## 6. `scenarios.csv` — vérité terrain des fraudes

Une ligne par instance de scénario. Sert à mesurer le **rappel par type de
fraude** et la métrique « alerte levée après combien de victimes ».

| Colonne | Description |
|---|---|
| `scenario_id`, `scenario_type`, `scenario_type_fr` | identification |
| `start_ts`, `end_ts`, `duration_hours` | fenêtre réelle |
| `n_victim_accounts`, `n_mule_accounts`, `n_transactions`, `total_amount` | ampleur |
| `redistributed_ratio` | part des fonds ressortie du compte collecteur |
| `destination_countries` | pays de sortie, séparés par `\|` |
| `gt_split` | `train` ou `test`, **jamais les deux** |
| `params_json` | tous les paramètres tirés au hasard, dont `amount_regime` |
| `description_fr` | résumé en français, réutilisable dans la fiche d'alerte |

### Les 7 scénarios

| Type | Signature | Paramètres randomisés |
|---|---|---|
| `faux_conseiller` | n victimes → 1 compte récent, puis sortie rapide | 8–30 victimes, collecte 6–48 h, sortie 0,3–3 h, 2–4 jambes, 70–95 % ressortis |
| `faux_investissement` | victimes aisées → 2–5 collecteurs → consolidation | 10–35 victimes, étalement 3–15 j, 3 plages de montants |
| `compte_collecteur` | mule **recrutée parmi des clients existants** | 15–40 émetteurs, collecte 24–72 h, 3–6 sorties |
| `smurfing` | fractionnement sous un palier | palier 990/1 900/2 900/4 900/9 900, 8–60 virements, 4–72 h |
| `chaine_mules` | 3–5 sauts, commission à chaque saut | montant 10–80 k, commission 2–8 %, sauts 0,3–6 h |
| `dormant_reactive` | compte ancien et inactif devenant un hub | dormance 400–2 500 j, 5–20 émetteurs |
| `cycle` | boucle de transferts entre 3–5 comptes | 1–3 tours, décroissance 1–8 % par saut |

### Régime de montant

Chaque instance tire un **régime** qui détermine l'ampleur des virements des
victimes :

| Régime | Poids | Montants | Destination étrangère |
|---|---|---|---|
| `discret` | 46 % | 80–900 € (médiane ~350 €) | 35 % |
| `standard` | 39 % | 250–3 000 € | 76 % |
| `eleve` | 15 % | 800–9 500 € | 88 % |

Le régime `discret` est la raison d'être du projet : **61 % de ses
transactions frauduleuses ont un montant inférieur au 95ᵉ centile habituel de
l'émetteur et une destination domestique**. Aucune analyse transaction par
transaction ne peut les signaler. Seule la convergence des flux les trahit.

---

## 7. `decoys.csv` — faux amis légitimes

C'est la table la plus importante du jeu de données.

Sans elle, un modèle apprend « convergence de flux = fraude », affiche un F1
flatteur, et un jury averti démonte la démonstration en une question. Chaque
faux ami **reproduit volontairement** une signature de fraude avec
`gt_is_fraud = 0`.

| Colonne | Description |
|---|---|
| `decoy_id`, `decoy_type`, `decoy_type_fr` | identification |
| `start_ts`, `end_ts` | fenêtre |
| `hub_account` | compte au centre de la structure |
| `n_accounts`, `n_transactions`, `total_amount` | ampleur |
| `gt_split` | partition |
| `description_fr` | ce qui se passe réellement |
| `why_looks_fraudulent` | **la signature de fraude imitée** |

| Type | Structure imitée |
|---|---|
| `collecte_association` | fan-in extrême : 120–300 donateurs en 48–120 h. Degré entrant supérieur à toutes les mules du jeu |
| `cagnotte_mariage` | fan-in **puis** fan-out rapide : 28–80 participants, 75–95 % reversés en quelques heures à des prestataires. Signature identique à un compte collecteur |
| `bailleur_multi_loyers` | 12–22 loyers encaissés le même jour |
| `corridor_remise` | 5–12 proches virant vers un même compte étranger en 48 h |
| `vente_vehicule` | gros encaissement d'un inconnu puis réorientation immédiate : ratio de passage ≈ 1 |
| `tresorerie_entrepreneur` | rotations rapides entre comptes du **même** titulaire |
| `paie_entreprise` | fan-out extrême : 35–120 salaires en 75 minutes |

Le module 3 doit mesurer son **taux de faux positifs sur ces instances**
spécifiquement, et le module 4 doit pouvoir en afficher une dans la démo
comme cas correctement non signalé.

---

## 8. Partition train / test et protection anti-fuite

Trois protections cumulées :

1. **Séparation temporelle.** Jours 0–44 en `train`, jours 45–59 en `test`.
   Le système apprend sur le passé et détecte dans des données plus récentes.
2. **Séparation par scénario.** Chaque instance de scénario et chaque faux ami
   est **entièrement** dans une seule partition. C'est garanti à la
   génération, pas filtré après coup. Sans cela, le modèle verrait en
   entraînement d'autres virements du même scénario qu'il doit détecter en
   test, et le rappel serait très surestimé.
3. **Garantie de couverture.** Chaque type de scénario possède au moins 4
   instances et au moins une dans chaque partition, sinon son rappel serait
   impossible à mesurer.

Le module 3 doit en plus garantir le caractère **point-in-time** de toutes les
variables de réseau. C'est la fuite la plus facile à introduire sans s'en
apercevoir.

---

## 9. Ce que le rapport de qualité garantit

`python -m fraudnet.generator.validate` exécute 25 contrôles. Les plus
importants ne portent pas sur l'intégrité mais sur la **non-trivialité** :

**Aucune règle à une variable ne résout le problème.** Sur le jeu de test,
plafond des règles de montant : **F1 = 0,35** (seuil choisi avec la vérité
terrain, donc optimiste). Meilleure règle naïve : « montant ≥ 3 000 € », F1 =
0,33 avec 25 % de précision. C'est la ligne de base que le module 3 doit
dépasser nettement.

**Le signal de graphe est combinatoire.** Sur les 45 comptes collecteurs
frauduleux :

| Règle | Précision | Rappel |
|---|---|---|
| fan-in 24 h ≥ 5 | 9,1 % | 100 % |
| + ratio sortant/entrant ≥ 0,60 | 17,8 % | 91,1 % |
| + compte ouvert depuis ≤ 120 j | 96,0 % | 53,3 % |

Le degré entrant **seul** est inutilisable : les 15 comptes au plus fort
fan-in du jeu sont tous légitimes (collectes d'associations, cagnottes,
bailleurs). Il faut le croiser avec la vitesse de redistribution et
l'ancienneté. C'est exactement la démonstration attendue par la priorité 3 du
projet.

Les 17 comptes collecteurs restants sont des **mules recrutées parmi des
clients existants** : leur compte est ancien, le critère d'ancienneté ne les
attrape pas. Le module 2 doit ajouter un indicateur de rupture
comportementale pour les récupérer.

**Les montants et les pays se recouvrent.** 35 % des virements légitimes
tombent dans l'intervalle interdécile des fraudes. 11,9 % des virements
légitimes partent à l'étranger contre 28,7 % des frauduleux : un rapport de
2,4× seulement. 6,7 % des virements légitimes visent un établissement de
paiement, parce que de nombreux clients détiennent légitimement un compte de
néobanque sous licence lituanienne ou maltaise.

---

## 10. Limites à présenter honnêtement au jury

- Données **entièrement synthétiques** : le modèle peut avoir appris des
  régularités du générateur plutôt que de la fraude. C'est pour cela que les
  paramètres sont randomisés par instance et que les faux amis existent, mais
  le risque ne disparaît pas.
- Taux de fraude de **1,5 %**, contre un ordre de grandeur réel plutôt proche
  de 0,1 %. Nécessaire pour disposer d'assez d'exemples d'apprentissage ;
  à dire explicitement.
- Les seuils de risque devront être **recalibrés** sur données réelles.
- Pas de dérive temporelle testée au-delà de 60 jours.
- L'étiquetage est parfait, ce qui n'arrive jamais : en réalité une partie des
  fraudes n'est jamais signalée par les victimes.
- En production, les variables de réseau devraient être calculées en flux
  continu, pas par recalcul complet.
