# Fangzha — Defense Sheet

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
souvent vers l'étranger, avant que la victime ne réalise l'arnaque. On ne cible 
que les transactions victime/collecteur. Cible : banques partenaires souhaitant
détecter tôt et geler avant évasion des fonds.

## 2. NIST CSF 2.0 functions covered

| Fonction | Couverture par le système |
|---|---|
| **Identify (ID)** | Cartographie de l'exposition : comptes, flux, communautés, comptes-ponts ; inventaire des typologies de fraude. |
| **Detect (DE)** | Cœur du système. Scoring par transaction, score agrégé par compte, détection d'anomalies de réseau et de rupture comportementale ; alertes continues. |
| **Respond (RS)** | Alertes explicables (motif, facteurs, comptes liés) orientant l'analyste vers le gel du compte et l'avertissement des victimes. |

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
| **Time to respond** | alerte générée immédiatement ; action humaine (gel) = minutes vs a minima quelques dizaines de minutes d'évasion observées sans système |

## 5. Known limitations

- **Données synthétiques** : performances à recalibrer sur données réelles ;
  
- **Évasion adverse** : un fraudeur imitant un commerce légitime (faux salaires,
  prestations fictives) reste un angle mort partiel ; les leurres montrent déjà
  des quasi-faux-positifs.
