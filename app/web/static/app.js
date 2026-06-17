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

// ── глоссарий: тултипы-расшифровки аббревиатур (наведение → title) ──
const GLOSSARY = {
  "ROIC−WACC": "Спред: отдача на инвестированный капитал (ROIC) минус его стоимость (WACC). Насколько бизнес зарабатывает СВЕРХ цены капитала — создаёт ли стоимость.",
  "ROIC-WACC": "Спред: отдача на инвестированный капитал минус его стоимость. Насколько бизнес зарабатывает сверх цены капитала.",
  "ROIC": "Return on Invested Capital — отдача на весь инвестированный капитал (собственный + заёмный).",
  "WACC": "Weighted Average Cost of Capital — средневзвешенная стоимость капитала (цена денег для бизнеса).",
  "ROE": "Return on Equity — рентабельность собственного капитала (прибыль / капитал акционеров).",
  "CoE": "Cost of Equity — стоимость собственного капитала (требуемая доходность акционера).",
  "TAM": "Total Addressable Market — общий потенциальный объём рынка.",
  "P/E": "Price / Earnings — цена акции к прибыли на акцию.",
  "P/B": "Price / Book — цена к собственному капиталу (балансовой стоимости).",
  "ФНБ": "Фонд национального благосостояния — суверенный резерв РФ.",
  "IMOEX": "Индекс Мосбиржи — основной индекс рынка акций РФ.",
  "Urals": "Эталонный сорт российской экспортной нефти.",
  "Payout": "Доля чистой прибыли, выплачиваемая дивидендами.",
  "payout": "Доля чистой прибыли, выплачиваемая дивидендами.",
};
function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function glossarize(text) {
  const out = escapeHtml(text);
  const terms = Object.keys(GLOSSARY).sort((a, b) => b.length - a.length)
    .map(t => t.replace(/[.*+?^${}()|[\]\\/-]/g, "\\$&"));
  const re = new RegExp("(" + terms.join("|") + ")", "g");
  return out.replace(re, m => `<abbr class="gl" title="${GLOSSARY[m].replace(/"/g, "&quot;")}">${m}</abbr>`);
}

// ── оценка метрик (правила; банк-aware спред). Общая логика для карточки и скринера ──
function metricEvalRows(x) {
  const rows = [];
  const sp = x.classification ? x.classification.roic_minus_wacc : null;
  const roe = x.inputs.roe.value;
  if (roe != null) {
    let l, c;
    if (sp != null && sp < 0) {
      l = "завышен · спред<0"; c = "edge";   // ROE при ROIC<WACC вводит в заблуждение
    } else {
      [l, c] = roe >= 0.25 ? ["очень сильно", "buy"] : roe >= 0.15 ? ["сильно", "buy"]
             : roe >= 0.08 ? ["средне", "edge"] : ["слабо", "avoid"];
    }
    rows.push({ k: "ROE", v: pct(roe), label: l, cls: c });
  }
  if (sp != null) {
    const bank = x.sector === "Банк";
    let l, c, name;
    if (bank) {
      name = "Спред ROE − CoE";
      [l, c] = sp >= 0.05 ? ["очень сильно", "buy"] : sp >= 0.02 ? ["создаёт стоимость", "buy"]
             : sp >= 0 ? ["умеренно положительный", "edge"] : ["разрушает стоимость", "avoid"];
    } else {
      name = "Спред ROIC − WACC";
      [l, c] = sp >= 0.10 ? ["создаёт стоимость", "buy"] : sp >= 0.03 ? ["хорошо", "buy"]
             : sp >= 0 ? ["околонулевой", "edge"] : ["разрушает стоимость", "avoid"];
    }
    rows.push({ k: name, v: `${sp >= 0 ? "+" : ""}${(sp * 100).toFixed(1)} пп`, label: l, cls: c });
  }
  const di = x.inputs.div_yield, dy = di.value;
  if (dy != null && dy > 0) {
    if (di.spike) {
      // разовый дивиденд: показываем факт + устойчивую (на ней калиброван сигнал)
      const sv = di.signal_value != null ? di.signal_value : 0;
      rows.push({ k: "Дивдоходность", v: `${pct(dy)} → устойч. ${pct(sv)}`, label: "разовая · спайк", cls: "edge" });
    } else {
      const [l, c] = dy >= 0.12 ? ["высокая", "buy"] : dy >= 0.06 ? ["умеренная", "edge"] : ["низкая", "neu"];
      rows.push({ k: "Дивдоходность", v: pct(dy), label: l, cls: c });
    }
  }
  const po = x.inputs.payout.value;
  if (po != null) {
    const l = po >= 0.6 ? "зрелый кэш-возврат" : po >= 0.3 ? "сбалансированный" : "реинвест / рост";
    rows.push({ k: "Payout", v: pct(po), label: l, cls: "neu" });
  }
  return rows;
}
function metricEvalRowsHTML(x) {
  return metricEvalRows(x).map(r =>
    `<div class="meval-row"><span class="mk">${glossarize(r.k)}</span><span class="mv">${r.v}</span>` +
    `<span class="mverd ${r.cls}">${r.cls !== "neu" ? '<span class="dot"></span>' : ""}${r.label}</span></div>`
  ).join("");
}

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

// ── ФНБ-маркер режима рынка в шапке (зелёный/жёлтый/красный + раскрытие метрик) ──
const REGIME_RU = { NORMAL: "Норма", RISK: "Риск", SHOCK: "Шок" };
const REGIME_CLS = { NORMAL: "buy", RISK: "edge", SHOCK: "avoid" };

function nwfRow(k, v, cls) {
  const dot = cls ? '<span class="dot"></span>' : '';
  return `<div class="nwf-row"><span class="nwf-k">${k}</span>
    <span class="nwf-v ${cls || ''}">${dot}${v}</span></div>`;
}

async function initNwfMarker() {
  const host = document.getElementById("nwf-marker");
  if (!host) return;
  let r;
  try { r = await getJSON("/regime"); } catch (e) { return; }
  const cls = REGIME_CLS[r.regime] || "edge";
  const lbl = (REGIME_RU[r.regime] || r.regime).toUpperCase();
  const inp = r.inputs || {};

  const liq = inp.nwf_liquid_pct, mz = inp.nwf_months_to_zero;
  const dd = inp.market_drawdown;
  const bsign = (inp.urals != null && inp.oil_cutoff != null) ? (inp.urals - inp.oil_cutoff) : null;
  const dp = r.deval_pressure || "low";
  const dpRu = dp === "high" ? "высокое" : dp === "elevated" ? "повышенное" : "низкое";
  const dpCls = dp === "high" ? "avoid" : dp === "elevated" ? "edge" : "buy";
  const rows = [
    nwfRow(`Девал-давление${r.deval_score != null ? ` (${r.deval_score}/6)` : ""}`, dpRu, dpCls),
    nwfRow("Ликвидный ФНБ", liq != null ? liq.toFixed(1) + "% ВВП" : "—",
           liq == null ? "" : (liq >= 3.0 ? "buy" : (liq >= 1.5 ? "edge" : "avoid"))),
    nwfRow("Месяцев до нуля", mz != null ? Math.round(mz) : "—",
           mz == null ? "" : (mz >= 24 ? "buy" : (mz >= 12 ? "edge" : "avoid"))),
    nwfRow("Urals − отсечка", bsign != null ? `${inp.urals}−${inp.oil_cutoff} = ${bsign >= 0 ? "+" : ""}${bsign}` : "—",
           bsign == null ? "" : (bsign >= 0 ? "buy" : "avoid")),
    nwfRow("Просадка IMOEX", dd != null ? (dd * 100).toFixed(0) + "%" : "—",
           dd == null ? "" : (dd >= 0.27 ? "avoid" : (dd >= 0.10 ? "edge" : "buy"))),
  ].join("");
  const ad = r.allocation && r.allocation.defense;
  let alloc = `Защита ${Math.round((r.defense || 0) * 100)}% · Атака ${Math.round((r.attack || 0) * 100)}%`;
  if (ad) alloc += ` · защита: ОФЗ ${Math.round(ad.ofz_fixed * 100)} / золото ${Math.round(ad.gold * 100)} / флоат ${Math.round(ad.floater * 100)}%`;

  // advisory-разбор Опуса (кеш с сервера; правила остаются костяком)
  const a = r.analysis;
  let analysisHtml;
  if (a && a.note) {
    const aCls = REGIME_CLS[a.regime_opus] || "edge";
    const when = (a.created_at || "").replace("T", " ");
    const diverge = a.diverges
      ? `<div class="nwf-diverge">⚠ Правило: <b>${lbl}</b> · Опус: <b>${(REGIME_RU[a.regime_opus] || a.regime_opus).toUpperCase()}</b> — на твоё решение</div>`
      : "";
    const nu = (a.nuances || []).map(n => `<li>${glossarize(n)}</li>`).join("");
    analysisHtml = `<div class="nwf-analysis">
      <div class="nwf-ahead">🤖 Анализ Опуса <span class="muted">· ${when} · уверенность ${a.confidence || "—"}</span>
        <a href="#" id="nwf-analyze" title="прогнать заново">↻</a></div>
      ${diverge}
      <p class="nwf-anote">${glossarize(a.note)}</p>
      ${nu ? `<ul class="nwf-nuances">${nu}</ul>` : ""}</div>`;
  } else {
    analysisHtml = `<div class="nwf-analysis muted">Анализ Опуса не сгенерирован.
      <a href="#" id="nwf-analyze">прогнать</a></div>`;
  }

  host.innerHTML = `
    <button class="nwf-btn nwf-${cls}" id="nwf-btn" title="ФНБ-режим рынка — нажми для деталей">
      <span class="dot"></span> ФНБ · ${lbl}</button>
    <div class="nwf-pop" id="nwf-pop" hidden>
      <div class="nwf-pop-head nwf-${cls}">Режим рынка · ${lbl}</div>
      <div class="nwf-rows">${rows}</div>
      <div class="nwf-alloc">${alloc}</div>
      <p class="nwf-note">${glossarize(r.note || "")}</p>
      ${analysisHtml}
    </div>`;

  const btn = document.getElementById("nwf-btn");
  const pop = document.getElementById("nwf-pop");
  btn.addEventListener("click", (e) => { e.stopPropagation(); pop.hidden = !pop.hidden; });
  document.addEventListener("click", (e) => { if (!host.contains(e.target)) pop.hidden = true; });
  const an = document.getElementById("nwf-analyze");
  if (an) an.addEventListener("click", async (e) => {
    e.preventDefault(); e.stopPropagation();
    an.textContent = "анализирую (Opus)…";
    try { await sendJSON("/regime/analyze", "POST", {}); } catch (err) {}
    await initNwfMarker();
    document.getElementById("nwf-pop")?.removeAttribute("hidden");
  });

  renderShock(r);   // вторая кнопка — форвардный риск ШОКА (из того же ответа /regime)
}

// ── кнопка «Риск ШОКа»: форвардная вероятность (субъективная оценка Opus) ──
function shockCls(p) { return p >= 35 ? "avoid" : p >= 15 ? "edge" : "buy"; }

function renderShock(r) {
  const host = document.getElementById("shock-marker");
  if (!host) return;
  const s = r.shock;
  if (!s || s.aggregate_pct == null) {
    host.innerHTML = `<button class="nwf-btn nwf-edge" id="shock-btn" title="Риск ШОКа">⚡ Риск ШОКа · —</button>
      <div class="nwf-pop" id="shock-pop" hidden><div class="nwf-pop-head nwf-edge">Риск ШОКа</div>
        <div class="nwf-analysis muted">Оценка Опуса не сгенерирована. <a href="#" id="shock-analyze">прогнать</a></div></div>`;
  } else {
    const p = Math.round(s.aggregate_pct);
    const cls = shockCls(p);
    const when = (s.created_at || "").replace("T", " ");
    const scen = (s.scenarios || []).map(x => {
      const pp = Math.round(x.prob_pct || 0);
      return `<div class="nwf-row"><span class="nwf-k">${glossarize(x.name || "")}</span>
          <span class="nwf-v ${shockCls(pp)}"><span class="dot"></span>${pp}%</span></div>
        ${x.rationale ? `<div class="shock-rat">${glossarize(x.rationale)}</div>` : ""}`;
    }).join("");
    host.innerHTML = `<button class="nwf-btn nwf-${cls}" id="shock-btn" title="Форвардная вероятность ШОКА (оценка Opus)">
        <span class="dot"></span> ⚡ Риск ШОКа · ${p}%</button>
      <div class="nwf-pop" id="shock-pop" hidden>
        <div class="nwf-pop-head nwf-${cls}">Риск ШОКа · ${p}% <span class="muted" style="font-weight:400">/ ${s.horizon || "12 мес"}</span>
          <a href="#" id="shock-analyze" title="прогнать заново" style="float:right;font-weight:400">↻</a></div>
        <div class="nwf-rows">${scen}</div>
        <p class="nwf-note">${glossarize(s.note || "")}</p>
        <p class="shock-disc">Субъективная оценка Opus по сценариям (не калиброванная вероятность), агрегат с учётом корреляции. Форвардный риск ≠ текущий ШОК-режим.</p>
      </div>`;
  }
  const btn = document.getElementById("shock-btn");
  const pop = document.getElementById("shock-pop");
  if (btn && pop) {
    btn.addEventListener("click", (e) => { e.stopPropagation(); pop.hidden = !pop.hidden; });
    document.addEventListener("click", (e) => { if (!host.contains(e.target)) pop.hidden = true; });
  }
  const sa = document.getElementById("shock-analyze");
  if (sa) sa.addEventListener("click", async (e) => {
    e.preventDefault(); e.stopPropagation();
    sa.textContent = "оцениваю (Opus)…";
    try { await sendJSON("/regime/shock_assess", "POST", {}); } catch (err) {}
    await initNwfMarker();
    document.getElementById("shock-pop")?.removeAttribute("hidden");
  });
}
document.addEventListener("DOMContentLoaded", initNwfMarker);
