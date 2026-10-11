# FraudGraph — Guide d'utilisation (Module 2 : cartographie)

FraudGraph est une **cartographie interactive des flux financiers** destinée à un
analyste anti-fraude. Chaque **compte** est un point (nœud), chaque **transaction**
une flèche orientée (émetteur → destinataire). La couleur d'un compte reflète son
**score de risque** calculé par le modèle d'IA (Module 3).

> Données **synthétiques**. Une alerte est une **aide à la décision**, pas une
> preuve de fraude.

---

## 1. Lancer l'outil

### Prérequis
- **Python ≥ 3.10** (sous NixOS, voir ci-dessous).
- Un navigateur avec **accélération WebGL** — utilisez **Firefox** (le rendu peut
  être très lent sur un navigateur sans accélération GPU).

### Démarrage

```bash
cd module2
python3 -m venv .venv        # 1re fois seulement
source .venv/bin/activate
pip install -r requirements.txt   # 1re fois seulement
./run.sh
```

Puis ouvrez **http://127.0.0.1:8000** dans Firefox.

### Sous NixOS

```bash
nix-shell -p python311 python311Packages.pip python311Packages.virtualenv
cd module2
source .venv/bin/activate         # (après le premier python -m venv .venv)
./run.sh
```

> À chaque redémarrage de la machine, relancez le `nix-shell` : Python n'est
> disponible que dans ce shell. Le dossier `.venv` et les dépendances, eux,
> restent sur le disque.

### Au chargement
Un **journal** détaille les étapes (téléchargement du réseau, construction des
~7 000 comptes et ~77 000 liens, rendu). Sur une machine avec GPU, c'est quasi
instantané. Si le journal signale « Rendu WebGL **logiciel** », changez de
navigateur ou activez l'accélération matérielle.

---

## 2. Lire la carte

- **Un point = un compte.** Sa **couleur = le risque** estimé par le modèle :
  - 🔴 **rouge** : risque élevé (score ≥ 50)
  - 🟡 **jaune** : risque moyen (score ≥ 25)
  - 🟢 **vert** : risque faible
- **Une flèche = une transaction**, de l'émetteur vers le destinataire. Son
  épaisseur reflète le montant.
- Les comptes sont regroupés en **îlots** (communautés de comptes qui transigent
  entre eux), ce qui fait ressortir les structures.

> Par défaut, en vue d'ensemble, seuls les **comptes à risque** sont affichés
> (voir « Afficher tous les comptes » plus bas) pour garder la carte lisible.

---

## 3. Explorer un compte

- **Survol** d'un compte : met en avant son voisinage immédiat.
- **Clic** sur un compte : ouvre le **panneau de détail** (à droite) et **isole
  son réseau** — on ne voit plus que lui et ses partenaires. La caméra se recadre
  automatiquement.
- **Survol d'une flèche** : affiche le **montant** de la transaction.
- **Revenir à la vue générale** : touche **Retour arrière** (Backspace), ou le
  bouton **×** du panneau. *(Cliquer dans le vide ne désélectionne pas, pour
  éviter les fausses manip.)*

### Le panneau de détail contient
- l'**identifiant** du compte (titre) et le **titulaire** (nom/prénom ou raison
  sociale) ;
- le **score de risque** (0–100) et le niveau ;
- pays, type de client, nombre de transactions reçues / émises, nombre de
  partenaires dans la période ;
- la **fiche d'alerte du modèle** si le compte est signalé : le **motif détecté**,
  les **principaux facteurs** (en français), et les **comptes liés** (cliquables
  pour naviguer de proche en proche).

> **À savoir sur le score d'un compte** : le modèle score les *transactions* ; le
> score d'un **compte** est le plus élevé des scores des virements qu'il a reçus.
> Un compte rouge a donc reçu au moins une transaction jugée très risquée — la
> fiche d'alerte indique laquelle et pourquoi.

---

## 4. Rechercher un compte

Champ **« Rechercher un nom, prénom ou ID »** dans l'en-tête :
- tapez un **nom**, un **prénom** (les deux fonctionnent, même partiels) ou un
  **identifiant** (`ACC_…`) ;
- la liste des correspondances s'affiche avec une pastille de couleur selon le
  risque ;
- cliquez un résultat pour **centrer la carte** sur ce compte et ouvrir son détail.

---

## 5. Lister les comptes à risque

Bouton **« ⚠ Comptes à risque »** : ouvre un panneau latéral listant **tous** les
comptes au-dessus d'un seuil, triés par score décroissant.
- Sélecteur de **seuil** : élevé (≥ 50) ou moyen (≥ 25).
- Chaque ligne montre le titulaire, l'ID, le type et le score.
- **Cliquez une ligne** pour centrer la carte sur le compte.

---

## 6. Filtrer par niveau de risque

Curseur **« Risque min »** dans l'en-tête : masque les comptes dont le score est
sous la valeur choisie. Fonctionne aussi **en vue isolée** (quand un compte est
sélectionné) : utile pour ne garder, autour d'une mule, que ses partenaires
eux-mêmes à risque — on isole ainsi le **squelette d'un réseau**.

---

## 7. Afficher tous les comptes

Case **« Afficher tous les comptes »** : désactive le filtrage automatique et
affiche la **totalité des ~7 000 comptes** (galaxie complète). Décochée (défaut),
la vue d'ensemble ne montre que les comptes à risque, pour rester lisible et
rapide.

---

## 8. Voyager dans le temps (frise)

En bas, une **frise temporelle à deux poignées** (fenêtre glissante) :
- faites glisser les deux poignées pour ne garder que les transactions d'une
  **sous-période** ;
- les champs **date de début / fin** bornent la plage ;
- le bouton **▶** fait glisser la fenêtre dans le temps.

Quand un compte est sélectionné, son voisinage se recalcule pour ne montrer que
les **partenaires de la période affichée**.

### Sélecteur « Période »
Menu **« Période »** pour basculer d'un clic entre :
- **Tout** (août → octobre) ;
- **Entraînement** (jusqu'au 25 septembre) — les données sur lesquelles le modèle
  a appris ;
- **Test** (25 septembre → 9 octobre) — des données **jamais vues** par le modèle,
  pour juger honnêtement de sa performance.

---

## 9. Comprendre la couleur : le score vient du modèle (Module 3)

La couleur des comptes reflète la **prédiction du modèle d'IA** (Module 3), pas une
réponse connue d'avance. Le badge d'en-tête indique la source du score
(« Modèle IA ») et sa performance. Le modèle est entraîné sur la période
d'entraînement et évalué sur la période de test (cf. sélecteur « Période »).

---

## Astuces de navigation

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

- **La carte met longtemps / reste figée au chargement** → WebGL n'est pas
  accéléré. Ouvrez dans **Firefox**, ou activez l'accélération matérielle du
  navigateur.
- **`./run.sh` refuse de démarrer** → vérifiez `python3 --version` (≥ 3.10). Sous
  NixOS, utilisez `nix-shell -p python311 …` comme indiqué plus haut.
- **« Permission denied » sur run.sh** → `chmod +x run.sh`.
