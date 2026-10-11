# FraudGraph — détection de fraude bancaire par analyse de réseau et IA

FraudGraph aide un analyste anti-fraude à **repérer des réseaux de blanchiment et
d'arnaque** dans les flux bancaires. L'idée : une transaction prise isolément
paraît banale, mais **le réseau** (qui envoie à qui, quand, combien) révèle les
montages — comptes collecteurs, mules, chaînes, cycles.

L'outil central est une **cartographie interactive** : chaque **compte** est un
point, chaque **transaction** une flèche. Un **modèle d'IA** attribue à chaque
compte un **score de risque** qui colore la carte, et explique ses alertes.

> Données **synthétiques**. Une alerte est une **aide à la décision**, pas une
> preuve de fraude.

---

## Architecture (vue d'ensemble)

Le projet est organisé en modules qui se chaînent :

```
Module 1 (données)  →  Module 3 (modèle IA)  →  Module 2 (cartographie)
 comptes & virements    score de risque /         visualisation + exploration
 synthétiques           alertes explicables        (l'outil que vous utilisez)
```

- **Module 1** — jeu de données bancaire synthétique (comptes, transactions,
  scénarios de fraude). Dossier `esseckathon/fraudnet/`.
- **Module 3** — modèle d'apprentissage qui score les transactions et agrège un
  **score par compte**, avec des alertes motivées. Dossier `module3/`.
- **Module 2** — la **cartographie web** (ce README décrit son usage). Dossier
  `module2/`.

Un volet blockchain (`esseckathon/blockchain/`) rejoue les flux pour l'intégrité.

---

## Démarrage rapide

### Prérequis
- **Python ≥ 3.10**
- Un navigateur avec **accélération WebGL** → utilisez **Firefox** (sans GPU, le
  rendu peut être très lent).

### Lancer l'outil

```bash
cd module2
python3 -m venv .venv              # 1re fois seulement
source .venv/bin/activate
pip install -r requirements.txt    # 1re fois seulement
./run.sh
```

Puis ouvrez **http://127.0.0.1:8000** dans Firefox.

### Sous NixOS

```bash
nix-shell -p python311 python311Packages.pip python311Packages.virtualenv
cd module2
source .venv/bin/activate          # après le premier `python -m venv .venv`
./run.sh
```

> À chaque réouverture de terminal, relancez le `nix-shell` : Python n'est
> disponible que dans ce shell. Le dossier `.venv` et les dépendances restent sur
> le disque.

### Au chargement
Un **journal** détaille les étapes (téléchargement du réseau, construction des
~7 000 comptes et ~77 000 liens, rendu). Avec un GPU c'est quasi instantané. Si le
journal signale « Rendu WebGL **logiciel** », changez de navigateur ou activez
l'accélération matérielle.

---

## Utiliser la cartographie

### Lire la carte
- **Un point = un compte** ; sa **couleur = le risque** estimé par le modèle :
  - 🔴 **rouge** : risque élevé (score ≥ 50)
  - 🟡 **jaune** : risque moyen (score ≥ 25)
  - 🟢 **vert** : risque faible
- **Une flèche = une transaction** (émetteur → destinataire) ; son épaisseur
  reflète le montant.
- Les comptes sont regroupés en **îlots** (communautés qui transigent entre
  elles), ce qui fait ressortir les structures.
- Par défaut, la vue d'ensemble n'affiche que les **comptes à risque**, pour
  rester lisible (voir « Afficher tous les comptes »).

### Explorer un compte
- **Survol** : met en avant son voisinage immédiat.
- **Clic** : ouvre le **panneau de détail** et **isole son réseau** (lui + ses
  partenaires) ; la caméra se recadre.
- **Survol d'une flèche** : affiche le **montant** de la transaction.
- **Revenir à la vue générale** : touche **Retour arrière** (Backspace) ou le
  bouton **×**. *(Cliquer dans le vide ne désélectionne pas, pour éviter les
  fausses manip.)*

Le **panneau de détail** montre : identifiant et titulaire (nom/prénom ou raison
sociale), score de risque et niveau, pays, type de client, nombre de transactions
reçues/émises, partenaires sur la période, et — si le compte est signalé — la
**fiche d'alerte du modèle** : motif détecté, principaux facteurs (en français),
comptes liés cliquables.

> **Score d'un compte** : le modèle score les *transactions* ; le score d'un
> *compte* est le plus élevé des scores des virements qu'il a reçus. Un compte
> rouge a donc reçu au moins une transaction jugée très risquée — la fiche
> d'alerte indique laquelle et pourquoi.

### Rechercher un compte
Champ **« Rechercher un nom, prénom ou ID »** : tapez un nom, un prénom (même
partiels) ou un identifiant `ACC_…`. Cliquez un résultat pour centrer la carte et
ouvrir son détail.

### Lister les comptes à risque
Bouton **« ⚠ Comptes à risque »** : panneau listant **tous** les comptes au-dessus
d'un seuil (élevé ≥ 50 ou moyen ≥ 25), triés par score. Cliquez une ligne pour
centrer la carte sur le compte.

### Filtrer par niveau de risque
Curseur **« Risque min »** : masque les comptes sous le seuil choisi. Fonctionne
aussi **en vue isolée** : autour d'une mule, on ne garde que les partenaires
eux-mêmes à risque → on isole le **squelette d'un réseau**.

### Afficher tous les comptes
Case **« Afficher tous les comptes »** : affiche la **totalité des ~7 000 comptes**
(galaxie complète). Décochée (défaut), seuls les comptes à risque sont visibles en
vue d'ensemble.

### Voyager dans le temps
Frise **à deux poignées** (fenêtre glissante) en bas : glissez les poignées pour
ne garder qu'une **sous-période** ; les champs date bornent la plage ; le bouton
**▶** fait glisser la fenêtre dans le temps. Quand un compte est sélectionné, son
voisinage se recalcule pour la période affichée.

Menu **« Période »** pour basculer entre :
- **Tout** (août → octobre) ;
- **Entraînement** (→ 25 septembre) — données sur lesquelles le modèle a appris ;
- **Test** (25 septembre → 9 octobre) — données **jamais vues** par le modèle,
  pour juger honnêtement de sa performance.

### Comprendre la couleur
La couleur reflète la **prédiction du modèle d'IA (Module 3)**, pas une réponse
connue d'avance. Le badge d'en-tête indique la source du score et sa performance.

---

## Raccourcis

| Action | Comment |
|---|---|
| Zoomer / dézoomer | molette de la souris |
| Déplacer la carte | clic-glisser sur le fond |
| Détail d'un compte | clic sur le point |
| Montant d'une transaction | survol de la flèche |
| Revenir à la vue générale | **Retour arrière** (Backspace) |
| Recadrer la vue | bouton **⤢ Recadrer** |

---

## Dépannage

- **La carte reste figée au chargement** → WebGL non accéléré : ouvrez dans
  **Firefox** ou activez l'accélération matérielle.
- **`./run.sh` refuse de démarrer** → vérifiez `python3 --version` (≥ 3.10). Sous
  NixOS, passez par `nix-shell -p python311 …` (ci-dessus).
- **« Permission denied » sur run.sh** → `chmod +x run.sh`.

---

## Pour aller plus loin

- Guide d'utilisation détaillé : [`module2/GUIDE_UTILISATION.md`](module2/GUIDE_UTILISATION.md)
- Détail technique du Module 2 : [`module2/README.md`](module2/README.md)
- Contrat de données entre modules : [`module2/docs/DATA_CONTRACT.md`](module2/docs/DATA_CONTRACT.md)
