/* M2 - Cartographie WebGL façon Obsidian (Sigma.js + graphology).
 *
 * Principes de performance (7060 nœuds / 77 355 liens sur les vraies données) :
 *  - rendu WebGL (Sigma) : la carte graphique dessine, le CPU respire ;
 *  - AUCUN layout navigateur : les positions (x, y) arrivent précalculées du
 *    serveur (backend/module2_graph/layout.py) ;
 *  - timeline = on masque/affiche des liens déjà positionnés, avec les dates
 *    converties en ms UNE fois au chargement (pas de new Date() par image) ;
 *  - focus Obsidian = on joue sur l'opacité (reducers), pas sur la topologie.
 */

const COLORS = { high: "#ff5a5a", mid: "#ffb020", low: "#35d07f" };
// seuils de couleur : rouge >= 50, jaune >= 25, vert sinon
function riskColor(s) { return s >= 50 ? COLORS.high : s >= 25 ? COLORS.mid : COLORS.low; }

const state = {
  graph: null,       // graphology
  renderer: null,    // sigma
  fa2: null,         // worker layout
  edgesByTime: [],   // [{key, t}] trié par t (ms epoch, converti une seule fois)
  tMin: null, tMax: null,
  extent: 1000,      // étendue (x et y) du layout serveur, mesurée au chargement
  riskMin: 0,
  lodThreshold: 50,  // seuil de risque courant selon le zoom (LOD)
  showAll: false,    // "Afficher tous les comptes" : désactive le filtre LOD
  winT0: null, winT1: null,  // fenêtre temporelle courante (ms epoch)
  hovered: null,
  hoveredEdge: null,
  selected: null,
  neighbors: new Set(),
  searchIndex: [],   // [{id, name, score, ct, hay}] pour la recherche nom/prénom
  // MODE "Test IA" : rejeu temporel des détections M3 sur le split test.
  // Quand actif, le graphe N'AFFICHE QUE les comptes des alertes test ;
  // ils sont neutres (gris) puis "s'allument" en rouge à la date réelle.
  testMode: false,
  testAccounts: new Set(),   // tous les comptes concernés par les alertes test
  testRevealed: new Set(),   // comptes déjà "allumés" (détectés) au fil du rejeu
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
  logLine(`  <span class="dim">nœuds=${nf(data.meta.n_nodes)} · liens agrégés=${nf(data.meta.n_edges)} `
    + `(sur ${nf(data.meta.n_edges_raw)} transactions brutes)</span>`);
  logLine(`  <span class="dim">période : ${fmtDate(data.meta.t_min)} -> ${fmtDate(data.meta.t_max)}</span>`);
  setBar(25); await nextFrame();

  const g = new graphology.Graph({ multi: false, type: "directed" });

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
    const base = 1.5 + Math.sqrt(Math.min((n.fi || 0) + (n.fo || 0), 80)) * 0.7;
    g.addNode(n.id, {
      x: n.x, y: n.y, size: base, baseSize: base,
      color: riskColor(n.s), label: n.id,   // le libellé reste l'ID unique
      score: n.s, role: n.r, country: n.ci, ctype: n.ct, fi: n.fi, fo: n.fo,
      ownerName: n.nm, firstName: n.fn, lastName: n.ln,   // identité -> panneau infos
      truthRole: n.tr, truthDecoy: n.td,                  // vérité terrain M1 (affichage)
    });
    // index de recherche : nom/prénom (ou raison sociale) + ID, normalisé
    const displayName = (n.fn || n.ln) ? `${n.fn || ""} ${n.ln || ""}`.trim() : (n.nm || "");
    state.searchIndex.push({
      id: n.id, name: displayName, score: n.s, ct: n.ct,
      hay: `${displayName} ${n.id}`.toLowerCase(),
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
    + `<span class="num">${nf(risky)}</span> à risque ≥ 50 · `
    + `<span class="dim">étendue ${state.extent.toFixed(0)} unités</span>`, "ok");
  await nextFrame();

  // 4) Construction des liens — PAR LOTS
  setHead("Construction des flux...");
  logLine(`>  Ajout des liens + préparation de la frise temporelle...`);
  const tl = [];
  const NE = data.edges.length;
  let added = 0, frauds = 0, skipped = 0;
  const tEdges = t0();
  for (let i = 0; i < NE; i++) {
    const e = data.edges[i];
    if (e.s === e.t || !g.hasNode(e.s) || !g.hasNode(e.t) || g.hasEdge(e.s, e.t)) { skipped++; }
    else {
      const key = g.addEdge(e.s, e.t, {
        size: 0.3 + Math.log10((e.m || 1) + 1) * 0.35,
        color: e.f ? "rgba(255,90,90,0.35)" : "rgba(130,150,180,0.07)",
        ts: e.ts, amount: e.m, count: e.c, fraud: e.f, hidden: false,
        // libellé = montant (+ nb de transactions si agrégées), affiché au survol
        amountLabel: e.c > 1 ? `${fmtAmount(e.m)} · ${e.c} tx` : fmtAmount(e.m),
        label: "",
      });
      added++; if (e.f) frauds++;
      // date convertie en ms UNE SEULE FOIS : applyWindow() est appelée à
      // chaque mouvement de poignée et 14 fois/s en lecture animée. Reparser
      // les 77 355 chaînes ISO à chaque appel coûtait ~25 ms (mesuré), soit
      // un tiers d'un cœur en continu pendant la lecture.
      if (e.ts) { const t = new Date(e.ts).getTime(); if (!isNaN(t)) tl.push({ key, t }); }
    }
    if ((i + 1) % 5000 === 0 || i === NE - 1) {
      setBar(60 + 25 * (i + 1) / NE);
      logLine(`     ${nf(i + 1)} / ${nf(NE)} liens traités  <span class="dim">(${nf(added)} ajoutés)</span>`);
      await nextFrame();
    }
  }
  logLine(`[OK] ${nf(added)} liens ajoutés en ${ms(tEdges)} · `
    + `<span class="num">${nf(frauds)}</span> frauduleux` + (skipped ? ` · ${nf(skipped)} ignorés (doublons/boucles)` : ""), "ok");

  // 5) Frise temporelle
  setHead("Tri de la frise temporelle...");
  const tSort = t0();
  tl.sort((a, b) => a.t - b.t);
  logLine(`[OK] ${nf(tl.length)} liens horodatés triés en ${ms(tSort)}`, "ok");
  setBar(90); await nextFrame();

  state.graph = g;
  state.edgesByTime = tl;
  state.tMin = data.meta.t_min;
  state.tMax = data.meta.t_max;
  logLine(`[OK] Graphe prêt — temps total ${ms(started)}`, "ok");
}

/* Plus de layout navigateur : positions figees cote serveur.
 * Le niveau de detail (LOD) est pilote par le zoom de la camera. */

// seuil de risque minimal AFFICHE selon le zoom (ratio Sigma : grand = dézoomé)
const RISK_OVERVIEW = 50;   // dézoomé -> seulement comptes à risque >= 50 (demande)
function lodRiskThreshold() {
  if (state.showAll) return 0;   // "Afficher tous les comptes" : aucun filtre LOD
  const ratio = state.renderer ? state.renderer.getCamera().ratio : 1;
  // ratio ~>0.7 : vue d'ensemble -> seuil haut ; en zoomant -> seuil qui tombe à 0
  if (ratio >= 0.7) return RISK_OVERVIEW;
  if (ratio >= 0.4) return 25;
  return 0;                 // zoom rapproché : on révèle tout le voisinage local
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
    zIndex: true,
    hideEdgesOnMove: true,   // ne pas dessiner les arêtes pendant pan/zoom (fluidité)
    defaultEdgeColor: "rgba(130,170,230,0.8)",
    minArrowSize: 10,        // taille mini de la pointe de flèche (plus visible)
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
    // MODE "Test IA" : on ne montre QUE les comptes des alertes test. Un compte
    // révélé (détecté) passe en rouge et grossit ; les autres comptes test
    // restent gris neutres ; tout le reste est masqué.
    if (state.testMode) {
      if (!state.testAccounts.has(node)) { res.hidden = true; return res; }
      if (state.testRevealed.has(node)) {
        res.color = COLORS.high; res.size = data.baseSize * 2.0;
        res.zIndex = 2; res.forceLabel = true;
      } else {
        res.color = "rgba(140,160,190,0.5)"; res.size = data.baseSize * 1.1;
        res.label = ""; res.zIndex = 0;
      }
      return res;
    }
    // filtre utilisateur (curseur) ET niveau de détail selon le zoom (LOD)
    const threshold = Math.max(state.riskMin, state.lodThreshold);
    // on garde toujours visibles le focus et ses voisins, même sous le seuil
    // CLIC (selected) : on ne montre QUE le nœud et ses partenaires de la fenêtre.
    if (state.selected) {
      // le compte focalisé reste TOUJOURS visible (on ne perd pas sa sélection)
      if (node === state.selected) { res.size = data.baseSize * 1.7; res.zIndex = 2; res.forceLabel = true; return res; }
      // les partenaires sont filtrés par le curseur "Risque min" (même en vue isolée)
      if (state.neighbors.has(node) && data.score >= state.riskMin) {
        res.zIndex = 1; res.forceLabel = true; return res;
      }
      res.hidden = true; return res;      // tout le reste est masqué
    }
    // SURVOL (hovered) ou vue normale : LOD + estompage doux
    const protectedNode = state.hovered && (node === state.hovered || state.neighbors.has(node));
    if (!protectedNode && data.score < threshold) { res.hidden = true; return res; }
    if (state.hovered) {
      if (node === state.hovered) { res.size = data.baseSize * 1.6; res.zIndex = 2; res.forceLabel = true; }
      else if (state.neighbors.has(node)) { res.zIndex = 1; res.forceLabel = true; }
      else { res.color = "rgba(120,140,170,0.12)"; res.label = ""; res.zIndex = 0; }
    }
    return res;
  });

  state.renderer.setSetting("edgeReducer", (edge, data) => {
    const res = { ...data };
    const g = state.graph;
    // en mode "Test IA" on raconte l'allumage des COMPTES : aucune arête.
    if (state.testMode) { res.hidden = true; return res; }
    const focus = state.selected || state.hovered;
    // OPTIMISATION : aucune arête tant qu'aucun nœud n'est sélectionné/survolé.
    // (les 77k liens ne sont dessinés qu'au focus -> rendu bien plus léger)
    if (!focus) { res.hidden = true; return res; }
    // fenêtre temporelle : masquer les liens hors période
    if (data._tlHidden) { res.hidden = true; return res; }
    // on ne garde que les arêtes incidentes au nœud focalisé
    const [s, t] = g.extremities(edge);
    if (s !== focus && t !== focus) { res.hidden = true; return res; }
    // filtre "Risque min" en vue isolée : masquer les liens vers un partenaire
    // dont le score est sous le seuil (cohérent avec le nodeReducer)
    const other = s === focus ? t : s;
    if (g.getNodeAttribute(other, "score") < state.riskMin) { res.hidden = true; return res; }
    // PRIX : le montant s'affiche sur TOUTES les arêtes du nœud focalisé
    res.label = data.amountLabel;
    if (edge === state.hoveredEdge) {        // survol = mise en évidence
      res.color = "rgba(255,224,138,0.95)";
      res.size = Math.max(data.size, 4); res.zIndex = 3;
    } else {
      res.color = "rgba(130,170,230,0.85)";
      res.size = Math.max(data.size, 3); res.zIndex = 2;
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

  // LOD : quand on zoome/dézoome, recalcule le seuil de risque affiché
  const cam = state.renderer.getCamera();
  cam.on("updated", () => {
    const t = lodRiskThreshold();
    if (t !== state.lodThreshold) { state.lodThreshold = t; state.renderer.refresh(); }
    updateLodBadge();
  });
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

/* ---------- Liste des comptes à risque (SANS plafond) ----------
 * On affiche TOUS les comptes au-dessus du seuil (aucune limite à 500). Pour ne
 * pas figer le navigateur quand la liste est longue (plusieurs centaines de
 * comptes), on rend PAR LOTS : un premier lot immédiat, les suivants ajoutés au
 * défilement (scroll). Un SEUL écouteur de clic (délégation) couvre toute la
 * liste, même les lignes ajoutées après coup. */
const RL_BATCH = 300;   // nombre de lignes ajoutées par lot
const rlState = { items: [], rendered: 0 };

function rlRowHtml(m) {
  const col = riskColor(m.score);
  const name = m.name || "(sans nom)";
  return `<li data-id="${esc(m.id)}">
      <span class="rl-dot" style="background:${col}"></span>
      <span>
        <span class="rl-name">${esc(name)}</span><br/>
        <span class="rl-sub">${esc(m.id)} · ${esc(m.ct ?? "")}</span>
      </span>
      <span class="rl-score" style="color:${col}">${m.score}</span></li>`;
}

// ajoute le prochain lot de lignes (si disponible)
function rlAppendBatch() {
  const ul = el("rl-items");
  const next = rlState.items.slice(rlState.rendered, rlState.rendered + RL_BATCH);
  if (!next.length) return;
  ul.insertAdjacentHTML("beforeend", next.map(rlRowHtml).join(""));
  rlState.rendered += next.length;
}

function renderRiskList() {
  const thr = parseInt(el("rl-threshold").value, 10);
  rlState.items = state.searchIndex
    .filter(e => e.score >= thr)
    .sort((a, b) => b.score - a.score);
  rlState.rendered = 0;
  el("rl-count").textContent = `${rlState.items.length.toLocaleString("fr-FR")} comptes`;
  const ul = el("rl-items");
  ul.innerHTML = "";
  rlAppendBatch();   // premier lot immédiat ; le reste arrive au scroll
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
    const col = riskColor(m.score);   // mêmes seuils (50/25) que le graphe et la liste
    const name = m.name || "(sans nom)";
    return `<li data-id="${esc(m.id)}">
      <span class="sr-dot" style="background:${col}"></span>
      <span class="sr-name">${esc(name)}</span>
      <span class="sr-meta"> · ${esc(m.id)} · ${esc(m.ct ?? "")} · risque ${m.score}</span></li>`;
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

function updateLodBadge() {
  const b = el("lod-badge");
  if (!b) return;
  const t = Math.max(state.riskMin, state.lodThreshold);
  if (state.showAll) { b.textContent = `Affichage : tous les comptes (${state.graph.order.toLocaleString("fr-FR")})`; return; }
  b.textContent = t > 0 ? `Affichage : risque ≥ ${t}` : "Affichage : tous les comptes";
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
  // sélectionner un compte sort proprement du mode "Test IA" (on bascule vers
  // la carte normale centrée sur ce compte).
  if (state.testMode && node) closeTestMode();
  state.selected = node;
  state.hovered = null;
  if (!node) {
    state.neighbors = new Set();
    el("panel").hidden = true;
    state.renderer.refresh();
    state.renderer.getCamera().animatedReset();
    return;
  }
  state.neighbors = neighborsOf(node);
  showPanel(node);
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
  el("p-score").textContent = a.score;
  document.querySelector(".score-ring").style.background =
    `conic-gradient(${riskColor(a.score)} ${a.score * 3.6}deg, #1b2434 0deg)`;

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

  // fi / fo sont des NOMBRES de transactions (fan_in / fan_out), pas des montants
  el("p-attrs").innerHTML = `
    <div><dt>Titulaire</dt><dd>${esc(identite)}</dd></div>
    ${truth ? `<div><dt>Statut réel</dt><dd>${esc(truth)}</dd></div>` : ""}
    <div><dt>Pays</dt><dd>${esc(a.country ?? "—")}</dd></div>
    <div><dt>Type client</dt><dd>${esc(a.ctype ?? "—")}</dd></div>
    <div><dt>Transactions reçues</dt><dd>${a.fi}</dd></div>
    <div><dt>Transactions émises</dt><dd>${a.fo}</dd></div>
    <div><dt>Partenaires (fenêtre)</dt><dd>${Math.max(state.neighbors.size - 1, 0)}</dd></div>`;

  // Fiche d'alerte M3 (si ce compte en a une) : pattern, facteurs, comptes liés.
  renderAccountAlert(node);
}

/* Fiche d'alerte M3 affichée sous les attributs du panneau de détail.
 * Chargée à la demande ; absente si le compte n'a pas d'alerte / M3 inactif. */
async function renderAccountAlert(node) {
  // nettoie toute fiche précédente
  const old = document.getElementById("p-alert");
  if (old) old.remove();
  let data;
  try {
    const r = await fetch(`/api/account/${encodeURIComponent(node)}/alert`);
    if (!r.ok) return;              // 404 = pas d'alerte -> rien à afficher
    data = await r.json();
  } catch (_) { return; }
  // le compte a pu changer pendant le fetch
  if (state.selected !== node) return;
  const al = data.alert || {};
  const factors = (al.top_factors || []).map(f => {
    const label = typeof f === "string" ? f : (f.label || f.name || JSON.stringify(f));
    return `<li>${esc(label)}</li>`;
  }).join("");
  const related = (al.related_accounts || [])
    .filter(id => id && id !== node)
    .map(id => `<span class="pa-chip" data-id="${esc(id)}">${esc(id)}</span>`).join("");
  const box = document.createElement("div");
  box.className = "p-alert";
  box.id = "p-alert";
  box.innerHTML = `
    <h3>Alerte du modèle (M3)</h3>
    <div class="pa-pattern">${esc(al.pattern_label || al.pattern || "motif détecté")}</div>
    ${al.risk_score != null ? `<div class="rl-sub">Score d'alerte : ${esc(al.risk_score)} · ${esc(al.risk_level ?? "")}</div>` : ""}
    ${factors ? `<div class="rl-sub" style="margin-top:6px">Principaux facteurs</div><ul>${factors}</ul>` : ""}
    ${related ? `<div class="rl-sub" style="margin-top:6px">Comptes liés</div><div class="pa-related">${related}</div>` : ""}`;
  el("p-attrs").insertAdjacentElement("afterend", box);
  // clic sur un compte lié -> navigue vers lui
  box.querySelectorAll(".pa-chip[data-id]").forEach(chip => {
    chip.addEventListener("click", () => selectNode(chip.dataset.id));
  });
}

/* ---------- DÉMO : simulation "arnaque à l'instant T" ---------- */
let demoData = null;      // payload de /api/demo mis en cache
let demoTimer = null;

function fmtClock(totalSec) {
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = Math.floor(totalSec % 60);
  const pad = n => String(n).padStart(2, "0");
  return h > 0 ? `${pad(h)}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

async function openDemo() {
  closeTestMode();                 // ne pas superposer les deux modes
  toggleRiskList(false);
  el("demo-overlay").hidden = false;
  if (!demoData) {
    try { demoData = await fetch("/api/demo").then(r => r.json()); }
    catch (_) { demoData = { available: false }; }
  }
  const d = demoData;
  if (!d || !d.available) {
    el("demo-story").textContent =
      "Scénario de démonstration indisponible sur ce jeu de données.";
    el("demo-run").hidden = true;
    return;
  }
  el("demo-run").hidden = false;
  const countries = (d.redistribution_countries || []).join(", ") || "l'étranger";
  // Récit : arnaque fausse voix / vidéo IA. On NE donne PAS de montant médian
  // par victime (virements modérés, sous les seuils de vérification bancaire).
  el("demo-story").innerHTML =
    `Un escroc se fait passer, par <strong>fausse voix ou vidéo générée par IA</strong>, `
    + `pour un proche ou un conseiller. <strong>${d.n_victims}</strong> victimes virent `
    + `chacune une somme modérée (sous les seuils de vérification bancaire) vers un même `
    + `compte collecteur. En quelques heures, les fonds — <strong>${fmtAmount(d.total_collected)}</strong> `
    + `au total — repartent vers ${esc(countries)}.`;
  // réinitialise l'affichage des deux colonnes
  el("demo-clock-bad").textContent = "00:00";
  el("demo-clock-good").textContent = "00:00";
  el("demo-money-bad").textContent = fmtAmount(d.total_collected);
  el("demo-money-good").textContent = fmtAmount(d.total_collected);
  el("demo-money-bad").style.color = "var(--text)";
  el("demo-money-good").style.color = "var(--text)";
  el("demo-verdict").hidden = true;
  el("demo-goto").hidden = true;
}

function closeDemo() {
  if (demoTimer) { clearInterval(demoTimer); demoTimer = null; }
  el("demo-overlay").hidden = true;
}

function runDemo() {
  const d = demoData;
  if (!d || !d.available) return;
  if (demoTimer) { clearInterval(demoTimer); demoTimer = null; }
  el("demo-run").disabled = true;
  el("demo-verdict").hidden = true;
  el("demo-goto").hidden = true;

  // Échelles de temps (réelles) : "sans système" = l'argent s'évapore à
  // hours_until_exit ; "avec système" = alerte à detection_minutes.
  const exitSec = (d.hours_until_exit || 0) * 3600;      // temps réel avant sortie
  const alertSec = (d.detection_minutes || 0) * 60;      // temps réel de détection
  const DURATION_MS = 3200;                              // durée de l'animation
  const start = performance.now();
  const total = d.total_collected || 0;
  const lost = d.already_lost_at_alert || 0;
  const saved = d.salvageable || 0;

  demoTimer = setInterval(() => {
    const p = Math.min((performance.now() - start) / DURATION_MS, 1);
    // Compteur "sans système" : court jusqu'à l'évasion totale.
    const simBad = p * exitSec;
    el("demo-clock-bad").textContent = fmtClock(simBad);
    // l'argent fond : au moment de la sortie, il ne reste rien.
    const remainBad = total * (1 - p);
    el("demo-money-bad").textContent = fmtAmount(Math.max(remainBad, 0));
    el("demo-money-bad").style.color = "var(--high)";

    // Compteur "avec système" : s'arrête à l'alerte (bien plus tôt).
    const simGood = Math.min(p * exitSec, alertSec);
    el("demo-clock-good").textContent = fmtClock(simGood);
    // on sauve ce qui n'était pas encore sorti à l'instant de l'alerte.
    el("demo-money-good").textContent = fmtAmount(saved);
    el("demo-money-good").style.color = "var(--low)";

    if (p >= 1) {
      clearInterval(demoTimer); demoTimer = null;
      el("demo-run").disabled = false;
      const ratioPct = Math.round((d.salvage_ratio || 0) * 100);
      el("demo-verdict").innerHTML =
        `Sans système, la totalité (<strong style="color:var(--high)">${fmtAmount(total)}</strong>) `
        + `s'évapore en ${d.hours_until_exit} h vers ${esc((d.redistribution_countries || []).join(", ") || "l'étranger")}.<br/>`
        + `Avec notre système, l'alerte tombe à T+${d.detection_minutes} min : on gèle et on sauve `
        + `<strong>${fmtAmount(saved)}</strong> (${ratioPct} %)`
        + (lost > 0 ? `, seuls ${fmtAmount(lost)} étaient déjà partis.` : `.`);
      el("demo-verdict").hidden = false;
      el("demo-goto").hidden = false;
    }
  }, 60);
}

function demoGoto() {
  if (!demoData || !demoData.hub) return;
  closeDemo();
  selectNode(demoData.hub);
}

/* ---------- MODE "Test IA" : rejeu temporel sur le split test ---------- */
let testData = null;      // payload de /api/test-timeline mis en cache
let testTimer = null;

async function openTestMode() {
  closeDemo();                      // ne pas superposer avec l'overlay démo
  toggleRiskList(false);
  if (!testData) {
    try { testData = await fetch("/api/test-timeline").then(r => r.json()); }
    catch (_) { testData = { available: false }; }
  }
  if (!testData || !testData.available || !testData.alerts.length) {
    testData = { available: false };
    alert("Mode Test IA indisponible : aucune alerte sur le split test.");
    return;
  }
  state.testMode = true;
  state.testRevealed = new Set();
  state.testAccounts = new Set(testData.alerts.map(a => a.account));
  // on retire tout focus/sélection courant pour un départ propre
  state.selected = null; state.hovered = null; state.neighbors = new Set();
  el("panel").hidden = true;
  el("testai-banner").hidden = false;
  updateTestBanner(null);
  state.renderer.getCamera().animatedReset();
  state.renderer.refresh();
}

function closeTestMode() {
  if (!state.testMode) return;
  if (testTimer) { clearInterval(testTimer); testTimer = null; }
  state.testMode = false;
  state.testRevealed = new Set();
  state.testAccounts = new Set();
  el("testai-banner").hidden = true;
  el("tb-replay").disabled = false;
  if (state.renderer) state.renderer.refresh();
}

function updateTestBanner(ts) {
  el("tb-count").textContent =
    `${state.testRevealed.size} / ${state.testAccounts.size} détectés`;
  el("tb-clock").textContent = ts ? fmtDate(ts) : "prêt — cliquez sur « Rejouer »";
}

function replayTest() {
  if (!testData || !testData.available) return;
  if (testTimer) { clearInterval(testTimer); testTimer = null; }
  // repart de zéro
  state.testRevealed = new Set();
  state.renderer.refresh();
  const alerts = testData.alerts;      // déjà triées par ts côté serveur
  const n = alerts.length;
  // révéler par petits lots pour tenir ~10 s au total quel que soit n
  const TOTAL_MS = 10000, STEP_MS = 180;
  const steps = Math.max(1, Math.round(TOTAL_MS / STEP_MS));
  const perStep = Math.max(1, Math.ceil(n / steps));
  let i = 0;
  el("tb-replay").disabled = true;
  testTimer = setInterval(() => {
    let lastTs = null;
    for (let k = 0; k < perStep && i < n; k++, i++) {
      state.testRevealed.add(alerts[i].account);
      lastTs = alerts[i].ts;
    }
    updateTestBanner(lastTs);
    state.renderer.refresh();
    if (i >= n) {
      clearInterval(testTimer); testTimer = null;
      el("tb-replay").disabled = false;
    }
  }, STEP_MS);
}

/* ---------- Timeline : FENÊTRE GLISSANTE [début, fin] via double slider ----------
 * Les champs date bornent la plage TOTALE ; le double slider sélectionne une
 * sous-fenêtre. On n'affiche que les liens dont la date tombe dans la fenêtre. */

// plage totale (en ms epoch) definie par les champs date
// Frontière officielle train/test du jeu de données M1 (cf. manifest : split_boundary).
// train = début des données -> 25/09 ; test = 25/09 -> fin.
const SPLIT_BOUNDARY = "2026-09-25";

/* Règle les champs date sur la période choisie, remet le double-slider à fond
 * et applique la fenêtre. mode : "all" | "train" | "test". */
function setPeriod(mode) {
  const dMin = state.tMin ? state.tMin.slice(0, 10) : "";
  const dMax = state.tMax ? state.tMax.slice(0, 10) : "";
  if (mode === "train") {
    el("date-start").value = dMin;
    el("date-end").value = SPLIT_BOUNDARY;
  } else if (mode === "test") {
    el("date-start").value = SPLIT_BOUNDARY;
    el("date-end").value = dMax;
  } else {                       // "all"
    el("date-start").value = dMin;
    el("date-end").value = dMax;
  }
  // double-slider ré-ouvert en grand sur la nouvelle plage
  el("time-min").value = 0;
  el("time-max").value = 1000;
  applyWindow();
}

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
  state.renderer.refresh();
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
  // bornes de dates par défaut
  const d0 = state.tMin ? state.tMin.slice(0, 10) : "";
  const d1 = state.tMax ? state.tMax.slice(0, 10) : "";
  el("date-start").value = d0; el("date-end").value = d1;
  // fenêtre ouverte en grand au départ (toute la plage)
  el("time-min").value = 0; el("time-max").value = 1000;
  applyWindow();

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

  // Sélecteur de PÉRIODE : règle les champs date sur train / test / tout,
  // remet le double-slider à fond, puis applique la fenêtre (le masquage des
  // arêtes hors période est déjà géré par applyWindow).
  el("period-select").addEventListener("change", e => setPeriod(e.target.value));
  el("risk-filter").addEventListener("input", e => {
    state.riskMin = parseInt(e.target.value, 10);
    el("risk-filter-val").textContent = e.target.value;
    updateLodBadge();
    state.renderer.refresh();
  });

  // "Afficher tous les comptes" : désactive le filtre LOD (affiche les 7000)
  el("show-all").addEventListener("change", e => {
    state.showAll = e.target.checked;
    state.lodThreshold = lodRiskThreshold();
    updateLodBadge();
    state.renderer.refresh();
  });

  // liste des comptes à risque
  el("risklist-btn").addEventListener("click", () => toggleRiskList());
  el("risklist-close").addEventListener("click", () => toggleRiskList(false));
  el("rl-threshold").addEventListener("change", renderRiskList);
  // UN SEUL écouteur (délégation) : couvre aussi les lignes ajoutées au scroll
  el("rl-items").addEventListener("click", e => {
    const li = e.target.closest("li[data-id]");
    if (li) selectNode(li.dataset.id);
  });
  // rendu progressif : on charge le lot suivant quand on approche du bas
  el("rl-items").addEventListener("scroll", e => {
    const ul = e.target;
    if (ul.scrollTop + ul.clientHeight >= ul.scrollHeight - 120) rlAppendBatch();
  });
  el("reset-view-btn").addEventListener("click", () => state.renderer.getCamera().animatedReset());
  el("panel-close").addEventListener("click", () => selectNode(null));

  // DÉMO : simulation "arnaque à l'instant T"
  el("demo-btn").addEventListener("click", openDemo);
  el("demo-close").addEventListener("click", closeDemo);
  el("demo-run").addEventListener("click", runDemo);
  el("demo-goto").addEventListener("click", demoGoto);

  // MODE "Test IA" : rejeu temporel des détections sur le split test
  el("testai-btn").addEventListener("click", openTestMode);
  el("tb-replay").addEventListener("click", replayTest);
  el("tb-exit").addEventListener("click", closeTestMode);

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
    state.lodThreshold = lodRiskThreshold();
    updateLodBadge();
    logLine(`[OK] Rendu WebGL initialisé (total étape) en ${ms(tR)} · affichage : risque >= ${state.lodThreshold}`, "ok");
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
  openDemo, runDemo, closeDemo,
  openTestMode, replayTest, closeTestMode,
};

document.addEventListener("DOMContentLoaded", main);
