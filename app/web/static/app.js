// Общие helpers фронта
const API = "/api";

async function getJSON(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function sendJSON(path, method, body) {
  const r = await fetch(API + path, {
    method, headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

const pct = (x, d = 1) => (x === null || x === undefined) ? "—" : (x * 100).toFixed(d) + "%";
const pctSigned = (x, d = 1) => (x === null || x === undefined) ? "—"
  : `<span class="${x >= 0 ? "pos" : "neg"}">${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)}%</span>`;
const num = (x, d = 2) => (x === null || x === undefined) ? "—" : Number(x).toFixed(d);

function sigClass(s) {
  if (s === "ПОКУПАЙ") return "buy";
  if (s === "ГРАНИЦА") return "edge";
  return "avoid";
}
function sigBadge(s) { return `<span class="sig ${sigClass(s)}">${s}</span>`; }

// Глобальные переключатели режима и дефлятора (мгновенный пересчёт через settings)
async function initHeaderControls() {
  // подсветка активной ссылки
  document.querySelectorAll("header nav a").forEach(a => {
    if (a.getAttribute("href") === location.pathname) a.classList.add("active");
  });
  const regimeSel = document.getElementById("g-regime");
  const deflSel = document.getElementById("g-deflator");
  const horizonSel = document.getElementById("g-horizon");
  if (!regimeSel) return;
  try {
    const s = await getJSON("/settings");
    regimeSel.value = s.regime;
    deflSel.value = s.deflator_preset;
    if (horizonSel) horizonSel.value = String(s.forecast_years);
    const lbl = document.getElementById("g-deflator-val");
    if (lbl) lbl.textContent = "(" + pct(s.deflator_active) + ")";
  } catch (e) { console.warn(e); }
  regimeSel.addEventListener("change", async () => {
    await sendJSON("/settings", "PUT", { regime: regimeSel.value });
    location.reload();
  });
  deflSel.addEventListener("change", async () => {
    await sendJSON("/settings", "PUT", { deflator_preset: deflSel.value });
    location.reload();
  });
  if (horizonSel) horizonSel.addEventListener("change", async () => {
    await sendJSON("/settings", "PUT", { forecast_years: parseInt(horizonSel.value) });
    location.reload();
  });
}
document.addEventListener("DOMContentLoaded", initHeaderControls);
