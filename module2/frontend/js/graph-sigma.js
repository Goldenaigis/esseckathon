/* M2 - Cartographie WebGL façon Obsidian (Sigma.js + graphology + ForceAtlas2).
 *
 * Principes de performance (7000 nœuds / ~77k liens) :
 *  - rendu WebGL (Sigma) : la carte graphique dessine, le CPU respire ;
 *  - layout ForceAtlas2 calculé UNE fois dans un worker (ne gèle pas l'UI) ;
 *  - timeline cumulative = on masque/affiche des liens déjà positionnés
 *    (aucune recomputation de layout pendant le scroll) ;
 *  - focus Obsidian = on joue sur l'opacité (reducers), pas sur la topologie.
 */

const COLORS = { high: "#ff5a5a", mid: "#ffb020", low: "#35d07f" };
function riskColor(s) { return s >= 60 ? COLORS.high : s >= 30 ? COLORS.mid : COLORS.low; }

const state = {
  graph: null,       // graphology
  renderer: null,    // sigma
  fa2: null,         // worker layout
  edgesByTime: [],   // [{key, ts}] trié par ts (pour la timeline cumulative)
  tMin: null, tMax: null,
  riskMin: 0,
  cutoffIdx: null,   // index courant dans edgesByTime (cumulatif)
  hovered: null,
  selected: null,
  neighbors: new Set(),
};

const el = id => document.getElementById(id);
const fmtAmount = a => a == null ? "—" :
  new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(a);
const fmtDate = ts => { const d = new Date(ts); return isNaN(d) ? "—" :
  d.toLocaleString("fr-FR", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit" }); };

/* ---------- Chargement + construction du graphe ---------- */
async function load() {
  const data = await fetch("/api/graph/webgl").then(r => r.json());
  el("loading-txt").textContent = `Disposition de ${data.meta.n_nodes} comptes…`;

  const g = new graphology.Graph({ multi: false, type: "directed" });

  // nœuds : position initiale aléatoire en cercle (FA2 fera le reste)
  const N = data.nodes.length;
  data.nodes.forEach((n, i) => {
    const ang = (i / N) * 2 * Math.PI;
    g.addNode(n.id, {
      x: Math.cos(ang) * 100 + Math.random() * 5,
      y: Math.sin(ang) * 100 + Math.random() * 5,
      size: 3 + Math.sqrt(Math.min((n.fi || 0) + (n.fo || 0), 60)) * 1.4,
      baseSize: 3 + Math.sqrt(Math.min((n.fi || 0) + (n.fo || 0), 60)) * 1.4,
      color: riskColor(n.s),
      label: n.id,
      score: n.s, role: n.r, country: n.ci, ctype: n.ct, fi: n.fi, fo: n.fo,
    });
  });

  // liens agrégés ; on garde ts/amount/fraude ; on prépare la timeline
  const tl = [];
  data.edges.forEach(e => {
    if (e.s === e.t || !g.hasNode(e.s) || !g.hasNode(e.t)) return;
    if (g.hasEdge(e.s, e.t)) return; // agrégé côté serveur, mais sécurité
    const key = g.addEdge(e.s, e.t, {
      size: 0.4 + Math.log10((e.m || 1) + 1) * 0.5,
      color: e.f ? "rgba(255,90,90,0.5)" : "rgba(130,150,180,0.18)",
      ts: e.ts, amount: e.m, count: e.c, fraud: e.f,
      hidden: false,
    });
    if (e.ts) tl.push({ key, ts: e.ts });
  });
  tl.sort((a, b) => a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0);

  state.graph = g;
  state.edgesByTime = tl;
  state.tMin = data.meta.t_min;
  state.tMax = data.meta.t_max;
  state.cutoffIdx = tl.length; // tout affiché au départ
}

/* ---------- Layout ForceAtlas2 (worker, une fois) ---------- */
function runLayout(ms = 2500, onDone) {
  if (state.fa2) state.fa2.kill();
  const settings = graphologyLibrary.layoutForceAtlas2.inferSettings(state.graph);
  settings.barnesHutOptimize = true;      // O(n log n) : indispensable à 7000 nœuds
  settings.slowDown = 6;
  settings.gravity = 0.8;
  settings.scalingRatio = 12;
  state.fa2 = new graphologyLibrary.FA2Layout(state.graph, { settings });
  state.fa2.start();
  setTimeout(() => {
    state.fa2.stop();
    state.renderer && state.renderer.refresh();
    state.renderer && state.renderer.getCamera().animatedReset();
    if (onDone) onDone();
  }, ms);
}

/* ---------- Rendu Sigma + effet focus (Obsidian) ---------- */
function initSigma() {
  state.renderer = new Sigma(state.graph, el("sigma"), {
    renderEdgeLabels: false,
    labelRenderedSizeThreshold: 10,   // labels seulement sur gros nœuds / au zoom
    labelFont: "Inter, sans-serif",
    labelColor: { color: "#c9d4e8" },
    defaultEdgeType: "line",
    zIndex: true,
  });

  // reducers = cœur de l'effet Obsidian : estompe tout sauf le focus
  state.renderer.setSetting("nodeReducer", (node, data) => {
    const res = { ...data };
    if (data.score < state.riskMin) { res.hidden = true; return res; }
    const focus = state.selected || state.hovered;
    if (focus) {
      if (node === focus) { res.size = data.baseSize * 1.6; res.zIndex = 2; res.forceLabel = true; }
      else if (state.neighbors.has(node)) { res.zIndex = 1; res.forceLabel = true; }
      else { res.color = "rgba(120,140,170,0.12)"; res.label = ""; res.zIndex = 0; }
    }
    return res;
  });

  state.renderer.setSetting("edgeReducer", (edge, data) => {
    const res = { ...data };
    const g = state.graph;
    // timeline cumulative : masquer les liens postérieurs au curseur
    if (data._tlHidden) { res.hidden = true; return res; }
    const focus = state.selected || state.hovered;
    if (focus) {
      const [s, t] = g.extremities(edge);
      if (s === focus || t === focus) { res.color = "rgba(110,168,254,0.7)"; res.size = Math.max(data.size, 1.2); res.zIndex = 2; }
      else { res.color = "rgba(120,140,170,0.04)"; res.zIndex = 0; }
    }
    return res;
  });

  // survol = focus temporaire (+ resserrement visuel via zoom doux)
  state.renderer.on("enterNode", ({ node }) => { if (!state.selected) setHover(node); });
  state.renderer.on("leaveNode", () => { if (!state.selected) setHover(null); });
  state.renderer.on("clickNode", ({ node }) => selectNode(node));
  state.renderer.on("clickStage", () => selectNode(null));
}

function neighborsOf(node) {
  const s = new Set([node]);
  state.graph.forEachNeighbor(node, n => s.add(n));
  return s;
}

function setHover(node) {
  state.hovered = node;
  state.neighbors = node ? neighborsOf(node) : new Set();
  state.renderer.refresh();
}

/* clic = focus persistant + RESSERREMENT : on recadre la caméra sur le voisinage */
function selectNode(node) {
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
  const graphExtent = 200; // approx de l'étendue totale posée par FA2
  const ratio = Math.max(0.08, Math.min(spanX, spanY) / graphExtent * 1.4);
  const { x, y } = state.renderer.graphToViewport({ x: cx, y: cy });
  // Sigma raisonne en coord normalisées ; on anime vers le centre du voisinage
  const pos = state.renderer.viewportToFramedGraph({ x, y });
  cam.animate({ x: pos.x, y: pos.y, ratio }, { duration: 500 });
}

function showPanel(node) {
  const a = state.graph.getNodeAttributes(node);
  el("panel").hidden = false;
  el("p-id").textContent = node;
  const roleLabels = {
    collector: "Compte collecteur (étoile)", collector_redistributor: "Collecte + redistribution",
    smurf_target: "Cible de fractionnement", relay: "Maillon de chaîne",
    cycle_member: "Membre d'un cycle", normal: "Comportement normal",
  };
  el("p-role").textContent = roleLabels[a.role] || a.role || "—";
  el("p-score").textContent = a.score;
  document.querySelector(".score-ring").style.background =
    `conic-gradient(${riskColor(a.score)} ${a.score * 3.6}deg, #1b2434 0deg)`;
  el("p-attrs").innerHTML = `
    <div><dt>Pays</dt><dd>${a.country ?? "—"}</dd></div>
    <div><dt>Type client</dt><dd>${a.ctype ?? "—"}</dd></div>
    <div><dt>Flux entrants</dt><dd>${a.fi}</dd></div>
    <div><dt>Flux sortants</dt><dd>${a.fo}</dd></div>
    <div><dt>Voisins</dt><dd>${state.neighbors.size - 1}</dd></div>`;
}

/* ---------- Timeline cumulative (positions fixes) ---------- */
function applyTimeline(cutIdx) {
  state.cutoffIdx = cutIdx;
  const g = state.graph;
  // tout masquer d'abord via flag, puis révéler jusqu'au curseur
  state.edgesByTime.forEach((e, i) => {
    g.setEdgeAttribute(e.key, "_tlHidden", i >= cutIdx);
  });
  const shown = cutIdx;
  const curTs = cutIdx > 0 ? state.edgesByTime[Math.min(cutIdx, state.edgesByTime.length) - 1].ts : state.tMin;
  el("time-current").textContent = fmtDate(curTs);
  el("tl-count").textContent = `${shown.toLocaleString("fr-FR")} / ${state.edgesByTime.length.toLocaleString("fr-FR")} liens affichés (cumulatif)`;
  state.renderer.refresh();
}

/* borne la timeline entre deux dates choisies, puis mappe le slider dessus */
function timelineBounds() {
  const ds = el("date-start").value ? new Date(el("date-start").value).toISOString() : state.tMin;
  const de = el("date-end").value ? new Date(el("date-end").value + "T23:59:59").toISOString() : state.tMax;
  // indices des liens dans [ds, de]
  const inRange = state.edgesByTime.filter(e => e.ts >= ds && e.ts <= de);
  return { ds, de, inRange };
}

function onSlider() {
  const { inRange } = timelineBounds();
  const frac = parseInt(el("time-slider").value, 10) / 1000;
  // les liens hors bornes restent masqués ; dans les bornes on révèle jusqu'à frac
  const cutInRange = Math.round(frac * inRange.length);
  const g = state.graph;
  const rangeKeys = new Set(inRange.slice(0, cutInRange).map(e => e.key));
  const outKeys = new Set(inRange.map(e => e.key));
  let shown = 0;
  state.edgesByTime.forEach(e => {
    const visible = rangeKeys.has(e.key);
    g.setEdgeAttribute(e.key, "_tlHidden", !visible);
    if (visible) shown++;
  });
  const curTs = cutInRange > 0 ? inRange[cutInRange - 1].ts : (inRange[0] && inRange[0].ts) || state.tMin;
  el("time-current").textContent = fmtDate(curTs);
  el("tl-count").textContent = `${shown.toLocaleString("fr-FR")} / ${inRange.length.toLocaleString("fr-FR")} liens (dans la période)`;
  state.renderer.refresh();
}

let playTimer = null;
function togglePlay() {
  if (playTimer) { clearInterval(playTimer); playTimer = null; el("play-btn").textContent = "▶"; return; }
  el("play-btn").textContent = "⏸";
  const slider = el("time-slider");
  slider.value = 0; onSlider();
  playTimer = setInterval(() => {
    let v = parseInt(slider.value, 10) + 12;
    if (v >= 1000) { v = 1000; clearInterval(playTimer); playTimer = null; el("play-btn").textContent = "▶"; }
    slider.value = v; onSlider();
  }, 60);
}

/* ---------- init ---------- */
function initControls() {
  // bornes de dates par défaut
  const d0 = state.tMin ? state.tMin.slice(0, 10) : "";
  const d1 = state.tMax ? state.tMax.slice(0, 10) : "";
  el("date-start").value = d0; el("date-end").value = d1;
  el("time-slider").value = 1000;
  onSlider();

  el("time-slider").addEventListener("input", onSlider);
  el("date-start").addEventListener("change", onSlider);
  el("date-end").addEventListener("change", onSlider);
  el("play-btn").addEventListener("click", togglePlay);
  el("risk-filter").addEventListener("input", e => {
    state.riskMin = parseInt(e.target.value, 10);
    el("risk-filter-val").textContent = e.target.value;
    state.renderer.refresh();
  });
  el("layout-btn").addEventListener("click", () => runLayout());
  el("reset-view-btn").addEventListener("click", () => state.renderer.getCamera().animatedReset());
  el("panel-close").addEventListener("click", () => selectNode(null));
}

async function main() {
  await load();
  initSigma();
  initControls();
  el("loading-txt").textContent = `Disposition de ${state.graph.order} comptes…`;
  // on masque l'overlay quand le layout est terminé (voir runLayout -> onDone)
  runLayout(2800, () => { el("loading").style.display = "none"; });
}

document.addEventListener("DOMContentLoaded", main);
