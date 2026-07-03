/* Calcio AI — Analytics Board · logica frontend + grafici Plotly */
"use strict";

let LEAGUES = [];
let CURRENT = null;
let TAB = "fixtures";

const $ = id => document.getElementById(id);
const fmt = (x, d = 2) => Number(x).toFixed(d);
const PLOTLY_LAYOUT = {
  paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
  font: { color: "#8b96ad", family: "Segoe UI, sans-serif", size: 12 },
  margin: { t: 30, r: 20, b: 40, l: 60 },
};
const GREEN = "#22c55e", BLUE = "#3b82f6";

function toast(msg) {
  const t = $("toast");
  t.textContent = msg; t.style.display = "block";
  setTimeout(() => (t.style.display = "none"), 6000);
}

async function api(path) {
  const res = await fetch(path);
  const data = await res.json().catch(() => ({ errore: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(data.errore || `HTTP ${res.status}`);
  return data;
}

const dateFmt = iso => iso ? new Date(iso).toLocaleString("it-IT",
  { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";

/* Banner quando i risultati mostrati sono dell'ultima stagione giocata
   (la stagione preferita — es. 2026-27 — non è ancora iniziata) */
const planBanner = d => d.piano_limitato ? `
  <div class="panel banner">📅 Risultati e classifica della stagione <b>${d.season}</b>
  (l'ultima disputata). Il calendario delle prossime partite è già quello
  <b>${d.stagione_corrente}</b>: appena inizia, risultati, classifica e tabelloni
  passano automaticamente ai dati in tempo reale.</div>` : "";

/* ------------------------------------------------------------- bootstrap */
async function init() {
  try {
    const data = await api("/api/leagues");
    LEAGUES = data.leagues;
    const sel = $("leagueSelect");
    sel.innerHTML = LEAGUES.map(l =>
      `<option value="${l.key}">${l.icona} ${l.nome}${l.season ? " · " + l.season : ""}</option>`).join("");
    sel.onchange = () => { CURRENT = sel.value; render(); };
    CURRENT = LEAGUES[0].key;
    const acc = data.account || {};
    if (acc.piano) $("accountBadge").innerHTML =
      `dati <b>${acc.piano}</b><br>micro-eventi: ${acc.micro || "n/d"} · agg. ${acc.aggiornato || "?"}`;
    document.querySelectorAll(".tab").forEach(b => b.onclick = () => {
      document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
      b.classList.add("active"); TAB = b.dataset.tab; render();
    });
    render();
  } catch (e) {
    $("content").innerHTML = `<div class="panel">⚠️ ${e.message}</div>`;
  }
}

function render() {
  if (TAB === "fixtures") renderFixtures();
  else if (TAB === "standings") renderStandings();
  else renderBracket();
}

/* -------------------------------------------------------------- partite */
async function renderFixtures() {
  $("content").innerHTML = `<div class="loading">Carico le partite…</div>`;
  try {
    const [next, last] = await Promise.all([
      api(`/api/fixtures?league=${CURRENT}&mode=next&n=18`),
      api(`/api/fixtures?league=${CURRENT}&mode=last&n=6`),
    ]);
    const card = (f, played) => `
      <div class="fx-card">
        <div class="fx-meta"><span>${f.round || ""}</span><span>${dateFmt(f.date)}</span></div>
        <div class="fx-teams">
          <div class="fx-team"><img src="${f.home.logo}" alt=""><span class="nm">${f.home.name}</span></div>
          <div class="fx-score ${played ? "" : "live"}">${played ? f.gh + " - " + f.ga : "vs"}</div>
          <div class="fx-team right"><img src="${f.away.logo}" alt=""><span class="nm">${f.away.name}</span></div>
        </div>
        <button class="btn block" onclick="openAnalysis(${f.fixture_id})">📈 Analizza (10.000 sim)</button>
      </div>`;
    let html = planBanner(next);
    if (next.fixtures.length)
      html += `<div class="panel" style="margin-bottom:14px"><h3>Prossime partite</h3>
        <div class="fx-grid">${next.fixtures.map(f => card(f, false)).join("")}</div></div>`;
    if (last.fixtures.length)
      html += `<div class="panel"><h3>Ultimi risultati</h3>
        <div class="fx-grid">${last.fixtures.map(f => card(f, true)).join("")}</div></div>`;
    $("content").innerHTML = html ||
      `<div class="panel">Nessuna partita in programma per questa competizione.</div>`;
  } catch (e) { $("content").innerHTML = `<div class="panel">⚠️ ${e.message}</div>`; }
}

/* ------------------------------------------------------------ classifica */
async function renderStandings() {
  $("content").innerHTML = `<div class="loading">Carico la classifica…</div>`;
  try {
    const data = await api(`/api/standings?league=${CURRENT}`);
    if (!data.groups.length) {
      $("content").innerHTML = `<div class="panel">Classifica non disponibile.</div>`; return;
    }
    const banner = planBanner(data);
    const formHtml = f => (f || "").split("").map(c =>
      c === "W" ? "<b>V</b>" : c === "L" ? "<s>P</s>" : "<i>N</i>").join(" ");
    $("content").innerHTML = banner + `<div class="groups">` + data.groups.map(g => `
      <div class="panel"><h3>${g.nome}</h3>
      <table><thead><tr><th>#</th><th class="name">Squadra</th><th>Pt</th><th>G</th>
        <th>V</th><th>N</th><th>P</th><th>DR</th><th>Forma</th></tr></thead><tbody>
      ${g.rows.map(r => {
        const d = (r.descrizione || "").toLowerCase();
        const cls = d.includes("champions") || d.includes("next round") || d.includes("knockout")
          ? "q1" : d.includes("europa") || d.includes("play") ? "q2"
          : d.includes("relegation") ? "q3" : "";
        return `<tr class="${cls}"><td>${r.rank}</td>
          <td class="name"><img src="${r.logo}" alt="">${r.team}</td>
          <td class="pt">${r.points}</td><td>${r.played}</td><td>${r.win}</td>
          <td>${r.draw}</td><td>${r.lose}</td><td>${r.diff > 0 ? "+" : ""}${r.diff}</td>
          <td class="form">${formHtml(r.form)}</td></tr>`;
      }).join("")}</tbody></table></div>`).join("") + `</div>`;
  } catch (e) { $("content").innerHTML = `<div class="panel">⚠️ ${e.message}</div>`; }
}

/* ------------------------------------------------------------- tabellone */
async function renderBracket() {
  $("content").innerHTML = `<div class="loading">Ricostruisco il tabellone…</div>`;
  try {
    const data = await api(`/api/bracket?league=${CURRENT}`);
    if (!data.rounds.length) {
      $("content").innerHTML = `<div class="panel">Nessuna fase a eliminazione
        diretta disponibile (torneo non iniziato o solo fase campionato).</div>`;
      return;
    }
    const row = (t, gh, other) => {
      const win = t.winner === true;
      return `<div class="trow ${win ? "win" : ""}">
        <img src="${t.logo}" alt=""><span class="tn">${t.name}</span>
        <span class="ts">${gh ?? "–"}</span></div>`;
    };
    $("content").innerHTML = planBanner(data) + `<div class="bracket">` + data.rounds.map(r => `
      <div class="roundcol"><h4>${r.nome}</h4><div class="ties">
      ${r.partite.map(m => `
        <div class="tie">
          ${row(m.home, m.gh)}${row(m.away, m.ga)}
          ${m.rigori ? `<div class="tie-foot"><span class="dt">rigori ${m.rigori.home}-${m.rigori.away}</span></div>` : ""}
          <div class="tie-foot"><span class="dt">${dateFmt(m.date)} · ${m.status || ""}</span>
            <button class="btn mini" onclick="openAnalysis(${m.fixture_id})">📈 Analizza</button>
          </div>
        </div>`).join("")}
      </div></div>`).join("") + `</div>`;
  } catch (e) { $("content").innerHTML = `<div class="panel">⚠️ ${e.message}</div>`; }
}

/* --------------------------------------------------------------- analisi */
async function openAnalysis(fixtureId) {
  const mode = $("last10Toggle").checked ? "last10" : "season";
  $("anHeader").innerHTML = "";
  $("anBody").innerHTML = `<div class="loading">Eseguo 10.000 simulazioni Monte Carlo…</div>`;
  $("pdfBtn").href = `/api/report?fixture=${fixtureId}&players=${mode}`;
  $("analysisOverlay").classList.add("show");
  try {
    const d = await api(`/api/simulate?fixture=${fixtureId}&players=${mode}`);
    renderAnalysis(d);
  } catch (e) {
    $("anBody").innerHTML = `<div class="panel">⚠️ ${e.message}</div>`;
  }
}
function closeAnalysis() { $("analysisOverlay").classList.remove("show"); }

function renderAnalysis(d) {
  const m = d.meta, sim = d.sim, meteo = d.meteo, prof = d.profili;
  const H = m.home.name, A = m.away.name;

  // header + badge meteo/quote
  const meteoBadge = !meteo.disponibile
    ? `<span class="badge">🌡 meteo n/d</span>`
    : meteo.estremo
      ? `<span class="badge alert">⛈ ${meteo.condizione} ${meteo.temperatura}°C — modello corretto: −5% precisione tiri, +10% falli</span>`
      : `<span class="badge ok">☀ ${meteo.condizione} · ${meteo.temperatura}°C</span>`;
  const oddsBadge = d.odds.bookmaker
    ? `<span class="badge">💰 quote ${d.odds.bookmaker}: ${d.odds.markets["1"] ?? "-"} / ${d.odds.markets["X"] ?? "-"} / ${d.odds.markets["2"] ?? "-"}</span>`
    : `<span class="badge">💰 quote non disponibili</span>`;
  $("anHeader").innerHTML = `
    <div class="match-title"><img src="${m.home.logo}" alt=""> ${H}
      <span style="color:var(--dim)">vs</span> ${A} <img src="${m.away.logo}" alt=""></div>
    <div class="match-sub">${m.league} · ${m.round} · ${dateFmt(m.date)}${
      m.venue ? ` · ${m.venue}${m.city ? " (" + m.city + ")" : ""}` : ""} · statistiche giocatori:
      <b>${(prof.home.players_mode || "").includes("forma") ? "forma ultime 10 reali" : "stagione nel torneo"}</b></div>
    <div class="badges">${meteoBadge}${oddsBadge}
      <span class="badge">🧤 ${prof.home.keeper.name}: SR ${fmt(prof.home.keeper.save_rate * 100, 1)}%${prof.home.keeper.saves_pg != null ? " · " + prof.home.keeper.saves_pg + " parate/g" : ""}</span>
      <span class="badge">🧤 ${prof.away.keeper.name}: SR ${fmt(prof.away.keeper.save_rate * 100, 1)}%${prof.away.keeper.saves_pg != null ? " · " + prof.away.keeper.saves_pg + " parate/g" : ""}</span>
    </div>`;

  const o = sim.outcomes;
  const kpis = [
    [`1 · ${H}`, fmt(o["1"]) + "%"], ["X", fmt(o["X"]) + "%"], [`2 · ${A}`, fmt(o["2"]) + "%"],
    ["BTTS", fmt(sim.btts) + "%"], ["Over 2.5", fmt(sim.over["2.5"]) + "%"],
    [`xG ${H}`, sim.xg.home], [`xG ${A}`, sim.xg.away],
    ["Corner tot.", sim.corners.mean_total], ["Cartellini", sim.cards.mean_total],
  ].map(([l, v]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");

  // scorer boards (marcatori con barre)
  const scorerBoard = (list, cls) => list.slice(0, 9).map(r => `
    <div class="scorer-row">
      <div class="nm">${r.name}${r.penalty_taker ? ' <small title="rigorista">®</small>' : ""}${r.super_sub ? ' <small title="super-sub: impatto 70-90esimo">⚡</small>' : ""}</div>
      <div class="track"><div class="fill ${cls}" style="width:${Math.min(r.anytime * 1.8, 100)}%"></div></div>
      <div class="pc">${fmt(r.anytime)}%</div>
      <div class="extra">2+: ${fmt(r.brace, 1)}% · 70-90': ${fmt(r.late_20, 1)}% · q.${r.fair_odds ?? "—"}</div>
    </div>`).join("");

  // tabelle giocatori (gol, tiri, assist / portiere)
  const ptable = (players, keeper) => `
    <table class="ptable"><thead><tr><th class="name">Giocatore</th><th>Gol</th>
    <th>Tiri</th><th>In porta</th><th>Assist</th><th>Min</th></tr></thead><tbody>
    ${players.slice(0, 8).map(p => `<tr><td class="name">${p.name}</td>
      <td>${p.goals}</td><td>${p.shots}</td><td>${p.shots_on}</td>
      <td>${p.assists}</td><td>${p.minutes}</td></tr>`).join("")}
    </tbody></table>
    <div class="note">🧤 ${keeper.name} — parate/partita: <b>${keeper.saves_pg ?? "n/d"}</b> ·
      Save Rate: <b>${fmt(keeper.save_rate * 100, 1)}%</b></div>`;

  // value bets
  const vb = d.value_bets.length ? `
    <table class="ptable"><thead><tr><th class="name">Mercato</th><th>Quota</th>
    <th>Modello</th><th>Implicita</th><th>Edge</th><th></th></tr></thead><tbody>
    ${d.value_bets.map(b => `<tr><td class="name">${b.mercato}</td><td>${fmt(b.quota)}</td>
      <td>${fmt(b.prob_modello, 1)}%</td><td>${fmt(b.prob_implicita, 1)}%</td>
      <td class="${b.edge > 0 ? "vb-edge-pos" : "vb-edge-neg"}">${b.edge > 0 ? "+" : ""}${fmt(b.edge, 1)}%</td>
      <td>${b.value ? '<span class="vb-yes">VALUE</span>' : ""}</td></tr>`).join("")}
    </tbody></table>
    <div class="note">Value = probabilità del modello superiore di ≥2 punti alla probabilità implicita della quota.</div>`
    : `<div class="note">Quote bookmaker non disponibili per questa partita (l'endpoint /odds copre i match più vicini al calcio d'inizio).</div>`;

  $("anBody").innerHTML = `
    <div class="kpis">${kpis}</div>
    <div class="an-grid">
      <div class="panel wide"><h3>Matrice risultati esatti (%) — distribuzione su 10.000 sim</h3>
        <div id="chMatrix" class="chart" style="min-height:360px"></div></div>
      <div class="panel"><h3>Confronto micro-eventi attesi</h3>
        <div id="chCompare" class="chart"></div></div>
      <div class="panel"><h3>Volume di tiro — i giocatori più caldi</h3>
        <div id="chShooters" class="chart"></div></div>
      <div class="panel"><h3>⚽ Tabellone marcatori — ${H}</h3>${scorerBoard(sim.scorers.home, "")}</div>
      <div class="panel"><h3>⚽ Tabellone marcatori — ${A}</h3>${scorerBoard(sim.scorers.away, "away")}</div>
      <div class="panel"><h3>Statistiche giocatori — ${H}</h3>${ptable(sim.scorers.home, prof.home.keeper)}</div>
      <div class="panel"><h3>Statistiche giocatori — ${A}</h3>${ptable(sim.scorers.away, prof.away.keeper)}</div>
      <div class="panel wide"><h3>💎 Value Bets — modello vs bookmaker</h3>${vb}</div>
    </div>`;

  // --- Plotly: matrice risultati esatti (heatmap)
  const labels = ["0", "1", "2", "3", "4", "5+"];
  Plotly.newPlot("chMatrix", [{
    z: sim.score_matrix, x: labels, y: labels, type: "heatmap",
    colorscale: [[0, "#0f1524"], [0.5, "#14532d"], [1, GREEN]],
    text: sim.score_matrix.map(r => r.map(v => v.toFixed(1) + "%")),
    texttemplate: "%{text}", hovertemplate: `${H} %{y} - %{x} ${A}: %{z}%<extra></extra>`,
  }], {
    ...PLOTLY_LAYOUT, margin: { t: 10, r: 10, b: 45, l: 55 },
    xaxis: { title: `Gol ${A}` }, yaxis: { title: `Gol ${H}`, autorange: "reversed" },
  }, { displayModeBar: false, responsive: true });

  // --- Plotly: confronto corner/falli/cartellini/tiri
  const cats = ["Tiri", "Tiri in porta", "Corner", "Falli", "Ammonizioni", "Parate"];
  Plotly.newPlot("chCompare", [
    { x: cats, y: [sim.shots.mean_home, sim.shots.sot_home, sim.corners.mean_home,
                   sim.fouls.mean_home, sim.cards.yellows_home, sim.saves.mean_home],
      name: H, type: "bar", marker: { color: GREEN } },
    { x: cats, y: [sim.shots.mean_away, sim.shots.sot_away, sim.corners.mean_away,
                   sim.fouls.mean_away, sim.cards.yellows_away, sim.saves.mean_away],
      name: A, type: "bar", marker: { color: BLUE } },
  ], { ...PLOTLY_LAYOUT, barmode: "group", legend: { orientation: "h", y: 1.15 } },
    { displayModeBar: false, responsive: true });

  // --- Plotly: tiratori più caldi (tiri effettuati, colore per squadra)
  const hot = [
    ...sim.scorers.home.slice(0, 6).map(p => ({ ...p, team: H, color: GREEN })),
    ...sim.scorers.away.slice(0, 6).map(p => ({ ...p, team: A, color: BLUE })),
  ].sort((a, b) => a.shots - b.shots);
  Plotly.newPlot("chShooters", [{
    y: hot.map(p => `${p.name} (${p.team.slice(0, 3).toUpperCase()})`),
    x: hot.map(p => p.shots), type: "bar", orientation: "h",
    marker: { color: hot.map(p => p.color) },
    text: hot.map(p => `${p.shots} tiri · ${p.shots_on} in porta`),
    textposition: "auto", hovertemplate: "%{y}: %{x} tiri<extra></extra>",
  }], { ...PLOTLY_LAYOUT, margin: { t: 10, r: 20, b: 40, l: 170 } },
    { displayModeBar: false, responsive: true });
}

init();
