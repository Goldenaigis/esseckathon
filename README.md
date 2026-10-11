# FraudGraph — guide de l'utilisateur

FraudGraph est un outil pour **repérer des réseaux de fraude et de blanchiment**
dans les mouvements d'argent entre comptes bancaires.

L'idée : un virement, vu tout seul, a l'air normal. Mais quand on regarde **le
réseau** — qui envoie à qui, quand, combien — les montages apparaissent : des
dizaines de victimes qui versent sur un même compte, de l'argent qui rebondit de
compte en compte, des allers-retours en boucle…

FraudGraph affiche ce réseau sous forme de **carte** : chaque **compte** est un
point, chaque **virement** une flèche. Une **intelligence artificielle** donne à
chaque compte un **score de risque** (de 0 à 100) qui colore la carte, et explique
pourquoi un compte est signalé.

> Les données sont **synthétiques** (fictives). Un signalement est une **aide à la
> décision**, pas une preuve de fraude.

---

## Démarrer

Il vous faut **Python 3.10 ou plus récent** et le navigateur **Firefox**.

```bash
cd module2
python3 -m venv .venv              # la 1re fois seulement
source .venv/bin/activate
pip install -r requirements.txt    # la 1re fois seulement
./run.sh
```

Ouvrez ensuite **http://127.0.0.1:8000** dans Firefox.

<details>
<summary>Vous êtes sous NixOS ?</summary>

```bash
nix-shell -p python311 python311Packages.pip python311Packages.virtualenv
cd module2
source .venv/bin/activate
./run.sh
```
Relancez le `nix-shell` à chaque réouverture de terminal.
</details>

Au premier affichage, l'outil charge le réseau (quelques secondes) : vous voyez un
nuage de points colorés. C'est parti.

---

## Ce que vous pouvez faire

### 🎨 Lire la carte en un coup d'œil

- **Un point = un compte.** Sa **couleur dit son niveau de risque** :
  - 🔴 **rouge** = risque élevé
  - 🟡 **jaune** = risque moyen
  - 🟢 **vert** = risque faible
- **Une flèche = un virement**, du compte émetteur vers le compte receveur. Plus
  la flèche est épaisse, plus le montant est gros.
- Les comptes se regroupent naturellement en **amas** : ça fait ressortir les
  groupes qui s'échangent beaucoup d'argent.

Au départ, la carte ne montre que les **comptes à risque**, pour rester lisible.

### 🔍 Examiner un compte

**Cliquez** sur un point. La carte **se concentre sur ce compte** : vous ne voyez
plus que lui et les comptes avec qui il a échangé de l'argent. Un **panneau**
s'ouvre à droite avec :
- le **titulaire** (nom et prénom, ou nom de l'entreprise) ;
- son **score de risque** ;
- son pays, le nombre de virements reçus et envoyés, ses partenaires ;
- s'il est signalé : **l'explication de l'IA** — le type de montage détecté, les
  **raisons** du signalement (en français), et les **comptes complices** (sur
  lesquels vous pouvez cliquer pour continuer l'enquête).

Astuce : **survolez une flèche** pour voir le **montant** du virement.

Pour revenir à la vue d'ensemble : appuyez sur **Retour arrière** (Backspace), ou
le **×** du panneau.

> Bon à savoir : un compte en rouge n'est pas forcément « coupable » — ça veut
> dire qu'il a reçu au moins un virement très suspect. Le panneau vous dit lequel
> et pourquoi.

### 🔎 Chercher quelqu'un par son nom

Tapez un **nom, un prénom ou un numéro de compte** dans la barre de recherche en
haut. La liste des correspondances apparaît ; cliquez sur l'une d'elles pour aller
directement sur ce compte.

### ⚠️ Voir la liste des comptes à risque

Le bouton **« Comptes à risque »** ouvre la liste de **tous** les comptes signalés,
classés du plus risqué au moins risqué. Vous pouvez choisir le seuil (risque élevé
ou moyen). Cliquez sur une ligne pour vous rendre sur le compte dans la carte.

### 🎚️ Filtrer par niveau de risque

Le curseur **« Risque min »** cache les comptes en dessous d'un certain score.
Pratique quand vous examinez une mule : montez le curseur pour ne garder, autour
d'elle, que les **autres comptes à risque** — vous isolez ainsi l'ossature du
réseau criminel.

### 🌐 Tout afficher

Cochez **« Afficher tous les comptes »** pour voir **l'intégralité du réseau** (y
compris les comptes normaux), pas seulement ceux à risque.

### ⏳ Remonter le temps

En bas, une **réglette à deux curseurs** vous laisse choisir une **période**.
Glissez les curseurs pour ne garder que les virements d'un intervalle de dates ;
le bouton **▶** fait défiler cette fenêtre dans le temps. Vous voyez ainsi comment
un réseau se forme, jour après jour.

Le menu **« Période »** propose trois raccourcis :
- **Tout** — toute la durée disponible ;
- **Entraînement** — la période sur laquelle l'IA a appris ;
- **Test** — une période que l'IA **n'avait jamais vue**, pour vérifier qu'elle
  détecte vraiment (et ne récite pas ce qu'elle a appris).

---

## Les gestes utiles

| Pour… | Faites… |
|---|---|
| Zoomer / dézoomer | la molette de la souris |
| Déplacer la carte | cliquer-glisser sur le fond |
| Ouvrir le détail d'un compte | cliquer sur le point |
| Voir le montant d'un virement | survoler la flèche |
| Revenir à la vue d'ensemble | la touche **Retour arrière** |
| Recadrer la carte | le bouton **⤢ Recadrer** |

---

## Si quelque chose ne va pas

- **La carte reste bloquée au chargement** → ouvrez l'outil dans **Firefox** (ou
  activez l'accélération graphique de votre navigateur).
- **`./run.sh` ne démarre pas** → vérifiez que vous avez **Python 3.10+**
  (`python3 --version`).
- **« Permission denied »** sur `run.sh` → tapez une fois `chmod +x run.sh`.
