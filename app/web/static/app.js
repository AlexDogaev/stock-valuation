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
  if (s === "ПРОДАВАЙ") return "sell";
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
  const feltInp = document.getElementById("g-felt");
  const targetInp = document.getElementById("g-target");
  const horizonSel = document.getElementById("g-horizon");
  const ksInp = document.getElementById("g-ks");
  const termInp = document.getElementById("g-terminal");
  if (!regimeSel) return;
  try {
    const s = await getJSON("/settings");
    regimeSel.value = s.regime;
    if (feltInp) feltInp.value = (s.felt_inflation * 100).toFixed(1);
    if (targetInp) targetInp.value = (s.risk_premium * 100).toFixed(1);   // единая премия за риск
    if (ksInp && s.key_rate_eff != null) {       // действующая КС (override или ЦБ SOAP)
      ksInp.value = (s.key_rate_eff * 100).toFixed(2);
      ksInp.title = `Ключевая ставка. ЦБ SOAP: ${s.key_rate_fetched != null ? (s.key_rate_fetched * 100).toFixed(2) + "%" : "—"}. Ручной override — для объявленной до публикации в SOAP.`;
    }
    if (termInp && s.terminal_inflation_eff != null) {     // терминальная инфляция (override или траектория)
      termInp.value = (s.terminal_inflation_eff * 100).toFixed(1);
      termInp.title = `Терминальная инфляция ${(s.terminal_inflation_eff*100).toFixed(1)}% (${s.inflation_terminal_override!=null?"ручной override":"из траектории КС"}). Подними для стресса «инфляция залипнет выше» → реал.YTM длинного фикса вниз.`;
    }
    if (horizonSel) horizonSel.value = String(s.forecast_years);
    const eff = document.getElementById("g-felt-eff");   // эфф. дефлятор за горизонт (траектория КС)
    if (eff) eff.textContent = (s.deflator_active != null && Math.abs(s.deflator_active - s.felt_inflation) > 0.001)
      ? " →" + (s.deflator_active * 100).toFixed(1) + "%" : "";
  } catch (e) { console.warn(e); }
  regimeSel.addEventListener("change", async () => {
    await sendJSON("/settings", "PUT", { regime: regimeSel.value });
    location.reload();
  });
  const saveNum = async (inp, key) => {           // поле в %, в настройки — долей
    const v = parseFloat(inp.value);
    if (isNaN(v)) return;
    await sendJSON("/settings", "PUT", { [key]: v / 100 });
    location.reload();
  };
  if (feltInp) feltInp.addEventListener("change", () => saveNum(feltInp, "felt_inflation"));
  if (targetInp) targetInp.addEventListener("change", () => saveNum(targetInp, "risk_premium"));
  if (ksInp) ksInp.addEventListener("change", () => saveNum(ksInp, "key_rate_override"));
  if (termInp) termInp.addEventListener("change", () => saveNum(termInp, "inflation_terminal_override"));
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
  const ueff = inp.urals_smoothed != null ? inp.urals_smoothed : inp.urals;   // #9: режим на сглаженной
  const bsign = (ueff != null && inp.oil_cutoff != null) ? (ueff - inp.oil_cutoff) : null;
  const dp = r.deval_pressure || "low";
  const dpRu = dp === "high" ? "высокое" : dp === "elevated" ? "повышенное" : "низкое";
  const dpCls = dp === "high" ? "avoid" : dp === "elevated" ? "edge" : "buy";
  const rows = [
    nwfRow(`Девал-давление${r.deval_score != null ? ` (${r.deval_score}/6)` : ""}`, dpRu, dpCls),
    nwfRow("Ликвидный ФНБ", liq != null ? liq.toFixed(1) + "% ВВП" : "—",
           liq == null ? "" : (liq >= 3.0 ? "buy" : (liq >= 1.5 ? "edge" : "avoid"))),
    nwfRow("Месяцев до нуля", mz != null ? Math.round(mz) : "—",
           mz == null ? "" : (mz >= 24 ? "buy" : (mz >= 12 ? "edge" : "avoid"))),
    nwfRow(`Urals − отсечка${inp.urals_source && inp.urals_source !== "спот" ? " (" + inp.urals_source + ")" : ""}`,
           bsign != null ? `${ueff}−${inp.oil_cutoff} = ${bsign >= 0 ? "+" : ""}${bsign.toFixed(1)}` : "—",
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

  try { r.outlook = await getJSON("/outlook"); } catch (e) { /* движок недоступен → старый Opus */ }
  renderShock(r);             // форвардный риск ШОКА (headline — из движка hazard)
  renderBreakthrough(r.outlook && r.outlook.breakthrough);   // фронтирный рывок (книга Гл.14)
  renderRenovation(r.outlook && r.outlook.renovation);       // Реновация Триады Жильё-ЖКХ-Электро (Гл.15-17)
  renderFiscalDrain(r.outlook && r.outlook.fiscal_drain);    // фискальное доминирование — дисконт пылесоса (§2)
  renderRateTrajectory(r);    // траектория ключевой ставки (Opus по пейсу + риторике)
}

// ── маркер «Окно Рывка» (книга Гл.14): созревание × чел.капитал × триггер, мультипликативно ──
function renderBreakthrough(b) {
  const host = document.getElementById("breakthrough-marker");
  if (!host) return;
  if (!b) { host.innerHTML = ""; return; }
  const cls = b.level === "открывается" ? "buy" : (b.level === "зреет" ? "edge" : "muted");
  const rows = Object.keys(b.factors || {}).map(k =>
    `<div class="nwf-row"><span class="nwf-k">${b.labels[k]}</span><span class="nwf-v">${Math.round(b.factors[k]*100)}%</span></div>`).join("");
  const traj = Object.entries(b.trajectory || {}).map(([p, v]) => `${p} ${v}%`).join(" · ");
  const H = b.horizon || 1;
  host.innerHTML = `<button class="nwf-btn nwf-${cls}" id="bt-btn" title="Окно рывка (книга Гл.14) К КОНЦУ горизонта ${H}л (год ${b.target_year}, ${b.period}): ${b.level}. Окно зреет во времени.">
      <span class="dot"></span> 🚀 Рывок · ${b.prob_pct}% <span class="muted" style="font-weight:400">/${H}л ${b.level}</span></button>
    <div class="nwf-pop" id="bt-pop" hidden>
      <div class="nwf-pop-head nwf-${cls}">Окно рывка · ${b.prob_pct}% (${b.level}) <span class="muted" style="font-weight:400">· к ${b.target_year} (${b.period})</span></div>
      <div class="nwf-alloc">созревание × чел.капитал × триггер (мультипликативно: низкий любой → закрыто); окно ЗРЕЁТ во времени → на длинном горизонте выше</div>
      <div class="nwf-rows">${rows}</div>
      <div class="nwf-alloc">траектория по пятилеткам: ${traj}</div>
      <p class="nwf-note">${b.note}</p>
      <p class="shock-disc">⚠ Калиброванная гипотеза (книга Гл.14): полный рывок (фронтир/экспорт высокого передела) ≠ пред-рывок (замещение известного). Бенефициары полного рывка минору ~недоступны; пред-рывок имеет потолок внутр. рынка.</p>
    </div>`;
  const btn = document.getElementById("bt-btn"), pop = document.getElementById("bt-pop");
  if (btn && pop) {
    btn.addEventListener("click", (e) => { e.stopPropagation(); pop.hidden = !pop.hidden; });
    document.addEventListener("click", (e) => { if (!host.contains(e.target)) pop.hidden = true; });
  }
}

// ── маркер «Реновация Триады» (Гл.15-17): мобилизационно-инфраструктурный рывок, неизбежность ВЫСОКА ──
function renderRenovation(b) {
  const host = document.getElementById("renovation-marker");
  if (!host) return;
  if (!b) { host.innerHTML = ""; return; }
  // не зелёный даже на «принуждена»: тема неизбежна, но минору достаётся ТОЛЬКО через поставщиков
  // (операторы — бенефициар на бумаге, тариф). Янтарный = «структурный спрос, но узкий узел».
  const cls = b.level === "латентна" ? "muted" : "edge";
  const rows = Object.keys(b.factors || {}).map(k =>
    `<div class="nwf-row"><span class="nwf-k">${b.labels[k]}</span><span class="nwf-v">${Math.round(b.factors[k]*100)}%</span></div>`).join("");
  const traj = Object.entries(b.trajectory || {}).map(([p, v]) => `${p} ${v}%`).join(" · ");
  const H = b.horizon || 1;
  host.innerHTML = `<button class="nwf-btn nwf-${cls}" id="rn-btn" title="Реновация Триады Жильё-ЖКХ-Электро (Гл.15-17) К КОНЦУ горизонта ${H}л (год ${b.target_year}, ${b.period}): ${b.level}. Неизбежность нарастает по мере выбытия советской базы.">
      <span class="dot"></span> 🏗️ Реновация · ${b.prob_pct}% <span class="muted" style="font-weight:400">/${H}л ${b.level}</span></button>
    <div class="nwf-pop" id="rn-pop" hidden>
      <div class="nwf-pop-head nwf-${cls}">Реновация Триады · ${b.prob_pct}% (${b.level}) <span class="muted" style="font-weight:400">· к ${b.target_year} (${b.period})</span></div>
      <div class="nwf-alloc">Жильё + ЖКХ-сети + энергетика, срок 50-60 лет → выбывает синхронно в 2020-40-х. Россия ПРИНУЖДЕНА (рынок — сама страна, внешний не нужен). Неизбежность = износ × реактивный триггер.</div>
      <div class="nwf-rows">${rows}<div class="nwf-row"><span class="nwf-k">фискальная способность (↓ → триаж)</span><span class="nwf-v">${b.fiscal_pct}%</span></div></div>
      <div class="nwf-alloc">траектория неизбежности по пятилеткам: ${traj}</div>
      <p class="nwf-note">${b.note}</p>
      <p class="shock-disc">⚠ Калиброванная гипотеза (Гл.15-17). Реализация = ТРИАЖ, не модернизационный бум (фискальные ножницы Гл.16). Реактивно-аварийно. Узел для минора — поставщики оборудования (кабель/трубы/металл/цемент), НЕ операторы (тариф).</p>
    </div>`;
  const btn = document.getElementById("rn-btn"), pop = document.getElementById("rn-pop");
  if (btn && pop) {
    btn.addEventListener("click", (e) => { e.stopPropagation(); pop.hidden = !pop.hidden; });
    document.addEventListener("click", (e) => { if (!host.contains(e.target)) pop.hidden = true; });
  }
}

// ── маркер «Пылесос» (фискальное доминирование §2): дисконт к акциям от выгребания пула в ОФЗ ──
function renderFiscalDrain(f) {
  const host = document.getElementById("fiscal-marker");
  if (!host) return;
  if (!f) { host.innerHTML = ""; return; }
  const cls = f.level === "высокий" ? "avoid" : (f.level === "повышенный" ? "edge" : "muted");
  host.innerHTML = `<button class="nwf-btn nwf-${cls}" id="fd-btn" title="Фискальное доминирование (§2): пул сбережений выгребается в ОФЗ → дисконт к равновесному P/E акций. ${f.level}.">
      <span class="dot"></span> 🏦 Пылесос · ${(f.drain_pp*100).toFixed(1)}пп <span class="muted" style="font-weight:400">${f.level}</span></button>
    <div class="nwf-pop" id="fd-pop" hidden>
      <div class="nwf-pop-head nwf-${cls}">Дисконт пылесоса · ${(f.drain_pp*100).toFixed(1)}пп (${f.level}, интенс. ${Math.round(f.intensity*100)}%)</div>
      <div class="nwf-alloc">Денег фиксированно, государству нужнее → пул сбережений выгребается в ОФЗ → акциям меньше бида → дисконт к равновесному P/E (НЕ в hurdle — отдельный канал от деваль-риска).</div>
      <div class="nwf-rows">
        <div class="nwf-row"><span class="nwf-k">дефицит, % ВВП (run-rate)</span><span class="nwf-v">${(f.deficit_pct_gdp*100).toFixed(1)}%</span></div>
        <div class="nwf-row"><span class="nwf-k">превышение плана</span><span class="nwf-v">${Math.round(f.overshoot*100)}%</span></div>
      </div>
      <p class="nwf-note">${f.note}</p>
      <p class="shock-disc">⚠ Калиброванная гипотеза (§2/§5). Считается от ёмкости пула (≈ВВП), не от долга. Ввод дефицита — ручной (Минфин помесячно, /Настройки).</p>
    </div>`;
  const btn = document.getElementById("fd-btn"), pop = document.getElementById("fd-pop");
  if (btn && pop) {
    btn.addEventListener("click", (e) => { e.stopPropagation(); pop.hidden = !pop.hidden; });
    document.addEventListener("click", (e) => { if (!host.contains(e.target)) pop.hidden = true; });
  }
}

// ── кнопка «Риск ШОКа»: форвардная вероятность (субъективная оценка Opus) ──
function shockCls(p) { return p >= 35 ? "avoid" : p >= 15 ? "edge" : "buy"; }

function renderShock(r) {
  const host = document.getElementById("shock-marker");
  if (!host) return;
  const s = r.shock;
  if (!s || s.aggregate_pct == null) {
    host.innerHTML = `<button class="nwf-btn nwf-edge" id="shock-btn" title="Риск ШОКа">⚡ ШОК · —</button>
      <div class="nwf-pop" id="shock-pop" hidden><div class="nwf-pop-head nwf-edge">Риск ШОКа</div>
        <div class="nwf-analysis muted">Оценка Опуса не сгенерирована. <a href="#" id="shock-analyze">прогнать</a></div></div>`;
  } else {
    // headline — ДВИЖОК hazard (фон × EWI + структурный горб); fallback на старый Opus aggregate
    const haz = r.outlook && r.outlook.hazard;
    const annualFrac = haz ? haz.annual : (s.aggregate_pct / 100);
    const annual = Math.round(annualFrac * 100);
    const hzSel = document.getElementById("g-horizon");
    const H = hzSel ? (parseInt(hzSel.value) || 1) : 1;
    const p = Math.round((1 - Math.pow(1 - annualFrac, H)) * 100);  // кумулятив за горизонт
    const cls = p > 70 ? "avoid" : p >= 30 ? "edge" : "buy";  // шкала: <30 зел · 30-70 жёлт · >70 красн (на кумулятив)
    const bLo = haz && haz.annual_band ? haz.annual_band[0] : annualFrac * 0.6;
    const bHi = haz && haz.annual_band ? haz.annual_band[1] : Math.min(0.6, annualFrac * 1.45);
    const pLo = Math.round((1 - Math.pow(1 - bLo, H)) * 100);
    const pHi = Math.round((1 - Math.pow(1 - bHi, H)) * 100);
    const engineLine = haz
      ? `<div class="nwf-alloc">движок: фон ${Math.round(haz.base_fond * 100)}% × EWI ×${haz.ewi_multiplier} (скор ${haz.ewi_score}) + горб ${(haz.structural_hump * 100).toFixed(1)}% → <b>${annual}%/год</b></div>`
      : "";
    const when = (s.created_at || "").replace("T", " ");
    const scen = (s.scenarios || []).map(x => {
      const pp = Math.round(x.prob_pct || 0);
      const sev = x.severity_pct != null ? Math.round(x.severity_pct) : null;
      return `<div class="nwf-row"><span class="nwf-k">${glossarize(x.name || "")}${x.factor ? ` <span class="muted">· ${x.factor}</span>` : ""}</span>
          <span class="nwf-v ${shockCls(pp)}"><span class="dot"></span>${pp}%${sev != null ? ` · урон ${sev}%` : ""}</span></div>
        ${x.rationale ? `<div class="shock-rat">${glossarize(x.rationale)}</div>` : ""}`;
    }).join("");
    const mx = (v) => v != null ? Math.round(v) + "%" : "—";
    const metrics = `<div class="nwf-alloc">P(хотя бы один): <b>${p}%</b> с корреляцией vs ${mx(s.independent_pct)} наивно ·
        ожид. урон IMOEX <b>${mx(s.expected_damage_pct)}</b> (P×severity) · за 3 года <b>${mx(s.p_horizon3_pct)}</b></div>`;
    host.innerHTML = `<button class="nwf-btn nwf-${cls}" id="shock-btn" title="Кумулятивная вероятность ШОКА за ${H} г (годовой hazard ${annual}%); меняется с горизонтом">
        <span class="dot"></span> ⚡ ШОК · ${p}% <span class="muted" style="font-weight:400">/${H}г</span></button>
      <div class="nwf-pop" id="shock-pop" hidden>
        <div class="nwf-pop-head nwf-${cls}">Риск ШОКа · ${p}% <span class="muted" style="font-weight:400">(${pLo}–${pHi}%)</span> за ${H} г <span class="muted" style="font-weight:400">· годовой ${annual}%</span>
          <a href="#" id="shock-analyze" title="прогнать заново" style="float:right;font-weight:400">↻</a></div>
        ${engineLine}
        <div class="nwf-rows">${scen}</div>
        ${metrics}
        <p class="nwf-note">${glossarize(s.note || "")}</p>
        <p class="shock-disc">⚠ КОНСЕНСУС-ПРОКСИ Opus (суждение по истории + риторике), НЕ независимый внешний якорь. hazard из 4 разнородных кризисов (2008/2014/2020/2022) → широкий дов.интервал (показан в скобках). Две оси: P (вероятность) и урон (severity) — «вероятно но переживём» (нефть) ≠ «маловероятно но катастрофа» (война). Форвардный риск ≠ текущий ШОК-режим.</p>
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
// ── кнопка «Траектория КС»: градация Opus (направление × скорость) по пейсу + риторике ──
function rateDir(grade) {
  const speed = (grade || "").split(" ")[0] || "—";
  if ((grade || "").includes("снижен")) return { arrow: "↓", cls: "buy", speed };
  if ((grade || "").includes("повышен")) return { arrow: "↑", cls: "avoid", speed };
  return { arrow: "→", cls: "edge", speed: "удержание" };
}

function renderRateTrajectory(r) {
  const host = document.getElementById("rate-marker");
  if (!host) return;
  const t = r.rate_trajectory;
  if (!t || !t.grade) {
    host.innerHTML = `<button class="nwf-btn nwf-edge" id="rate-btn" title="Траектория КС">↕ КС · —</button>
      <div class="nwf-pop" id="rate-pop" hidden><div class="nwf-pop-head nwf-edge">Траектория КС</div>
        <div class="nwf-analysis muted">Градация не сгенерирована. <a href="#" id="rate-run">прогнать</a></div></div>`;
  } else {
    const d = rateDir(t.grade);
    const tks = t.terminal_ks != null ? pct(t.terminal_ks) : "—";
    const dec = (t.decisions || []).map(x => `${(x[0] || "").slice(2)} ${(x[1] * 100).toFixed(2)}%`).join(" · ");
    host.innerHTML = `<button class="nwf-btn nwf-${d.cls}" id="rate-btn" title="Траектория ключевой ставки: ${t.grade} (Opus по пейсу + риторике ЦБ)">
        <span class="dot"></span> ${d.arrow} КС</button>
      <div class="nwf-pop" id="rate-pop" hidden>
        <div class="nwf-pop-head nwf-${d.cls}">Траектория КС · ${t.grade}
          <a href="#" id="rate-run" title="прогнать заново" style="float:right;font-weight:400">↻</a></div>
        <div class="nwf-row"><span class="nwf-k">Терминальная КС</span><span class="nwf-v">${tks}</span></div>
        <div class="nwf-row"><span class="nwf-k">Средний шаг</span><span class="nwf-v">${t.avg_step_pp} пп/заседание</span></div>
        <div class="nwf-row"><span class="nwf-k">Уверенность</span><span class="nwf-v">${t.confidence || "—"}</span></div>
        ${t.signal_read ? `<p class="nwf-note"><b>Сигнал ЦБ:</b> ${glossarize(t.signal_read)}</p>` : ""}
        ${t.rationale ? `<p class="nwf-note">${glossarize(t.rationale)}</p>` : ""}
        <div class="nwf-alloc">Решения: ${dec || "—"}</div>
        <p class="shock-disc">${t.source || ""}. Кормит терминал дефлятора: инфляция = терминальная КС − реальный спред.</p>
      </div>`;
  }
  const btn = document.getElementById("rate-btn"), pop = document.getElementById("rate-pop");
  if (btn && pop) {
    btn.addEventListener("click", (e) => { e.stopPropagation(); pop.hidden = !pop.hidden; });
    document.addEventListener("click", (e) => { if (!host.contains(e.target)) pop.hidden = true; });
  }
  const rr = document.getElementById("rate-run");
  if (rr) rr.addEventListener("click", async (e) => {
    e.preventDefault(); e.stopPropagation();
    rr.textContent = "оцениваю (Opus)…";
    try { await sendJSON("/regime/rate_trajectory", "POST", {}); } catch (err) {}
    await initNwfMarker();
    document.getElementById("rate-pop")?.removeAttribute("hidden");
  });
}
document.addEventListener("DOMContentLoaded", initNwfMarker);
