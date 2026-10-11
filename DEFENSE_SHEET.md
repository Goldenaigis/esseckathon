# FraudGraph — Defense Sheet

**Système** : détection de réseaux de fraude et de blanchiment sur flux
interbancaires par analyse de graphe + modèle d'apprentissage supervisé.
**Données** : synthétiques (7 060 comptes, 151 770 virements, 72 scénarios de
fraude injectés). Un signalement est une aide à la décision, pas une preuve.

---

## 1. Threat scenario addressed

Fraude par ingénierie sociale (faux conseiller, fausse voix/vidéo IA d'un proche,
faux investissement) suivie de **blanchiment en réseau** : des victimes virent
vers un **compte collecteur**, qui redistribue rapidement les fonds à travers des
**mules**, des **chaînes**, du **fractionnement (smurfing)** et des **cycles**,
souvent vers l'étranger, avant que la victime ne réalise l'arnaque. Chaque virement
isolé paraît légitime ; c'est la **structure du réseau** et sa **dynamique
temporelle** qui trahissent le montage. Cible : banques partenaires souhaitant
détecter tôt et geler avant évasion des fonds.

## 2. NIST CSF 2.0 functions covered

| Fonction | Couverture par le système |
|---|---|
| **Identify (ID)** | Cartographie de l'exposition : comptes, flux, communautés, comptes-ponts ; inventaire des typologies de fraude. |
| **Detect (DE)** | Cœur du système. Scoring par transaction, score agrégé par compte, détection d'anomalies de réseau et de rupture comportementale ; alertes continues. |
| **Respond (RS)** | Alertes explicables (motif, facteurs, comptes liés) orientant l'analyste vers le gel du compte et l'avertissement des victimes. |
| **Protect (PR)** | *Partiel* : aide à la décision de gel ; la mise en œuvre (blocage effectif) relève du SI bancaire, hors périmètre. |
| **Recover (RC)** | *Hors périmètre* : la récupération des fonds dépend des procédures bancaires/judiciaires. |
| **Govern (GV)** | *Partiel* : séparation stricte train/test, cloisonnement de la vérité terrain, journalisation ; gouvernance complète à définir côté établissement. |

## 3. ATT&CK / ATLAS / OWASP mapping

- **MITRE ATT&CK (fraude financière, analogie)** : la chaîne détectée correspond à
  *Collection → Exfiltration* appliquée aux fonds (collecte sur un hub,
  redistribution/exfiltration vers comptes étrangers). Le système agit comme
  détection comportementale au niveau « réseau ».
- **MITRE ATLAS (sécurité du modèle IA)** — risques considérés :
  - *Data poisoning* : atténué par un pipeline de génération maîtrisé et un
    contrôle anti-fuite (`assert_no_leakage`) avant entraînement.
  - *Model evasion* (fraudeur qui imite un comportement légitime, « leurres ») :
    partiellement adressé par les variables de réseau + temporelles ; **limite
    connue** (voir §5).
  - *Membership inference / fuite* : variables sensibles (âge, date de naissance)
    exclues ; aucune donnée réelle.
- **OWASP** :
  - *API Security Top 10* : surface = API lecture seule (pas d'écriture, pas
    d'authentifiant), pas d'injection (pas de SQL dynamique côté service),
    exposition de données minimisée (identité affichée à la demande).
  - *OWASP ML Top 10* : ML02 (data poisoning), ML01 (input manipulation/evasion),
    ML06 (ML supply chain) pris en compte via contrôle des artefacts versionnés.

## 4. Metrics achieved

Évaluation **sur le split test** (16 536 virements jamais vus à l'entraînement,
671 fraudes, 990 leurres légitimes), modèle « réseau » :

| Métrique | Valeur |
|---|---|
| **Taux de détection (rappel)** | **86,1 %** |
| **Précision** | **91,3 %** |
| **F1** | **0,89** (baseline règles de montant : 0,14) |
| **Taux de faux positifs** | **0,35 %** |
| PR-AUC / ROC-AUC | 0,96 / 0,99 |
| **Time to detect** | **≈ 0,03 ms / transaction** (scoring quasi temps réel) |
| **Time to respond** | alerte générée immédiatement ; action humaine (gel) = minutes vs **~17 h** d'évasion observées sans système |

**Rappel par typologie** : smurfing, chaînes de mules, cycles **100 %** ; faux
conseiller **98,5 %**, faux investissement **98,3 %** ; **compte collecteur 44 %**,
réactivation de compte dormant **52 %** (voir limites).

## 5. Known limitations

- **Données synthétiques** : performances à recalibrer sur données réelles ;
  pas de garantie de transfert direct en production.
- **Typologies faibles** : rappel bas sur *compte collecteur* (44 %) et *dormant
  réactivé* (52 %) → faux négatifs sur ces montages ; à renforcer (variables de
  rafale/temporelles, rééquilibrage).
- **Évasion adverse** : un fraudeur imitant un commerce légitime (faux salaires,
  prestations fictives) reste un angle mort partiel ; les leurres montrent déjà
  des quasi-faux-positifs.
- **Score par compte = max des virements reçus** : signale le compte, pas la
  responsabilité ; une victime peut apparaître « à risque ».
- **Explicabilité heuristique** : les motifs/facteurs sont des règles de lisibilité,
  à distinguer du score du modèle et de la vérité terrain.
- **Périmètre** : virements uniquement (`credit_transfer`) ; cartes/prélèvements
  servent de contexte, pas de cible. Protect/Recover/Govern non complets.
- **Non déployable en l'état** : prototype hackathon, sans validation sécurité,
  conformité (RGPD, secret bancaire) ni supervision humaine formalisée.
