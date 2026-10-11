/* M2 - Cartographie WebGL façon Obsidian (Sigma.js + graphology).
 *
 * Principes de performance (7 060 nœuds / 95 449 liens sur les vraies données,
 * dont 52 824 virements désagrégés un par un depuis l'arrivée des scores M3) :
 *  - rendu WebGL (Sigma) : la carte graphique dessine, le CPU respire ;
 *  - AUCUN layout navigateur : les positions (x, y) arrivent précalculées du
 *    serveur (backend/module2_graph/layout.py) ;
 *  - timeline = on masque/affiche des liens déjà positionnés, avec les dates
 *    converties en ms UNE fois au chargement (pas de new Date() par image) ;
 *  - focus Obsidian = on joue sur l'opacité (reducers), pas sur la topologie.
 */

const COLORS = { high: "#ff5a5a", mid: "#ffb020", low: "#35d07f", none: "#55607a" };
// seuils de couleur : rouge >= 50, jaune >= 25, vert sinon.
// `hasData` à false = le compte n'a reçu AUCUN virement noté dans la fenêtre
// temporelle courante. Il est alors gris et non vert : vert veut dire « jugé
// peu risqué », gris veut dire « pas de quoi juger sur cette période ».
function riskColor(s, hasData) {
  if (hasData === false) return COLORS.none;
  return s >= 50 ? COLORS.high : s >= 25 ? COLORS.mid : COLORS.low;
}

const state = {
  graph: null,       // graphology
  renderer: null,    // sigma
  fa2: null,         // worker layout
  edgesByTime: [],   // [{key, t}] trié par t (ms epoch, converti une seule fois)
  tMin: null, tMax: null,
  extent: 1000,      // étendue (x et y) du layout serveur, mesurée au chargement
  // Plus aucun filtre de risque sur les nœuds : ni curseur "risque min", ni seuil
  // selon le zoom. Les 7 060 comptes et les 95 449 liens sont tous dessinés, et
  // la seule chose qui masque encore quelque chose est la fenêtre temporelle.
  allEdges: true,    // décocher = revenir au dessin des liens au focus seulement
  includeTrain: false,  // la plage démarre sur la partition de test, voir initControls
  winT0: null, winT1: null,  // fenêtre temporelle courante (ms epoch)
  hovered: null,
  hoveredEdge: null,
  selected: null,
  neighbors: new Set(),
  searchIndex: [],   // [{id, name, score, ct, hay, agg, aggRaw, aggFallback}]
  // Virements notés REÇUS par compte, reconstruits depuis les arêtes au
  // chargement : id -> { r: [scores], m: [montants], t: [ms epoch] }, trois
  // tableaux parallèles. Le serveur ne les envoie plus séparément : chaque
  // virement noté est déjà une arête portant son score et son horodatage, et
  // reconstruire ici garantit que la date utilisée pour agréger est EXACTEMENT
  // celle utilisée pour filtrer la frise (même conversion, même fuseau).
  inbound: new Map(),
  // --- seuil d'alerte sur les virements (fonctionnalité 2) ---
  edgeThreshold: 80,   // 0..100 ; une arête notée r >= seuil passe au rouge
  hotEdges: true,      // garder ces arêtes rouges visibles en permanence
  scoredEdges: [],     // [{key, r, t}] arêtes NOTÉES seulement (r != null)
  nHot: 0,
  // --- agrégateur de score par compte (fonctionnalité 5) ---
  aggMode: "max",      // max | top3 | count | amount | noisyor
  aggAbove: 0,         // nb de comptes au-dessus du seuil selon l'agrégateur
  aggFallbacks: 0,     // nb de comptes sans virement noté reçu (repli score serveur)
  txScores: true,      // meta.tx_scores : scores par transaction disponibles
  tDemoStart: null,    // meta.t_demo_start : début de la partition de test
  nScoredTest: null,   // meta.n_tx_scored_test  : virements notés hors échantillon
  nScoredTrain: null,  // meta.n_tx_scored_train : virements notés in-sample
  accountReq: 0,       // compteur anti-course sur /api/account
  txReq: 0,            // compteur anti-course sur /api/tx
};

const el = id => document.getElementById(id);
// échappement HTML : les noms de titulaires viennent des CSV de M1 et sont
// injectés dans du innerHTML (un "&" ou un "<" casserait le panneau).
const esc = s => String(s ?? "").replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtAmount = a => a == null ? "—" :
  new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(a);
const fmtDate = ts => { const d = new Date(ts); return isNaN(d) ? "—" :
  d.toLocaleString("fr-FR", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit" }); };

/* ---------- Journal de chargement (verbeux) ---------- */
const nextFrame = () => new Promise(r => requestAnimationFrame(() => r()));
const t0 = () => performance.now();
const ms = s => `${(performance.now() - s).toFixed(0)} ms`;

function logLine(html, cls) {
  const log = el("load-log");
  const span = cls ? `<span class="${cls}">${html}</span>` : html;
  log.insertAdjacentHTML("beforeend", span + "\n");
  log.scrollTop = log.scrollHeight;
}
function setHead(txt) { el("loading-txt").textContent = txt; }
function setBar(pct) { el("load-bar-fill").style.width = Math.max(0, Math.min(100, pct)) + "%"; }
const nf = n => n.toLocaleString("fr-FR");

/* Détection du support WebGL + infos GPU (cause fréquente de blocage à l'init Sigma) */
function detectWebGL() {
  try {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2") || c.getContext("webgl") || c.getContext("experimental-webgl");
    if (!gl) return { ok: false, version: "aucun", renderer: "—" };
    const version = (c.getContext("webgl2")) ? "WebGL 2" : "WebGL 1";
    let renderer = "inconnu";
    const dbg = gl.getExtension("WEBGL_debug_renderer_info");
    if (dbg) renderer = gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) || renderer;
    const software = /swiftshader|software|llvmpipe|basic render/i.test(renderer);
    return { ok: true, version, renderer, software };
  } catch (e) {
    return { ok: false, version: "erreur", renderer: String(e) };
  }
}

/* ---------- Chargement + construction du graphe (verbeux) ---------- */
async function load() {
  const started = t0();
  logLine(">> Démarrage de la cartographie WebGL (façon Obsidian)", "dim");
  await nextFrame();

  // 1) Métadonnées serveur
  setHead("Connexion au serveur...");
  logLine(">  Requête <span class='dim'>/api/meta</span>...");
  await nextFrame();
  let meta;
  try {
    meta = await fetch("/api/meta").then(r => r.json());
    logLine(`[OK] Source de données : <span class="num">${meta.source}</span> · `
      + `<span class="num">${nf(meta.n_accounts)}</span> comptes · `
      + `<span class="num">${nf(meta.n_transactions)}</span> transactions · `
      + `<span class="num">${nf(meta.n_fraud_transactions)}</span> frauduleuses (vérité terrain)`, "ok");
  } catch (e) { logLine("[X] Échec de /api/meta : " + e, "warn"); }
  setBar(8); await nextFrame();

  // 2) Téléchargement du graphe
  setHead("Téléchargement du réseau...");
  logLine(">  Requête <span class='dim'>/api/graph/webgl</span> (positions précalculées côté serveur)...");
  await nextFrame();
  const tDl = t0();
  const resp = await fetch("/api/graph/webgl");
  const sizeMo = (+(resp.headers.get("content-length") || 0)) / 1e6;
  const data = await resp.json();
  logLine(`[OK] Payload reçu en ${ms(tDl)}${sizeMo ? ` · <span class="num">${sizeMo.toFixed(1)} Mo</span>` : ""}`, "ok");
  logLine(`  <span class="dim">nœuds=${nf(data.meta.n_nodes)} · liens=${nf(data.meta.n_edges)} `
    + `(sur ${nf(data.meta.n_edges_raw)} transactions brutes)</span>`);
  if (data.meta.n_edges_tx != null || data.meta.n_edges_agg != null) {
    logLine(`  <span class="dim">dont ${nf(data.meta.n_edges_tx || 0)} virements notés un par un `
      + `et ${nf(data.meta.n_edges_agg || 0)} paquets agrégés (non cliquables)</span>`);
  }
  logLine(`  <span class="dim">période : ${fmtDate(data.meta.t_min)} -> ${fmtDate(data.meta.t_max)}</span>`);
  // scores par transaction : sans eux, les agrégateurs n'ont rien à agréger
  state.txScores = data.meta.tx_scores !== false;
  state.tDemoStart = data.meta.t_demo_start || null;
  if (!state.txScores) {
    logLine("[!] meta.tx_scores = false : aucun score par virement. Le seuil d'alerte et les "
      + "agrégateurs retombent sur le score serveur par compte.", "warn");
  }
  // Répartition train/test des virements notés : elle décide de ce que la carte
  // a le droit de montrer par défaut. Les scores des lignes d'entraînement sont
  // in-sample, donc inutilisables comme preuve.
  state.nScoredTest = data.meta.n_tx_scored_test ?? null;
  state.nScoredTrain = data.meta.n_tx_scored_train ?? null;
  if (state.tDemoStart) {
    logLine(`  <span class="dim">début de la partition de test : ${fmtDate(state.tDemoStart)}</span>`);
    if (state.nScoredTest != null && state.nScoredTrain != null) {
      const tot = state.nScoredTest + state.nScoredTrain;
      logLine(`[!] ${nf(state.nScoredTrain)} des ${nf(tot)} virements notés `
        + `(${(100 * state.nScoredTrain / Math.max(tot, 1)).toFixed(1)} %) sont des lignes `
        + `d'ENTRAÎNEMENT : scores in-sample. La carte démarre sur la partition de test `
        + `(${nf(state.nScoredTest)} virements).`, "warn");
    }
  } else {
    logLine("[!] meta.t_demo_start absent : la frise cumulative partira du début des données.", "warn");
  }
  setBar(25); await nextFrame();

  // multi: true — le serveur renvoie les virements notés UN PAR UN, donc plusieurs
  // arêtes peuvent relier la même paire de comptes. En non-multi, graphology
  // n'en gardait qu'une et le virement le plus suspect pouvait disparaître.
  const g = new graphology.Graph({ multi: true, type: "directed" });

  // 3) Construction des nœuds — PAR LOTS, avec compteur (preuve que ça tourne)
  setHead("Construction des comptes...");
  logLine(`>  Ajout de ${nf(data.nodes.length)} comptes (positions figées)...`);
  const NB = data.nodes.length;
  const CHUNK = 1000;
  let risky = 0;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  const tNodes = t0();
  for (let i = 0; i < NB; i++) {
    const n = data.nodes[i];
    if (n.x < minX) minX = n.x; if (n.x > maxX) maxX = n.x;
    if (n.y < minY) minY = n.y; if (n.y > maxY) maxY = n.y;
    // Rayon volontairement petit : avec les 95 449 liens dessinés en permanence,
    // de grosses boules recouvraient le réseau au lieu de le montrer. L'échelle
    // reste en racine du degré, seulement resserrée (1,5..7,8 -> 0,5..2,8).
    const base = 0.5 + Math.sqrt(Math.min((n.fi || 0) + (n.fo || 0), 80)) * 0.26;
    g.addNode(n.id, {
      x: n.x, y: n.y, size: base, baseSize: base,
      // gris au départ : la couleur définitive est posée par le premier
      // recomputeAgg(), qui seul connaît la fenêtre temporelle.
      color: riskColor(0, false), label: n.id,   // le libellé reste l'ID unique
      score: n.s, role: n.r, country: n.ci, ctype: n.ct, fi: n.fi, fo: n.fo,
      ownerName: n.nm, firstName: n.fn, lastName: n.ln,   // identité -> panneau infos
      truthRole: n.tr, truthDecoy: n.td,                  // vérité terrain M1 (affichage)
      // agg = score agrégé côté client sur la FENÊTRE TEMPORELLE courante,
      // seule valeur utilisée pour la couleur et les compteurs. `score` est le
      // score serveur par compte, calculé sur toute la période : il ne sert plus
      // qu'au panneau d'infos, jamais de repli, sinon on réintroduirait un score
      // hors fenêtre dans une vue qui prétend ne montrer qu'un intervalle.
      agg: 0, aggRaw: 0, aggFallback: true,
    });
    // index de recherche : nom/prénom (ou raison sociale) + ID, normalisé
    const displayName = (n.fn || n.ln) ? `${n.fn || ""} ${n.ln || ""}`.trim() : (n.nm || "");
    state.searchIndex.push({
      id: n.id, name: displayName, score: n.s, ct: n.ct,
      hay: `${displayName} ${n.id}`.toLowerCase(),
      agg: 0, aggRaw: 0, aggFallback: true,
    });
    if (n.s >= 50) risky++;
    if ((i + 1) % CHUNK === 0 || i === NB - 1) {
      setBar(25 + 35 * (i + 1) / NB);
      logLine(`     ${nf(i + 1)} / ${nf(NB)} comptes  <span class="dim">(dernier : ${n.id})</span>`);
      await nextFrame();   // rend la main au navigateur -> le log s'affiche vraiment
    }
  }
  // étendue réelle du layout serveur (sert au recadrage sur un voisinage)
  state.extent = Math.max(maxX - minX, maxY - minY, 1);
  logLine(`[OK] ${nf(NB)} comptes ajoutés en ${ms(tNodes)} · `
    + `<span class="num">${nf(risky)}</span> à risque ≥ 50 au score serveur `
    + `<span class="dim">(toute la période ; la carte, elle, note sur la fenêtre)</span> · `
    + `<span class="dim">étendue ${state.extent.toFixed(0)} unités</span>`, "ok");
  await nextFrame();

  // 4) Construction des liens — PAR LOTS
  setHead("Construction des flux...");
  logLine(`>  Ajout des liens + préparation de la frise temporelle...`);
  const tl = [];
  const scored = [];
  const NE = data.edges.length;
  let added = 0, frauds = 0, skipped = 0, noScore = 0;
  const tEdges = t0();
  for (let i = 0; i < NE; i++) {
    const e = data.edges[i];
    if (e.s === e.t || !g.hasNode(e.s) || !g.hasNode(e.t)) { skipped++; }
    else {
      // r = score 0..100 du virement, null si NON noté (cartes, prélèvements).
      // Un `null` ne doit jamais devenir 0 : sinon il passerait au rouge au seuil 0.
      const risk = (typeof e.r === "number" && isFinite(e.r)) ? e.r : null;
      const txId = e.i == null || e.i === "" ? null : String(e.i);
      if (risk == null) noScore++;
      const key = g.addEdge(e.s, e.t, {
        // Épaisseur resserrée (0,3..1,4 -> 0,1..0,5) pour la même raison que le
        // rayon des nœuds : tout est dessiné, donc tout doit rester fin.
        size: 0.1 + Math.log10((e.m || 1) + 1) * 0.12,
        color: e.f ? "rgba(255,90,90,0.35)" : "rgba(130,150,180,0.07)",
        ts: e.ts, amount: e.m, count: e.c, fraud: e.f, hidden: false,
        risk, txId,
        // libellé = montant (+ score si le virement est noté), affiché au survol
        amountLabel: e.c > 1 ? `${fmtAmount(e.m)} · ${e.c} tx`
          : (risk != null ? `${fmtAmount(e.m)} · ${risk}/100` : fmtAmount(e.m)),
        label: "",
      });
      added++; if (e.f) frauds++;
      // date convertie en ms UNE SEULE FOIS, et réutilisée par les trois index
      // ci-dessous. applyWindow() est appelée à chaque mouvement de poignée et
      // 14 fois/s en lecture animée : reparser les chaînes ISO à chaque appel
      // coûtait ~25 ms (mesuré), soit un tiers d'un cœur en continu.
      // `tms` et non `t` : dans le payload, `e.t` est le compte DESTINATAIRE.
      let tms = null;
      if (e.ts) { const p = new Date(e.ts).getTime(); if (!isNaN(p)) tms = p; }
      if (risk != null) {
        scored.push({ key, r: risk, t: tms });
        // index des virements notés REÇUS par le destinataire : c'est lui qui
        // porte le risque d'être une mule, donc c'est son score qu'on agrège.
        // Une transaction sans horodatage exploitable n'y entre pas : elle
        // serait comptée dans toutes les fenêtres, y compris celles où elle
        // n'a pas lieu d'être.
        if (tms != null) {
          let inb = state.inbound.get(e.t);
          if (!inb) { inb = { r: [], m: [], t: [] }; state.inbound.set(e.t, inb); }
          inb.r.push(risk); inb.m.push(e.m || 0); inb.t.push(tms);
        }
      }
      if (tms != null) tl.push({ key, t: tms });
    }
    if ((i + 1) % 5000 === 0 || i === NE - 1) {
      setBar(60 + 25 * (i + 1) / NE);
      logLine(`     ${nf(i + 1)} / ${nf(NE)} liens traités  <span class="dim">(${nf(added)} ajoutés)</span>`);
      await nextFrame();
    }
  }
  logLine(`[OK] ${nf(added)} liens ajoutés en ${ms(tEdges)} · `
    + `<span class="num">${nf(frauds)}</span> frauduleux · `
    + `<span class="num">${nf(scored.length)}</span> notés, ${nf(noScore)} sans score`
    + (skipped ? ` · ${nf(skipped)} ignorés (boucles)` : ""), "ok");

  // 5) Frise temporelle
  setHead("Tri de la frise temporelle...");
  const tSort = t0();
  tl.sort((a, b) => a.t - b.t);
  logLine(`[OK] ${nf(tl.length)} liens horodatés triés en ${ms(tSort)}`, "ok");
  setBar(90); await nextFrame();

  state.graph = g;
  state.edgesByTime = tl;
  // arêtes notées, triées par score décroissant : le comptage au-dessus du seuil
  // s'arrête dès qu'on passe sous le seuil (pas de balayage complet).
  scored.sort((a, b) => b.r - a.r);
  state.scoredEdges = scored;
  state.tMin = data.meta.t_min;
  state.tMax = data.meta.t_max;
  logLine(`[OK] Graphe prêt — temps total ${ms(started)}`, "ok");
}

/* Plus de layout navigateur : positions figees cote serveur.
 *
 * Il n'y a plus non plus de niveau de detail (LOD) : le seuil de risque qui
 * montait a 50 en vue d'ensemble, et le curseur "Risque min" qui le doublait,
 * ont ete retires. Les deux cachaient par defaut la quasi-totalite du reseau,
 * ce qui est exactement l'inverse de ce qu'une cartographie doit faire : on ne
 * peut pas juger un graphe de 7 060 comptes en en voyant 500. */

/* ================= Seuil d'alerte sur les virements (fonctionnalité 2) =======
 * Un virement noté r >= seuil est "au-dessus du seuil" : son arête passe au
 * rouge et reste dessinée même sans survol ni sélection (sinon le réglage ne se
 * verrait pas, les 77 000 arêtes n'étant normalement affichées qu'au focus). */

// "80", "80 %", "0.8", "0,8" -> 80. En dessous de 1 AVEC séparateur décimal, on
// lit une probabilité ; "0" et "1" nus restent des scores sur 100.
function parseThreshold(raw) {
  const txt = String(raw ?? "").trim().replace(",", ".").replace("%", "").trim();
  if (!txt) return null;
  const v = parseFloat(txt);
  if (!isFinite(v)) return null;
  const proba = v > 0 && v < 1 && txt.includes(".");
  const on100 = proba ? v * 100 : v;
  return Math.max(0, Math.min(100, Math.round(on100)));
}

// nb d'arêtes notées au-dessus du seuil ET dans la fenêtre temporelle courante
function countHotEdges() {
  const thr = state.edgeThreshold, t0 = state.winT0, t1 = state.winT1;
  const arr = state.scoredEdges;
  let c = 0;
  for (let i = 0; i < arr.length; i++) {
    const e = arr[i];
    if (e.r < thr) break;             // tableau trié par score décroissant
    if (t0 == null || e.t == null || (e.t >= t0 && e.t <= t1)) c++;
  }
  return c;
}

/* ================= Agrégateurs de score par compte (fonctionnalité 5) =======
 * Recalculés CÔTÉ CLIENT à partir des virements notés reçus par le compte
 * (`state.inbound`), et RESTREINTS À LA FENÊTRE TEMPORELLE courante : un compte
 * dont le seul virement suspect date d'une période qui n'est plus affichée ne
 * doit pas rester rouge à l'écran. C'était le cas avant : les scores étaient
 * calculés une fois pour toutes sur les deux mois, quelle que soit la fenêtre.
 *
 * Renvoie null quand le compte n'a reçu aucun virement noté DANS la fenêtre.
 * L'appelant ne retombe alors PAS sur le score serveur (qui porte sur toute la
 * période, donc contredirait la fenêtre) : le compte passe au gris.
 * `value` sert à la couleur et aux compteurs, `raw` est ce qu'on affiche. */
const AGG_LABELS = {
  max: "max des virements reçus",
  top3: "moyenne des 3 plus hauts",
  count: "nombre au-dessus du seuil",
  amount: "moyenne pondérée par les montants",
  noisyor: "cumul (noisy-or)",
};

function aggregate(mode, inb, thr, t0, t1) {
  const N = inb ? inb.r.length : 0;
  // `inWin` : null de bout en bout quand aucune fenêtre n'est posée (avant le
  // premier applyWindow), sinon bornes incluses, comme pour les arêtes.
  const noWin = t0 == null || t1 == null;
  const ts = inb ? inb.t : null;
  const inWin = i => noWin || (ts[i] >= t0 && ts[i] <= t1);
  if (mode === "count") {
    // "0 virement au-dessus du seuil sur cette période" est une réponse juste,
    // pas une absence de réponse : ce mode compte donc même à 0. Mais un compte
    // qui n'a RIEN reçu de noté dans la fenêtre reste sans donnée (`hasData`),
    // et l'appelant le passera au gris plutôt qu'au vert.
    let c = 0, total = 0;
    for (let i = 0; i < N; i++) {
      if (!inWin(i)) continue;
      total++;
      if (inb.r[i] >= thr) c++;
    }
    return { raw: c, value: c > 0 ? 100 : 0, n: c, hasData: total > 0 };
  }
  // nombre de virements effectivement retenus : c'est lui, et non N, qui dit si
  // le compte a de quoi être noté sur la fenêtre.
  let n = 0;
  for (let i = 0; i < N; i++) if (inWin(i)) n++;
  if (!n) return null;
  const r = inb.r, m = inb.m;
  let v;
  if (mode === "max") {
    v = 0;
    for (let i = 0; i < N; i++) if (inWin(i) && r[i] > v) v = r[i];
  } else if (mode === "top3") {
    let a = -1, b = -1, c = -1;
    for (let i = 0; i < N; i++) {
      if (!inWin(i)) continue;
      const s = r[i];
      if (s > a) { c = b; b = a; a = s; }
      else if (s > b) { c = b; b = s; }
      else if (s > c) { c = s; }
    }
    const top = [a, b, c].filter(s => s >= 0).slice(0, Math.min(3, n));
    v = top.reduce((p, s) => p + s, 0) / top.length;
  } else if (mode === "amount") {
    let num = 0, den = 0;
    for (let i = 0; i < N; i++) {
      if (!inWin(i)) continue;
      const w = (typeof m[i] === "number" && m[i] > 0) ? m[i] : 0;
      num += r[i] * w; den += w;
    }
    // montants absents ou tous nuls : moyenne simple plutôt qu'une division par 0
    if (den > 0) v = num / den;
    else {
      let s = 0;
      for (let i = 0; i < N; i++) if (inWin(i)) s += r[i];
      v = s / n;
    }
  } else if (mode === "noisyor") {
    let p = 1;
    for (let i = 0; i < N; i++) {
      if (inWin(i)) p *= (1 - Math.max(0, Math.min(100, r[i])) / 100);
    }
    v = 100 * (1 - p);
  } else {
    return null;   // mode inconnu
  }
  v = Math.max(0, Math.min(100, v));
  return { raw: Math.round(v), value: v, n };
}

// un compte est "au-dessus du seuil" : au moins un virement pour `count`,
// score agrégé >= seuil pour les autres
function aggAbove(mode, value, raw, thr) {
  return mode === "count" ? raw >= 1 : value >= thr;
}

/* Recalcule l'agrégat de TOUS les comptes sur la fenêtre courante, recolore et
 * recompte. Appelé au changement d'agrégateur, au changement de seuil en mode
 * `count`, et surtout À CHAQUE applyWindow() : c'est ce qui rend les couleurs
 * cohérentes avec l'intervalle affiché. Donc chemin chaud, 14 fois/s pendant la
 * lecture animée : on ne fait qu'un passage sur les 7 060 comptes et un passage
 * sur leurs virements notés (52 824 au total, tous comptes confondus). */
function recomputeAgg() {
  const g = state.graph;
  if (!g) return;
  const mode = state.aggMode, thr = state.edgeThreshold;
  const t0 = state.winT0, t1 = state.winT1;
  const idx = state.searchIndex;
  let above = 0, fallbacks = 0;
  for (let i = 0; i < idx.length; i++) {
    const m = idx[i];
    const r = aggregate(mode, state.inbound.get(m.id), thr, t0, t1);
    let value, raw, fb = false;
    if (r) {
      value = r.value; raw = r.raw;
      // mode `count` : l'objet existe toujours, c'est `hasData` qui dit si le
      // compte a reçu quelque chose de noté dans la fenêtre.
      if (r.hasData === false) { fb = true; fallbacks++; }
    } else {
      // aucun virement noté dans la fenêtre : score 0 et gris. Reprendre le
      // score serveur ici remettrait un jugement portant sur toute la période
      // dans une vue qui n'affiche qu'un intervalle.
      value = 0; raw = 0; fb = true; fallbacks++;
    }
    m.agg = value; m.aggRaw = raw; m.aggFallback = fb;
    const prev = g.getNodeAttribute(m.id, "agg");
    const prevFb = g.getNodeAttribute(m.id, "aggFallback");
    if (prev !== value || prevFb !== fb) {
      g.setNodeAttribute(m.id, "agg", value);
      g.setNodeAttribute(m.id, "color", riskColor(value, !fb));
    }
    g.setNodeAttribute(m.id, "aggRaw", raw);
    g.setNodeAttribute(m.id, "aggFallback", fb);
    if (!fb && aggAbove(mode, value, raw, thr)) above++;
  }
  state.aggAbove = above;
  state.aggFallbacks = fallbacks;
}

// recompte seulement (les agrégats hors `count` ne dépendent pas du seuil)
function recountAgg() {
  const mode = state.aggMode, thr = state.edgeThreshold, idx = state.searchIndex;
  let above = 0;
  for (let i = 0; i < idx.length; i++) {
    if (aggAbove(mode, idx[i].agg, idx[i].aggRaw, thr)) above++;
  }
  state.aggAbove = above;
}

// bandeaux de la deuxième rangée de la frise
function updateThresholdUI() {
  const thr = state.edgeThreshold;
  const lbl = el("edge-threshold-lbl");
  if (lbl) lbl.textContent = `seuil ${thr} / 100, soit ${(thr / 100).toFixed(2).replace(".", ",")}`;
  state.nHot = countHotEdges();
  const hc = el("hot-count");
  if (hc) {
    hc.textContent = state.scoredEdges.length
      ? `${nf(state.nHot)} virements ≥ ${thr} (sur ${nf(state.scoredEdges.length)} notés)`
      : "aucun virement noté dans ce payload";
  }
  const ac = el("agg-count");
  if (ac) {
    ac.textContent = state.aggMode === "count"
      ? `${nf(state.aggAbove)} comptes avec au moins 1 virement ≥ ${thr}`
      : `${nf(state.aggAbove)} comptes au score agrégé ≥ ${thr}`;
  }
  const note = el("agg-note");
  if (note) {
    if (!state.txScores) {
      note.textContent = "Scores par virement indisponibles : aucun score par compte calculable.";
    } else if (state.aggFallbacks) {
      note.textContent = `${nf(state.aggFallbacks)} comptes sans virement noté dans la période : en gris, non notés.`;
    } else { note.textContent = ""; }
  }
}

// un seul point d'entrée pour changer le seuil (curseur, champ, programme)
function setThreshold(value, opts) {
  const thr = parseThreshold(value);
  if (thr == null) return;
  const changed = thr !== state.edgeThreshold;
  state.edgeThreshold = thr;
  const rng = el("edge-threshold"), num = el("edge-threshold-num");
  if (rng && (!opts || opts.from !== "range")) rng.value = String(thr);
  if (num && (!opts || opts.from !== "num")) num.value = String(thr);
  if (changed) {
    // le mode `count` dépend du seuil : il faut tout recalculer et recolorer
    if (state.aggMode === "count") recomputeAgg(); else recountAgg();
  }
  updateThresholdUI();
  if (state.renderer) state.renderer.refresh();
  if (!el("risklist").hidden) renderRiskList();
}

function setAggMode(mode) {
  state.aggMode = AGG_LABELS[mode] ? mode : "max";
  const tAgg = t0();
  recomputeAgg();
  updateThresholdUI();
  updateLodBadge();
  if (state.renderer) state.renderer.refresh();
  if (!el("risklist").hidden) renderRiskList();
  if (state.selected) showPanel(state.selected);
  logLine(`>  Agrégateur « ${AGG_LABELS[state.aggMode]} » appliqué en ${ms(tAgg)} · `
    + `${nf(state.aggAbove)} comptes au-dessus du seuil ${state.edgeThreshold}`, "dim");
}

/* ---------- Rendu Sigma + effet focus (Obsidian) ---------- */
async function initSigma() {
  // (a) Vérifier WebGL AVANT de créer Sigma (cause n°1 de blocage à cette étape)
  logLine(">  Vérification du support WebGL...");
  await nextFrame();
  const wgl = detectWebGL();
  if (!wgl.ok) {
    logLine(`[X] WebGL INDISPONIBLE dans ce navigateur (${wgl.renderer}).`, "warn");
    logLine("    Sigma ne peut pas s'initialiser sans WebGL. Essayez :", "warn");
    logLine("    - un autre navigateur (Chrome/Firefox à jour),", "warn");
    logLine("    - activer l'accélération matérielle,", "warn");
    logLine("    - ou utilisez la vue classique (bouton en haut à droite).", "warn");
    setHead("WebGL indisponible");
    throw new Error("WebGL indisponible");
  }
  logLine(`[OK] ${wgl.version} disponible`
    + (wgl.renderer && wgl.renderer !== "inconnu" ? ` · GPU : <span class="dim">${wgl.renderer}</span>` : ""), "ok");
  if (wgl.software) {
    logLine("[!] Rendu WebGL LOGICIEL détecté (pas de vraie carte graphique).", "warn");
    logLine("    L'affichage peut être lent sur 7 000 nœuds. On continue...", "warn");
  }
  await nextFrame();

  // (b) Construction du moteur Sigma
  logLine(">  Instanciation du moteur Sigma...");
  await nextFrame();
  const tSig = t0();
  state.renderer = new Sigma(state.graph, el("sigma"), {
    renderEdgeLabels: true,           // libellés d'arêtes (montant) au survol
    labelRenderedSizeThreshold: 12,   // labels nœuds seulement sur gros nœuds / au zoom
    labelFont: "Inter, sans-serif",
    labelColor: { color: "#c9d4e8" },
    edgeLabelFont: "Inter, sans-serif",
    edgeLabelColor: { color: "#ffe08a" },
    edgeLabelSize: 11,
    defaultEdgeType: "arrow",   // flèches : directionnalité src -> dst
    // SANS ce réglage, Sigma 3 n'émet NI enterEdge/leaveEdge NI clickEdge :
    // les écouteurs d'arêtes déjà en place ne se déclenchaient jamais.
    enableEdgeEvents: true,
    zIndex: true,
    hideEdgesOnMove: true,   // ne pas dessiner les arêtes pendant pan/zoom (fluidité)
    defaultEdgeColor: "rgba(130,170,230,0.8)",
    minArrowSize: 2,         // pointe de flèche discrète : 10 masquait le nœud visé
    minCameraRatio: 0.03,
    maxCameraRatio: 1.4,
  });
  logLine(`[OK] Moteur Sigma instancié en ${ms(tSig)}`, "ok");
  await nextFrame();
  logLine(">  Attachement des reducers (effet focus) et des événements...");
  await nextFrame();

  // reducers = cœur de l'effet Obsidian : estompe tout sauf le focus
  state.renderer.setSetting("nodeReducer", (node, data) => {
    const res = { ...data };
    // AUCUN filtre de score ici : tous les comptes sont visibles en vue
    // générale. Les boules étant petites, le facteur de grossissement au focus
    // est monté (1,7 -> 2,6) pour que le nœud sélectionné reste repérable.
    // CLIC (selected) : on ne montre QUE le nœud et ses partenaires de la fenêtre.
    if (state.selected) {
      if (node === state.selected) { res.size = data.baseSize * 2.6; res.zIndex = 2; res.forceLabel = true; return res; }
      if (state.neighbors.has(node)) { res.size = data.baseSize * 1.5; res.zIndex = 1; res.forceLabel = true; return res; }
      res.hidden = true; return res;      // tout le reste est masqué
    }
    if (state.hovered) {
      if (node === state.hovered) { res.size = data.baseSize * 2.4; res.zIndex = 2; res.forceLabel = true; }
      else if (state.neighbors.has(node)) { res.size = data.baseSize * 1.4; res.zIndex = 1; res.forceLabel = true; }
      else { res.color = "rgba(120,140,170,0.12)"; res.label = ""; res.zIndex = 0; }
    }
    return res;
  });

  state.renderer.setSetting("edgeReducer", (edge, data) => {
    const res = { ...data };
    const g = state.graph;
    const focus = state.selected || state.hovered;
    // fenêtre temporelle : masquer les liens hors période (prioritaire sur tout)
    if (data._tlHidden) { res.hidden = true; return res; }
    // ARÊTE AU-DESSUS DU SEUIL : rouge et dessinée en permanence, sans focus.
    // `risk == null` (carte, prélèvement, paquet agrégé) ne passe jamais ici,
    // même au seuil 0 : un virement non noté n'est pas un virement à 0.
    if (state.hotEdges && data.risk != null && data.risk >= state.edgeThreshold) {
      const hov = edge === state.hoveredEdge;
      res.hidden = false;
      res.color = hov ? "rgba(255,224,138,0.98)" : "rgba(255,70,70,0.9)";
      res.size = Math.max(data.size, hov ? 1.9 : 1.0);
      res.zIndex = 4;
      // libellé seulement au survol ou au focus : sinon des milliers de
      // montants s'empilent à l'écran et le canvas 2D des labels s'effondre
      res.label = (hov || focus) ? data.amountLabel : "";
      return res;
    }
    // VUE GÉNÉRALE, sans focus. `allEdges` (coché par défaut) dessine les 95 449
    // liens : c'est ce qui permet de voir le réseau entier, et c'est ce qui coûte
    // le plus cher au rendu. La case de l'en-tête existe pour le décocher si la
    // machine de démo ne suit pas ; on retombe alors sur l'ancien comportement,
    // où un lien n'apparaissait qu'au survol ou au clic d'un compte.
    if (!focus) {
      if (!state.allEdges) { res.hidden = true; return res; }
      res.hidden = false;
      // pas de libellé sans focus : des milliers de montants empilés font
      // s'effondrer le canvas 2D des labels (le rendu WebGL, lui, tient).
      res.label = "";
      res.color = data.fraud ? "rgba(255,90,90,0.30)" : "rgba(130,150,180,0.10)";
      res.zIndex = 0;
      return res;
    }
    // on ne garde que les arêtes incidentes au nœud focalisé
    const [s, t] = g.extremities(edge);
    if (s !== focus && t !== focus) { res.hidden = true; return res; }
    // PRIX : le montant s'affiche sur TOUTES les arêtes du nœud focalisé
    res.label = data.amountLabel;
    if (edge === state.hoveredEdge) {        // survol = mise en évidence
      res.color = "rgba(255,224,138,0.95)";
      res.size = Math.max(data.size, 1.7); res.zIndex = 3;
    } else {
      res.color = "rgba(130,170,230,0.85)";
      res.size = Math.max(data.size, 1.2); res.zIndex = 2;
    }
    return res;
  });

  // survol = focus temporaire (+ resserrement visuel via zoom doux)
  state.renderer.on("enterNode", ({ node }) => { if (!state.selected) setHover(node); });
  state.renderer.on("leaveNode", () => { if (!state.selected) setHover(null); });
  state.renderer.on("clickNode", ({ node }) => selectNode(node));
  // NB : pas de désélection au clic sur le vide (évite les missclicks).
  // Pour revenir à la vue générale : touche "\" (voir initControls).
  // survol d'une arête -> affiche le montant de la transaction
  state.renderer.on("enterEdge", ({ edge }) => { state.hoveredEdge = edge; state.renderer.refresh(); });
  state.renderer.on("leaveEdge", () => { state.hoveredEdge = null; state.renderer.refresh(); });
  // clic sur une arête -> détail du virement (pourquoi il n'est pas net)
  state.renderer.on("clickEdge", ({ edge }) => openEdgeDetail(edge));

  // Plus de recalcul de seuil au zoom : l'affichage ne dépend plus de la caméra.
  logLine("[OK] Reducers et événements attachés", "ok");
  await nextFrame();

  // (c) Premier rendu (dessin WebGL des 7 000 nœuds) — souvent le vrai coût
  logLine(">  Premier rendu WebGL (dessin des nœuds et liens)...");
  await nextFrame();
  const tDraw = t0();
  state.renderer.refresh();
  logLine(`[OK] Premier rendu effectué en ${ms(tDraw)}`, "ok");
  await nextFrame();
}

/* ---------- Liste des comptes à risque ---------- */
function renderRiskList() {
  const thr = parseInt(el("rl-threshold").value, 10);
  const mode = state.aggMode;
  // la liste suit l'agrégateur courant : en mode `count` on classe par nombre de
  // virements au-dessus du seuil, sinon par score agrégé.
  // Un compte sans virement noté dans la fenêtre n'est pas classable : il est
  // écarté de la liste au lieu d'y figurer avec un score de 0 ou un score
  // serveur qui porterait sur une autre période.
  const items = state.searchIndex
    .filter(e => !e.aggFallback && (mode === "count" ? e.aggRaw >= 1 : e.agg >= thr))
    .sort((a, b) => mode === "count" ? b.aggRaw - a.aggRaw : b.agg - a.agg);
  el("rl-count").textContent = mode === "count"
    ? `${items.length.toLocaleString("fr-FR")} comptes (≥ 1 virement ≥ ${state.edgeThreshold})`
    : `${items.length.toLocaleString("fr-FR")} comptes · ${AGG_LABELS[mode]}`;
  const ul = el("rl-items");
  ul.innerHTML = items.slice(0, 500).map(m => {
    const col = riskColor(m.agg, !m.aggFallback);
    const name = m.name || "(sans nom)";
    // mode `count` : on montre le compte BRUT de virements, pas un score sur 100
    const val = mode === "count" ? m.aggRaw : Math.round(m.agg);
    const sub = mode === "count" ? `${esc(m.id)} · ${m.aggRaw} virement(s) ≥ ${state.edgeThreshold}`
      : `${esc(m.id)} · ${esc(m.ct ?? "")}`;
    return `<li data-id="${esc(m.id)}">
      <span class="rl-dot" style="background:${col}"></span>
      <span>
        <span class="rl-name">${esc(name)}</span><br/>
        <span class="rl-sub">${sub}</span>
      </span>
      <span class="rl-score" style="color:${col}">${val}</span></li>`;
  }).join("");
  if (items.length > 500) {
    ul.insertAdjacentHTML("beforeend",
      `<li class="rl-sub" style="justify-content:center">… ${(items.length - 500).toLocaleString("fr-FR")} de plus (affinez le seuil)</li>`);
  }
  ul.querySelectorAll("li[data-id]").forEach(li => {
    li.onclick = () => selectNode(li.dataset.id);
  });
}

function toggleRiskList(show) {
  const panel = el("risklist");
  const open = show === undefined ? panel.hidden : show;
  panel.hidden = !open;
  if (open) renderRiskList();
}

/* ---------- Recherche par nom / prénom / ID ---------- */
function runSearch(q) {
  const box = el("search-results");
  const query = q.trim().toLowerCase();
  if (query.length < 2) { box.hidden = true; box.innerHTML = ""; return; }
  const terms = query.split(/\s+/);
  // un compte correspond s'il contient TOUS les termes (nom ET prénom)
  const matches = state.searchIndex
    .filter(e => terms.every(t => e.hay.includes(t)))
    .slice(0, 50);
  if (!matches.length) {
    box.innerHTML = `<li class="sr-empty">Aucun compte ne correspond.</li>`;
    box.hidden = false; return;
  }
  box.innerHTML = matches.map(m => {
    const col = riskColor(m.agg, !m.aggFallback);   // mêmes seuils que le graphe
    const name = m.name || "(sans nom)";
    // un compte sans virement noté dans la fenêtre reste cherchable (on doit
    // pouvoir aller le voir), mais on ne lui invente pas un score
    const val = m.aggFallback ? "non noté sur la période"
      : state.aggMode === "count" ? `${m.aggRaw} virement(s) ≥ ${state.edgeThreshold}`
        : `risque ${Math.round(m.agg)}`;
    return `<li data-id="${esc(m.id)}">
      <span class="sr-dot" style="background:${col}"></span>
      <span class="sr-name">${esc(name)}</span>
      <span class="sr-meta"> · ${esc(m.id)} · ${esc(m.ct ?? "")} · ${val}</span></li>`;
  }).join("");
  box.hidden = false;
  box.querySelectorAll("li[data-id]").forEach(li => {
    li.onclick = () => {
      el("search-input").value = "";
      box.hidden = true;
      selectNode(li.dataset.id);
    };
  });
}

// Il n'y a plus de seuil d'affichage à annoncer : le badge dit maintenant ce qui
// est réellement dessiné, et l'agrégateur de score en cours s'il n'est pas celui
// par défaut.
function updateLodBadge() {
  const b = el("lod-badge");
  if (!b || !state.graph) return;
  const nf2 = n => n.toLocaleString("fr-FR");
  const agg = state.aggMode === "max" ? "" : ` · ${AGG_LABELS[state.aggMode]}`;
  b.textContent = state.allEdges
    ? `${nf2(state.graph.order)} comptes · ${nf2(state.graph.size)} liens dessinés${agg}`
    : `${nf2(state.graph.order)} comptes · liens au focus seulement${agg}`;
}

/* Bandeau de partition. La frise démarre sur la partition de TEST parce que les
 * scores des virements antérieurs sont in-sample : le modèle de M3 s'est
 * entraîné dessus, donc ils sont flatteurs et ne prouvent rien. 36 288 des
 * 52 824 virements notés sont dans ce cas, soit 68,7 %. */
function updateSplitBadge() {
  const b = el("split-badge");
  if (!b) return;
  const n = state.nScoredTrain, m = state.nScoredTest;
  if (state.includeTrain) {
    b.textContent = n != null
      ? `Entraînement inclus : ${nf(n)} virements notés in-sample, non démonstratifs`
      : "Entraînement inclus : scores in-sample, non démonstratifs";
    b.style.color = "#ffb020";
  } else if (state.tDemoStart) {
    b.textContent = m != null
      ? `Test seul depuis le ${fmtDate(state.tDemoStart)} · ${nf(m)} virements hors échantillon`
      : `Partition de test seule, depuis le ${fmtDate(state.tDemoStart)}`;
    b.style.color = "";
  } else {
    // le serveur n'a pas su déduire la borne (source sqlite, CSV sans gt_split)
    b.textContent = "Partition inconnue : aucune borne de test fournie par le serveur";
    b.style.color = "#ffb020";
  }
}

/* Plage totale de la frise : [début du test, fin] par défaut, [début des
 * données, fin] si l'utilisateur demande l'historique d'entraînement. Les deux
 * champs date bornent la plage que les 1 000 crans du double curseur couvrent. */
function applySplitRange() {
  const lo = (!state.includeTrain && state.tDemoStart) ? state.tDemoStart : state.tMin;
  el("date-start").value = lo ? lo.slice(0, 10) : "";
  el("date-end").value = state.tMax ? state.tMax.slice(0, 10) : "";
  el("time-min").value = 0; el("time-max").value = 1000;
  updateSplitBadge();
  applyWindow();
}

/* Voisins d'un nœud, RESTREINTS à la fenêtre temporelle courante :
 * seuls les comptes avec qui il a transigé entre winT0 et winT1 sont retenus. */
function neighborsOf(node) {
  const t0 = state.winT0, t1 = state.winT1;
  if (t0 == null || t1 == null) {   // pas encore de fenêtre : tout le voisinage
    const s = new Set([node]);
    state.graph.forEachNeighbor(node, n => s.add(n));
    return s;
  }
  return windowNeighbors(node, t0, t1);
}

function setHover(node) {
  state.hovered = node;
  state.neighbors = node ? neighborsOf(node) : new Set();
  state.renderer.refresh();
}

/* clic = focus persistant + RESSERREMENT : on recadre la caméra sur le voisinage
 * (uniquement les partenaires de la fenêtre temporelle sélectionnée) */
function selectNode(node) {
  state.selected = node;
  state.hovered = null;
  if (!node) {
    state.neighbors = new Set();
    el("panel").hidden = true;
    el("p-activity").innerHTML = "";
    el("txpanel").hidden = true;
    state.accountReq++; state.txReq++;   // annule les réponses en vol
    state.renderer.refresh();
    state.renderer.getCamera().animatedReset();
    return;
  }
  state.neighbors = neighborsOf(node);
  showPanel(node);
  // l'appel réseau n'est fait QU'ICI : showPanel() est aussi rappelé par
  // applyWindow() 14 fois par seconde en lecture animée.
  loadAccountActivity(node);
  state.renderer.refresh();
  zoomToNeighborhood(node);
}

/* "rapprocher tout ça" au clic : recadre la caméra sur la bounding box du voisinage */
function zoomToNeighborhood(node) {
  const g = state.graph;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  state.neighbors.forEach(n => {
    const a = g.getNodeAttributes(n);
    minX = Math.min(minX, a.x); maxX = Math.max(maxX, a.x);
    minY = Math.min(minY, a.y); maxY = Math.max(maxY, a.y);
  });
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  // convertir en coord écran via le ratio ; on vise un ratio serré
  const cam = state.renderer.getCamera();
  const spanX = Math.max(maxX - minX, 1), spanY = Math.max(maxY - minY, 1);
  // étendue RÉELLE du layout serveur (~1040 unités), mesurée au chargement.
  // L'ancienne constante 200 (héritée de ForceAtlas2) sous-estimait l'échelle
  // d'un facteur 5 : la caméra zoomait beaucoup trop près du voisinage.
  const ratio = Math.max(0.08, Math.min(spanX, spanY) / state.extent * 1.4);
  const { x, y } = state.renderer.graphToViewport({ x: cx, y: cy });
  // Sigma raisonne en coord normalisées ; on anime vers le centre du voisinage
  const pos = state.renderer.viewportToFramedGraph({ x, y });
  cam.animate({ x: pos.x, y: pos.y, ratio }, { duration: 500 });
}

function showPanel(node) {
  const a = state.graph.getNodeAttributes(node);
  el("panel").hidden = false;
  el("p-id").textContent = node;   // identifiant unique (titre)
  // 6 rôles produits par graph_features._classify_role (+ "normal" par défaut)
  const roleLabels = {
    collector: "Compte collecteur (étoile)", collector_redistributor: "Collecte + redistribution",
    smurf_target: "Cible de fractionnement", relay: "Maillon de chaîne",
    cycle_member: "Membre d'un cycle", normal: "Comportement normal",
  };
  el("p-role").textContent = roleLabels[a.role] || a.role || "—";
  // L'anneau affiche le score de la FENÊTRE, pas le score serveur calculé sur
  // les deux mois : c'est le plus gros chiffre du panneau, le laisser hors
  // fenêtre contredisait tout le reste de l'écran.
  const shown = a.aggFallback ? null : Math.round(a.agg);
  el("p-score").textContent = shown == null ? "—" : shown;
  el("p-score-label").textContent = shown == null
    ? "Non noté sur la période" : "Score sur la période";
  const ringCol = riskColor(a.agg, !a.aggFallback);
  document.querySelector(".score-ring").style.background =
    `conic-gradient(${ringCol} ${(shown ?? 0) * 3.6}deg, #1b2434 0deg)`;

  // Vérité terrain M1 (étiquetée comme telle, distincte du score)
  const truthLabels = {
    fraudster: "Fraudeur (vérité M1)", mule: "Mule (vérité M1)",
    victim: "Victime (vérité M1)", normal: "Normal (vérité M1)",
  };
  let truth = truthLabels[a.truthRole] || null;
  if (a.truthDecoy) truth = "Leurre — légitime mais trompeur (vérité M1)";

  // Identité du titulaire : nom + prénom pour une personne, raison sociale sinon.
  // N'apparaît QUE dans ce panneau (jamais sur le graphe).
  let identite;
  if (a.firstName || a.lastName) {
    identite = `${a.firstName ?? ""} ${a.lastName ?? ""}`.trim();
  } else {
    identite = a.ownerName || "—";
  }

  // Score agrégé côté client, sur la FENÊTRE courante. `nWin` compte les
  // virements notés reçus dans cette fenêtre, et non sur toute la période :
  // c'est ce nombre qui justifie le score affiché juste au-dessus.
  const inb = state.inbound.get(node);
  const nTotal = inb ? inb.r.length : 0;
  let nWin = 0;
  if (inb && state.winT0 != null) {
    for (let i = 0; i < inb.t.length; i++) {
      if (inb.t[i] >= state.winT0 && inb.t[i] <= state.winT1) nWin++;
    }
  } else { nWin = nTotal; }
  const aggLine = a.aggFallback ? "aucun virement noté reçu sur cette période"
    : state.aggMode === "count"
      ? `${a.aggRaw} virement(s) reçus ≥ ${state.edgeThreshold}`
      : `${Math.round(a.agg)} / 100`;

  // fi / fo sont des NOMBRES de transactions (fan_in / fan_out), pas des montants
  el("p-attrs").innerHTML = `
    <div><dt>Titulaire</dt><dd>${esc(identite)}</dd></div>
    ${truth ? `<div><dt>Statut réel</dt><dd>${esc(truth)}</dd></div>` : ""}
    <div><dt>Pays</dt><dd>${esc(a.country ?? "—")}</dd></div>
    <div><dt>Type client</dt><dd>${esc(a.ctype ?? "—")}</dd></div>
    <div><dt>Transactions reçues</dt><dd>${a.fi}</dd></div>
    <div><dt>Transactions émises</dt><dd>${a.fo}</dd></div>
    <div><dt>Partenaires (fenêtre)</dt><dd>${Math.max(state.neighbors.size - 1, 0)}</dd></div>
    <div><dt>${esc(AGG_LABELS[state.aggMode])}</dt><dd>${esc(aggLine)}</dd></div>
    <div><dt>Virements notés reçus</dt><dd>${nWin} sur la période${
      nTotal !== nWin ? ` · ${nTotal} au total` : ""}</dd></div>`;
}

/* ====== Activité du compte : GET /api/account/{id} (fonctionnalité 4) ====== */

// message sobre et unique pour toutes les pannes d'API
function apiErrorHtml(status, quoi) {
  if (status === 404) return `<p class="pa-err">${esc(quoi)} : inconnu du serveur (404).</p>`;
  if (status === 503) return `<p class="pa-err">${esc(quoi)} : service indisponible (503), `
    + `les données ne sont pas encore chargées côté serveur.</p>`;
  if (status === 0) return `<p class="pa-err">${esc(quoi)} : serveur injoignable.</p>`;
  return `<p class="pa-err">${esc(quoi)} : le serveur a répondu ${status}.</p>`;
}

const DIR_ARROW = { in: "↓", out: "↑" };

async function loadAccountActivity(node) {
  const box = el("p-activity");
  const req = ++state.accountReq;
  box.innerHTML = `<p class="pa-wait">Chargement de l'activité du compte…</p>`;
  let d;
  try {
    const r = await fetch(`/api/account/${encodeURIComponent(node)}`);
    if (req !== state.accountReq) return;          // un autre compte a été cliqué
    if (!r.ok) { box.innerHTML = apiErrorHtml(r.status, "Activité du compte"); return; }
    d = await r.json();
  } catch (e) {
    if (req !== state.accountReq) return;
    box.innerHTML = apiErrorHtml(0, "Activité du compte"); return;
  }
  if (req !== state.accountReq) return;

  const txs = Array.isArray(d.transactions) ? d.transactions.slice() : [];
  // tri par date, les plus récentes d'abord
  txs.sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime());

  const rows = txs.map(t => {
    const sc = typeof t.risk_score === "number" ? t.risk_score : null;
    const col = sc == null ? "#5f6f8c" : riskColor(sc);
    const cp = t.counterparty_name || t.counterparty || "—";
    return `<li data-tx="${esc(t.tx_id ?? "")}" title="${esc(t.tx_type ?? "")} · ${esc(t.instrument ?? "")}">
      <span class="pa-dir">${DIR_ARROW[t.direction] || "·"}</span>
      <span class="pa-cp">${esc(cp)}<br/><span class="pa-date">${esc(fmtDate(t.ts))}</span></span>
      <span class="pa-amt">${fmtAmount(t.amount)}</span>
      <span class="pa-sc" style="color:${col}">${sc == null ? "—" : sc}</span></li>`;
  }).join("");

  box.innerHTML = `
    <h3>Activité du compte</h3>
    <div class="pa-grid">
      <span>Virements reçus</span><span>${nf(d.n_tx_in ?? 0)}</span>
      <span>Virements émis</span><span>${nf(d.n_tx_out ?? 0)}</span>
      <span>Montant cumulé reçu</span><span>${fmtAmount(d.amount_in)}</span>
      <span>Montant cumulé émis</span><span>${fmtAmount(d.amount_out)}</span>
      ${d.role ? `<span>Rôle détecté</span><span>${esc(d.role)}</span>` : ""}
    </div>
    <p class="pa-truth">
      <b>Vérité terrain du jeu de test</b> (étiquettes du générateur synthétique,
      indisponibles dans une banque réelle) :
      ${nf(d.n_fraud ?? 0)} transactions frauduleuses contre ${nf(d.n_clean ?? 0)} saines.
      ${d.truth_role ? `Rôle réel : ${esc(d.truth_role)}.` : ""}
      ${d.truth_is_decoy ? "Compte leurre : légitime mais trompeur." : ""}
    </p>
    <h3>Transactions (${nf(txs.length)}, plus récentes d'abord)</h3>
    ${txs.length ? `<ul id="pa-tx">${rows}</ul>`
      : `<p class="pa-wait">Aucune transaction renvoyée par le serveur.</p>`}
    ${d.truncated ? `<p class="tx-note">Liste bornée par le serveur à ${nf(txs.length)} transactions :
      l'historique complet du compte est plus long.</p>` : ""}`;

  // clic sur une ligne -> détail du virement (fonctionnalité 3)
  const ul = el("pa-tx");
  if (ul) ul.querySelectorAll("li[data-tx]").forEach(li => {
    li.onclick = () => { if (li.dataset.tx) showTxPanel(li.dataset.tx); };
  });
}

/* ====== Détail d'un virement : GET /api/tx/{tx_id} (fonctionnalité 3) ====== */

// vocabulaires du générateur M1, repli sur la valeur brute si elle est inconnue
const CHANNEL_LABELS = {
  web: "banque en ligne", mobile: "application mobile", branch: "agence",
  atm: "distributeur", api: "interface API", pos: "terminal de paiement",
  phone: "téléphone", batch: "traitement par lot",
};
const TXTYPE_LABELS = {
  salary: "salaire", rent: "loyer", donation: "don", transfer: "virement",
  purchase: "achat", subscription: "abonnement", refund: "remboursement",
  loan: "prêt", utility: "facture", tax: "impôt", cash_out: "retrait",
};
const LEVEL_LABELS = { high: "élevé", medium: "moyen", low: "faible", critical: "critique" };
const lbl = (map, v) => v == null ? "—" : (map[String(v).toLowerCase()] || String(v));

function openEdgeDetail(edge) {
  const a = state.graph.getEdgeAttributes(edge);
  if (!a.txId) {
    // arête sans tx_id : paquet agrégé, pas de détail transaction à montrer
    const p = el("txpanel");
    p.hidden = false;
    el("tx-title").textContent = "Lien sans détail";
    el("tx-body").innerHTML = `
      <p class="tx-wait">Ce lien n'est pas cliquable : il agrège plusieurs opérations
      et ne porte pas d'identifiant de transaction.</p>
      <div class="tx-grid">
        <span>Montant cumulé</span><span>${fmtAmount(a.amount)}</span>
        <span>Opérations</span><span>${nf(a.count || 1)}</span>
        <span>Dernière date</span><span>${esc(fmtDate(a.ts))}</span>
      </div>`;
    return;
  }
  showTxPanel(a.txId);
}

async function showTxPanel(txId) {
  const p = el("txpanel");
  const req = ++state.txReq;
  p.hidden = false;
  el("tx-title").textContent = txId;
  el("tx-body").innerHTML = `<p class="tx-wait">Chargement du virement…</p>`;
  let d;
  try {
    const r = await fetch(`/api/tx/${encodeURIComponent(txId)}`);
    if (req !== state.txReq) return;
    if (!r.ok) { el("tx-body").innerHTML = apiErrorHtml(r.status, "Détail du virement"); return; }
    d = await r.json();
  } catch (e) {
    if (req !== state.txReq) return;
    el("tx-body").innerHTML = apiErrorHtml(0, "Détail du virement"); return;
  }
  if (req !== state.txReq) return;

  const score = typeof d.risk_score === "number" ? d.risk_score : null;
  const solo = typeof d.score_tx_only === "number" ? d.score_tx_only : null;
  const col = score == null ? "#7d8eac" : riskColor(score);
  const factors = Array.isArray(d.top_factors) ? d.top_factors.filter(Boolean) : [];

  // la thèse du projet : ce que l'analyse de réseau ajoute au score transactionnel
  let thesis = "";
  if (score != null && solo != null) {
    const delta = score - solo;
    thesis = `<p class="tx-thesis"><b>${solo} sur 100</b> sans analyse de réseau,
      <b>${score} avec</b>.
      ${delta > 0 ? `Le réseau ajoute ${delta} points : c'est l'entourage du virement qui le trahit, pas le virement seul.`
        : delta < 0 ? `Le réseau retire ${-delta} points : le contexte disculpe en partie ce virement.`
        : "Le réseau ne change rien sur ce virement."}</p>`;
  } else if (score != null) {
    thesis = `<p class="tx-thesis">Score transactionnel seul non fourni par le serveur
      (champ <code>score_tx_only</code>), la comparaison n'est pas affichable.</p>`;
  }

  el("tx-title").textContent = d.tx_id || txId;   // textContent : pas d'échappement
  el("tx-body").innerHTML = `
    <div class="tx-score">
      <b style="color:${col}">${score == null ? "—" : score}</b>
      <small>/ 100 · palier ${esc(lbl(LEVEL_LABELS, d.risk_level))}</small>
    </div>
    ${thesis}
    <h3>Le virement</h3>
    <div class="tx-grid">
      <span>Montant</span><span>${fmtAmount(d.amount)}${d.currency && d.currency !== "EUR" ? " " + esc(d.currency) : ""}</span>
      <span>Date</span><span>${esc(fmtDate(d.ts))}</span>
      <span>Émetteur</span><span>${esc(d.src_owner_name ?? "—")}<br/><span class="pa-date">${esc(d.src_account ?? "")}</span></span>
      <span>Destinataire</span><span>${esc(d.dst_owner_name ?? "—")}<br/><span class="pa-date">${esc(d.dst_account ?? "")}</span></span>
      <span>Canal</span><span>${esc(lbl(CHANNEL_LABELS, d.channel))}</span>
      <span>Finalité</span><span>${esc(lbl(TXTYPE_LABELS, d.tx_type))}</span>
    </div>
    <h3>Pourquoi ce virement n'est pas net</h3>
    ${factors.length
      ? `<ul class="tx-factors">${factors.map(f => `<li>${esc(f)}</li>`).join("")}</ul>`
      : `<p class="tx-wait">Le serveur ne renvoie aucun facteur pour ce virement.</p>`}
    ${d.is_fraud != null ? `<p class="pa-truth"><b>Vérité terrain du jeu de test</b> :
      ce virement est ${d.is_fraud ? "frauduleux" : "légitime"}. Étiquette du générateur
      synthétique, elle n'existe pas dans une banque réelle.</p>` : ""}
    <p class="tx-note">Un score élevé signale un comportement à investiguer,
    pas une fraude établie.</p>`;
}

/* ---------- Timeline : FENÊTRE GLISSANTE [début, fin] via double slider ----------
 * Les champs date bornent la plage TOTALE ; le double slider sélectionne une
 * sous-fenêtre. On n'affiche que les liens dont la date tombe dans la fenêtre. */

// plage totale (en ms epoch) definie par les champs date
function dateRangeMs() {
  const ds = el("date-start").value ? new Date(el("date-start").value + "T00:00:00") : new Date(state.tMin);
  const de = el("date-end").value ? new Date(el("date-end").value + "T23:59:59") : new Date(state.tMax);
  return { lo: ds.getTime(), hi: Math.max(de.getTime(), ds.getTime() + 1) };
}

// convertit la position (0..1000) des deux poignees en fenetre temporelle [t0,t1] (ms)
function sliderWindowMs() {
  const { lo, hi } = dateRangeMs();
  let a = parseInt(el("time-min").value, 10);
  let b = parseInt(el("time-max").value, 10);
  if (a > b) { const t = a; a = b; b = t; }     // la poignee min reste <= max
  const span = hi - lo;
  return { t0: lo + span * (a / 1000), t1: lo + span * (b / 1000), a, b };
}

// recalcule le voisinage d'un noeud selectionne a partir des liens DANS la fenetre
function windowNeighbors(node, t0, t1) {
  const g = state.graph, s = new Set([node]);
  const inWin = ts => { const t = new Date(ts).getTime(); return t >= t0 && t <= t1; };
  g.forEachEdge(node, (edge, attr, src, tgt) => {
    if (attr.ts && inWin(attr.ts)) s.add(src === node ? tgt : src);
  });
  return s;
}

// applique la fenetre : masque les liens hors [t0,t1], met a jour la bande + compteur
function applyWindow() {
  const { t0, t1, a, b } = sliderWindowMs();
  const g = state.graph;
  let shown = 0;
  state.edgesByTime.forEach(e => {
    const vis = e.t >= t0 && e.t <= t1;   // e.t déjà en ms (converti au chargement)
    g.setEdgeAttribute(e.key, "_tlHidden", !vis);
    if (vis) shown++;
  });
  state.winT0 = t0; state.winT1 = t1;
  // Les scores par compte dependent de la fenetre : les recalculer ICI est ce
  // qui garantit qu'un compte colore en rouge a bien recu un virement suspect
  // DANS l'intervalle affiche. Mesure a surveiller : ce bloc s'execute aussi
  // 14 fois/s pendant la lecture animee.
  recomputeAgg();
  // si un noeud est selectionne, recalcule son voisinage pour CETTE fenetre
  if (state.selected) {
    state.neighbors = windowNeighbors(state.selected, t0, t1);
    showPanel(state.selected);
  }
  // bande visuelle entre les deux poignees
  el("rs-range").style.left = (a / 10) + "%";
  el("rs-range").style.right = (100 - b / 10) + "%";
  el("time-current").textContent = `${fmtDate(new Date(t0).toISOString())}  ->  ${fmtDate(new Date(t1).toISOString())}`;
  el("tl-count").textContent = `${shown.toLocaleString("fr-FR")} / ${state.edgesByTime.length.toLocaleString("fr-FR")} liens dans la fenêtre`;
  // le nombre d'arêtes au-dessus du seuil dépend aussi de la fenêtre
  updateThresholdUI();
  state.renderer.refresh();
}

/* ---------- Frise cumulative de démo (fonctionnalité 1) ----------
 * Distincte de la lecture animée : la borne de GAUCHE reste sur t_demo_start et
 * la borne de droite avance d'un jour toutes les 2 secondes. C'est une
 * accumulation, pas une fenêtre glissante. À 2 s par image, les 30 à 50 ms
 * d'applyWindow() ne se voient pas : on réutilise le même chemin de code. */
const DAY_MS = 86400000;
let demoTimer = null, demoDay = 0, demoDays = 0;

// yyyy-mm-dd en heure LOCALE (les dates du serveur sont naïves et parsées en local)
function localDay(msEpoch) {
  const d = new Date(msEpoch);
  const p = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function demoBounds() {
  const start = new Date(state.tDemoStart || state.tMin).getTime();
  const end = new Date(state.tMax).getTime();
  return { start, end: Math.max(end, start + DAY_MS) };
}

function toggleDemo() {
  if (demoTimer) { stopDemo(); return; }
  if (playTimer) togglePlay();          // une seule animation à la fois
  const { start, end } = demoBounds();
  // on cadre la plage totale sur [début de test, fin des données] pour que les
  // 1000 crans du double curseur couvrent exactement la période de démo
  el("date-start").value = localDay(start);
  el("date-end").value = localDay(end);
  demoDays = Math.max(1, Math.ceil((end - start) / DAY_MS));
  demoDay = 0;
  el("demo-btn").textContent = "⏹ Arrêter";
  el("demo-btn").classList.add("on");
  stepDemo();
  demoTimer = setInterval(stepDemo, 2000);
}

function stopDemo() {
  if (demoTimer) { clearInterval(demoTimer); demoTimer = null; }
  el("demo-btn").textContent = "⏩ Démo cumulative";
  el("demo-btn").classList.remove("on");
  // la vue reste en place : on ne touche ni au curseur ni à la fenêtre
}

function stepDemo() {
  demoDay++;
  const { start, end } = demoBounds();
  const t1 = Math.min(start + demoDay * DAY_MS, end);
  const { lo, hi } = dateRangeMs();
  const b = Math.round(1000 * (t1 - lo) / Math.max(hi - lo, 1));
  el("time-min").value = 0;                                  // borne gauche FIXE
  el("time-max").value = String(Math.max(0, Math.min(1000, b)));
  const tStep = t0();
  applyWindow();
  el("demo-status").textContent = `jour ${demoDay} sur ${demoDays} · cumul jusqu'au `
    + `${new Date(t1).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" })}`
    + ` (${ms(tStep)})`;
  if (demoDay >= demoDays) stopDemo();
}

let playTimer = null;
function togglePlay() {
  if (playTimer) { clearInterval(playTimer); playTimer = null; el("play-btn").textContent = "▶"; return; }
  el("play-btn").textContent = "⏸";
  // la LARGEUR de fenetre est conservee ; on la fait glisser de gauche a droite
  let a = parseInt(el("time-min").value, 10), b = parseInt(el("time-max").value, 10);
  let width = Math.max(b - a, 40);
  a = 0; b = width;
  el("time-min").value = a; el("time-max").value = b; applyWindow();
  playTimer = setInterval(() => {
    a += 10; b += 10;
    if (b >= 1000) { b = 1000; a = 1000 - width; clearInterval(playTimer); playTimer = null; el("play-btn").textContent = "▶"; }
    el("time-min").value = a; el("time-max").value = b;
    applyWindow();
  }, 70);
}

/* ---------- init ---------- */
function initControls() {
  // Plage par défaut = partition de test, fenêtre ouverte en grand dessus.
  applySplitRange();

  // garde les deux poignées cohérentes (min <= max) et applique la fenêtre
  const mn = el("time-min"), mx = el("time-max");
  mn.addEventListener("input", () => {
    if (parseInt(mn.value, 10) > parseInt(mx.value, 10)) mn.value = mx.value;
    applyWindow();
  });
  mx.addEventListener("input", () => {
    if (parseInt(mx.value, 10) < parseInt(mn.value, 10)) mx.value = mn.value;
    applyWindow();
  });
  el("date-start").addEventListener("change", applyWindow);
  el("date-end").addEventListener("change", applyWindow);
  el("play-btn").addEventListener("click", togglePlay);
  el("demo-btn").addEventListener("click", toggleDemo);
  // bascule entre partition de test seule et historique complet
  el("include-train").checked = state.includeTrain;
  el("include-train").addEventListener("change", e => {
    state.includeTrain = !!e.target.checked;
    if (demoTimer) stopDemo();   // la frise de démo cadre sa propre plage
    applySplitRange();
  });

  // --- seuil d'alerte sur les virements (fonctionnalité 2) ---
  el("edge-threshold").value = String(state.edgeThreshold);
  el("edge-threshold-num").value = String(state.edgeThreshold);
  el("edge-threshold").addEventListener("input", e => setThreshold(e.target.value, { from: "range" }));
  // le champ numérique accepte "80" comme "0.8" ; on ne recale l'affichage
  // qu'au change/blur pour ne pas réécrire sous les doigts de l'utilisateur
  el("edge-threshold-num").addEventListener("change", e => setThreshold(e.target.value, {}));
  el("edge-threshold-num").addEventListener("input", e => {
    const v = parseThreshold(e.target.value);
    if (v != null) setThreshold(v, { from: "num" });
  });
  el("hot-edges").checked = state.hotEdges;
  el("hot-edges").addEventListener("change", e => {
    state.hotEdges = !!e.target.checked;
    state.renderer.refresh();
  });

  // --- agrégateur de score par compte (fonctionnalité 5) ---
  el("agg-mode").value = state.aggMode;
  el("agg-mode").addEventListener("change", e => setAggMode(e.target.value));

  el("txpanel-close").addEventListener("click", () => { state.txReq++; el("txpanel").hidden = true; });

  // premier calcul : agrégats, compteurs et bandeaux
  recomputeAgg();
  updateThresholdUI();

  // soupape de performance : décocher revient au dessin des liens au focus seul
  el("all-edges").checked = state.allEdges;
  el("all-edges").addEventListener("change", e => {
    state.allEdges = !!e.target.checked;
    updateLodBadge();
    state.renderer.refresh();
  });

  // liste des comptes à risque
  el("risklist-btn").addEventListener("click", () => toggleRiskList());
  el("risklist-close").addEventListener("click", () => toggleRiskList(false));
  el("rl-threshold").addEventListener("change", renderRiskList);
  el("reset-view-btn").addEventListener("click", () => state.renderer.getCamera().animatedReset());
  el("panel-close").addEventListener("click", () => selectNode(null));

  // Touche "Backspace" = seul moyen de revenir à la vue générale (depuis une vue
  // isolée). On ignore si l'utilisateur tape dans un champ (recherche, dates).
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Backspace") return;
    const tag = (e.target && e.target.tagName) || "";
    if (tag === "INPUT" || tag === "TEXTAREA") return;
    if (state.selected) { e.preventDefault(); selectNode(null); }
  });

  // recherche par nom / prénom / ID (debounce léger)
  let searchTimer = null;
  const si = el("search-input");
  si.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => runSearch(si.value), 120);
  });
  si.addEventListener("focus", () => { if (si.value.trim().length >= 2) runSearch(si.value); });
  // fermer la liste si on clique ailleurs
  document.addEventListener("click", e => {
    if (!el("search-wrap").contains(e.target)) el("search-results").hidden = true;
  });
}

async function main() {
  try {
    await load();

    setHead("Initialisation du rendu WebGL...");
    const tR = t0();
    await initSigma();     // étape détaillée en sous-phases verbeuses (voir journal)
    initControls();
    updateLodBadge();
    logLine(`[OK] Rendu WebGL initialisé (total étape) en ${ms(tR)} · `
      + `${state.graph.size.toLocaleString("fr-FR")} liens dessinés, aucun filtre de risque`, "ok");
    logLine("<span class='dim'>Astuce : molette = zoom (révèle le voisinage) · clic = focus · slider = frise temporelle</span>");
    state.renderer.getCamera().animatedReset();
    state.renderer.refresh();
    setBar(100);
    await nextFrame();
    // petite pause pour laisser lire la dernière ligne, puis fondu
    setTimeout(() => {
      const o = el("loading");
      o.style.transition = "opacity 0.4s ease";
      o.style.opacity = "0";
      setTimeout(() => { o.style.display = "none"; }, 420);
    }, 800);
  } catch (err) {
    // on NE masque PAS l'overlay : le journal reste affiché avec l'erreur
    setHead("Chargement interrompu");
    logLine("[X] Erreur : " + (err && err.message ? err.message : err), "warn");
    logLine("<span class='dim'>Le journal ci-dessus indique la dernière étape atteinte.</span>");
  }
}

// garde-fou : toute erreur JS imprévue est écrite dans le journal (pas de blocage muet)
window.addEventListener("error", e => {
  try { logLine("[X] JS : " + e.message, "warn"); } catch (_) {}
});
window.addEventListener("unhandledrejection", e => {
  try { logLine("[X] Promesse rejetée : " + (e.reason && e.reason.message || e.reason), "warn"); } catch (_) {}
});

// hook de debug (tests only) : expose l'état et quelques actions
window.__fg = {
  state,
  select: id => selectNode(id),
  setWindow: (aPct, bPct) => { el("time-min").value = aPct; el("time-max").value = bPct; applyWindow(); },
  neighborsOf: (id) => Array.from(neighborsOf(id)),
  // fonctionnalités de démo (utilisées par le harnais de test hors navigateur)
  setThreshold, parseThreshold, setAggMode, aggregate, countHotEdges,
  toggleDemo, stopDemo, demoInfo: () => ({ day: demoDay, days: demoDays, running: !!demoTimer }),
  openEdge: edge => openEdgeDetail(edge),
  showTx: txId => showTxPanel(txId),
  loadAccount: id => loadAccountActivity(id),
  renderRiskList,
  // partition train/test : le harnais hors navigateur vérifie que la plage par
  // défaut démarre bien sur t_demo_start et pas sur t_min
  applySplitRange, updateSplitBadge,
  setIncludeTrain: v => { state.includeTrain = !!v; applySplitRange(); },
};

document.addEventListener("DOMContentLoaded", main);
