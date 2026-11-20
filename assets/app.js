/* Gold Desk front end. All numbers come from data/*.json (public sources, fetched by GitHub Actions) or from the user's own entries (localStorage).
   Same structure as STTIE (github.com/cakashoza-cmyk/sttie). No AI produces any number or call. */
(function () {
"use strict";
const $ = (id) => document.getElementById(id);
const LS = "golddesk.v1";
const DEF = { lang: "gu", dealer: null, premPct: 2.0, dipPct: 3.0, dipDays: 7, ccSpread: 4.0, holdDays: 30, grams: 100 };
let S = Object.assign({}, DEF, JSON.parse(localStorage.getItem(LS) || "{}"));
const save = () => localStorage.setItem(LS, JSON.stringify(S));
let L = null, M = null, P = null, R = null;   // live, model, predictions, rates
const OZ = 31.1034768;

const f2 = (x, d = 2) => (x == null || isNaN(x)) ? "—" : Number(x).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const rs = (x) => (x == null || isNaN(x)) ? "—" : "₹" + Math.round(x).toLocaleString("en-IN");
const pct = (x, d = 1) => (x == null || isNaN(x)) ? "—" : (x > 0 ? "+" : "") + x.toFixed(d) + "%";
const cls = (x, band = 0.0001) => x > band ? "up" : x < -band ? "down" : "flat";
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pill = (k, t) => `<span class="pill p-${k}">${t || k}</span>`;
const fill = (t, o) => t.replace(/\{(\w+)\}/g, (_, k) => o[k] != null ? o[k] : "");

/* ---------- audit trail: every number can show source, time and formula ---------- */
function audit(val, a) {
  const st = a.status || "est";
  const body = [a.source ? `<b>Source:</b> ${a.url ? `<a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.source)}</a>` : esc(a.source)}` : "",
    a.asof ? `<b>As of:</b> ${esc(a.asof)}` : "", a.fetched ? `<b>Fetched:</b> ${esc(a.fetched)}` : "",
    a.formula ? `<b>Formula:</b> <span class="formula" style="display:block">${esc(a.formula)}</span>` : "", a.note ? esc(a.note) : ""].filter(Boolean).join("<br>");
  const lab = { user: "your input", est: "estimate", assume: "assumption" }[st] || st;
  return `<details class="aud"><summary>${val} ${pill(st === "user" ? "input" : st, lab)}</summary><div class="audbox">${body}</div></details>`;
}
function item(k) { return L && L.items[k]; }
function itemAudit(k, valTxt) {
  const it = item(k);
  if (!it) return `<span class="grey">no live source</span> ${pill("none", "no live source")}`;
  return audit(valTxt || f2(it.value), { status: it.status, source: it.source, url: it.source_url, asof: it.as_of, fetched: L.generated_ist,
    note: (it.note || "") + (it.status === "stale" ? " STALE: last refresh failed (" + (it.stale_reason || "") + "); showing last good value." : "") });
}
function rateAudit(k, txt) { const r = R[k]; return audit(txt, { status: "official", source: r.source, url: r.url, asof: "checked by hand " + R.verified_on + (r.from ? "; in force from " + r.from : "") }); }

/* ---------- series & estimates ---------- */
function ser(k) { const it = item(k); return it && it.history ? it.history : []; }
function atOrBefore(h, d) { let lo = 0, hi = h.length - 1, r = null; while (lo <= hi) { const m = (lo + hi) >> 1; if (h[m][0] <= d) { r = h[m][1]; lo = m + 1; } else hi = m - 1; } return r; }
function before(h, d) { let lo = 0, hi = h.length - 1, r = null; while (lo <= hi) { const m = (lo + hi) >> 1; if (h[m][0] < d) { r = h[m][1]; lo = m + 1; } else hi = m - 1; } return r; }
function addDays(d, n) { const x = new Date(d + "T00:00:00Z"); x.setUTCDate(x.getUTCDate() + n); return x.toISOString().slice(0, 10); }
function daysBetween(a, b) { return Math.round((new Date(b + "T00:00:00Z") - new Date(a + "T00:00:00Z")) / 864e5); }
function changeOver(h, days) { if (h.length < 2) return null; const last = h[h.length - 1]; const prev = atOrBefore(h, addDays(last[0], -days)); return prev ? 100 * (last[1] / prev - 1) : null; }
function dutyPct() { return R ? R.bcd_pct.value + R.aidc_pct.value + R.sws_pct.value : null; }
function fxNow() { const a = item("usdinr") || item("usdinr_ecb"); return a ? a.value : null; }
// international gold in rupees per 10 g, before duty
function intlSeries() { const g = ser("comex"), i = ser("usdinr_ecb"); return g.map(([d, v]) => { const x = atOrBefore(i, d); return x ? [d, v * x / OZ * 10] : null; }).filter(Boolean); }
function landedNow() {
  const g = item("comex"), fx = fxNow(); if (!g || !fx || !R) return null;
  const intl = g.value * fx / OZ * 10, duty = intl * dutyPct() / 100;
  const tvAge = daysBetween(R.tariff_value.from, new Date().toISOString().slice(0, 10));
  const dutyTV = R.tariff_value.value * fx * dutyPct() / 100;
  return { usd10: g.value / OZ * 10, intl, duty, landed: intl + duty, dutyTV, landedTV: intl + dutyTV, tvStale: tvAge > 16, fx };
}
function ibjaDate() { const it = item("ibja999_pm"); return it ? it.as_of : null; }
function premLast() { const h = M && M.premium_history; return h && h.length ? { d: h[h.length - 1][0], v: h[h.length - 1][1] } : null; }
// COMEX reference at IBJA's afternoon rate = mean(previous close, same-day close), as in scripts/model.py
function comexRef(d) { const g = ser("comex"); const a = before(g, d), b = atOrBefore(g, d); return a != null && b != null ? (a + b) / 2 : b; }
function indicative() {
  const ib = item("ibja999"), d = ibjaDate(), g = item("comex"); if (!ib || !d || !g) return null;
  const ref = comexRef(d), refFx = atOrBefore(ser("usdinr_ecb"), d), fx = fxNow(); if (!ref || !refFx || !fx) return null;
  const ch = 100 * ((g.value * fx) / (ref * refFx) - 1);
  return { ch, v: item("ibja999_pm").value * (1 + ch / 100), ref, refFx, base: item("ibja999_pm").value, d };
}
function dipMove(days) { const s = intlSeries(); const d = ibjaDate(); if (!s.length || !d) return null; const p1 = atOrBefore(s, d), p0 = atOrBefore(s, addDays(d, -days)); return p0 && p1 ? 100 * (p1 / p0 - 1) : null; }

/* ---------- today's call ---------- */
function latestPred(kind, h) { if (!P) return null; const xs = P.predictions.filter((p) => p.kind === kind && (!h || p.horizon_days === h)); return xs[xs.length - 1] || null; }
function isDefault() { return ["premPct", "dipPct", "dipDays"].every((k) => Number(S[k]) === DEF[k]); }
function todaysCall() {
  const led = latestPred("call");
  if (led && isDefault()) return { call: led.buy_call, raw: led.raw_call, dip: led.rule_dip, prem: led.rule_premium, move: led.inputs.gold_rupee_move_pct,
    premV: led.inputs.premium_pct, soft: led.downgraded, news: led.news_flag, basis: led.basis, made_on: led.made_on, fromLedger: true };
  // user changed a rule setting: recompute with the same logic as scripts/model.py (gates and recent check come from the default back-test)
  const pl = premLast(); const premV = pl && pl.d === ibjaDate() ? pl.v : null; const move = dipMove(Number(S.dipDays));
  const prem = premV == null ? null : premV > S.premPct ? "wait" : premV < -S.premPct ? "buy now" : null;
  const dip = move == null ? null : move <= -S.dipPct ? "buy now" : move >= S.dipPct ? "wait" : null;
  const act = M ? M.rules.backtest.active : {}, rf = M ? M.rules.backtest.recent_fail : {};
  const g = (c, r) => c && act[r + "_" + (c === "buy now" ? "buy" : "wait")] ? c : null;
  const sc = [g(prem, "prem"), g(dip, "dip")].reduce((a, c) => a + (c === "buy now" ? 1 : c === "wait" ? -1 : 0), 0);
  let call = sc > 0 ? "buy now" : sc < 0 ? "wait" : "buy part"; const raw = call; let soft = null;
  const gd = g(dip, "dip"); if (gd && rf["dip_" + (gd === "buy now" ? "buy" : "wait")] && call !== "buy part") { call = "buy part"; soft = "recent"; }
  const news = led ? led.news_flag : null; if (news && call === "buy now") { call = "buy part"; soft = soft || "news"; }
  return { call, raw, dip, prem, move, premV, soft, news, basis: "rules", made_on: ibjaDate(), fromLedger: false };
}
function reasonText(c, T) {
  const out = []; const act = M ? M.rules.backtest.active : {};
  const mv = c.move != null ? Math.abs(c.move).toFixed(1) : "";
  if (c.dip === "buy now" && act.dip_buy) out.push(fill(c.soft && String(c.soft).indexOf("dip rule") >= 0 || c.soft === "recent" ? T.r_soft : T.r_dip, { d: S.dipDays, x: mv }));
  else if (c.dip === "wait" && act.dip_wait) out.push(fill(T.r_jump, { d: S.dipDays, x: mv }));
  if (c.prem === "wait" && act.prem_wait) out.push(fill(T.r_prem, { x: Math.abs(c.premV).toFixed(1) }));
  if (c.prem === "buy now" && act.prem_buy) out.push(fill(T.r_disc, { x: Math.abs(c.premV).toFixed(1) }));
  if (!out.length) out.push(T.r_flat);
  if (c.news) out.push(T.r_news);
  return out.join(" ");
}
function hitInfo() {
  const sc = (P ? P.predictions : []).filter((p) => p.scored && p.kind === "call").slice(-20);
  const b = M && M.rules.backtest.dip.by_call["buy now"];
  return { n: sc.length, k: sc.filter((p) => p.hit_buy_call).length, bt: b ? Math.round(b.hit_rate) : null, btn: b ? b.n : null };
}
function nextFestivals() {
  const today = new Date(Date.now() + 5.5 * 3600e3).toISOString().slice(0, 10);
  return (R ? R.calendar : []).filter((f) => f.date >= today).map((f) => Object.assign({ left: daysBetween(today, f.date) }, f));
}
function fmtDate(d, lang) { return new Date(d + "T00:00:00Z").toLocaleDateString({ gu: "gu-IN", hi: "hi-IN", en: "en-IN" }[lang], { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }); }

function renderSimple() {
  const T = STR[S.lang] || STR.gu;
  document.documentElement.lang = S.lang;
  document.querySelectorAll("#langs button").forEach((b) => b.classList.toggle("on", b.dataset.l === S.lang));
  $("s-title").textContent = T.title; $("a-today").textContent = T.today;
  $("p-title").textContent = T.price_t; $("i-title").textContent = T.prem_t; $("h-title").textContent = T.hit_t; $("f-title").textContent = T.fest_t;
  $("q-label").textContent = T.input_l; $("q-clear").textContent = T.clear; $("wa-btn").textContent = "🟢 " + T.share;
  $("speak-btn").textContent = "🔊 " + T.listen; $("details-link").textContent = T.details;
  $("s-src").textContent = T.src; $("s-disc").textContent = T.disclaimer;
  if (!L || !M) { $("a-main").textContent = T.nodata; return; }
  $("s-updated").textContent = fill(T.updated, { t: L.generated_ist });
  const c = todaysCall();
  $("answer").className = "answer " + (c.call === "buy now" ? "buy" : c.call === "wait" ? "wait" : "small");
  $("a-main").textContent = c.call === "buy now" ? "✅ " + T.buy_now : c.call === "wait" ? "⏳ " + T.wait : "🟡 " + T.buy_part;
  $("a-reason").textContent = reasonText(c, T);
  // price tile
  const ib = item("ibja999"), k22 = item("ibja916");
  const ch7 = changeOver(ser("ibja999_pm"), 7);
  const arrow = ch7 == null ? "" : ch7 > 0.5 ? "⬆️" : ch7 < -0.5 ? "⬇️" : "➡️";
  $("p-big").innerHTML = ib ? `${rs(ib.value)} <span style="font-size:1.6rem">${arrow}</span>` : "—";
  $("p-big").className = "t-big " + (ch7 == null ? "" : cls(ch7, 0.5));
  $("p-sub").textContent = (ch7 != null ? fill(T.trend7, { x: (ch7 > 0 ? "+" : "") + ch7.toFixed(1) }) + " · " : "") + T.price_sub + (ib ? " · " + ib.as_of : "");
  $("p-sub2").textContent = [k22 ? fill(T.k22, { x: Math.round(k22.value).toLocaleString("en-IN") }) : "", ib ? fill(T.gst, { x: Math.round(ib.value * (1 + R.gst_pct.value / 100)).toLocaleString("en-IN") }) : ""].filter(Boolean).join(" · ");
  const ind = indicative();
  $("p-ind").textContent = ind && Math.abs(ind.ch) >= 0.3 ? "🌍 " + fill(T.indic, { x: (ind.ch > 0 ? "+" : "") + ind.ch.toFixed(1), y: (Math.round(ind.v / 100) * 100).toLocaleString("en-IN") }) : "";
  // premium tile
  const pl = premLast();
  if (pl) {
    const v = pl.v, x = Math.abs(v).toFixed(1);
    $("i-main").textContent = v > S.premPct ? "🔺 " + fill(T.prem_hi, { x }) : v < -S.premPct ? "🔻 " + fill(T.prem_lo, { x }) : "⚖️ " + fill(T.prem_ok, { x: (v > 0 ? "+" : "") + v.toFixed(1) });
    $("i-sub").textContent = T.prem_sub.replace("15%", dutyPct() + "%") + " · " + pl.d;
  } else { $("i-main").textContent = "—"; $("i-sub").textContent = ""; }
  // hit tile
  const h = hitInfo();
  $("h-main").textContent = h.n >= 10 ? "🎯 " + fill(T.hit_live, { n: h.n, k: h.k }) : "📚 " + T.hit_learning;
  $("h-sub").textContent = h.bt != null ? fill(T.hit_bt, { k: h.bt, n: h.btn }) : "";
  // festivals
  const fs = nextFestivals();
  $("f-main").innerHTML = fs.length ? fs.slice(0, 2).map((f) => esc(fill(T.fest, { name: S.lang === "en" ? f.name : f[S.lang], date: fmtDate(f.date, S.lang), n: f.left }))).join("<br>") : "—";
  $("f-sub").textContent = T.fest_sub;
  // dealer quote
  $("q-input").value = S.dealer > 0 ? S.dealer : "";
  if (S.dealer > 0 && ib) { const d = S.dealer - ib.value * (1 + R.gst_pct.value / 100); $("q-res").textContent = fill(d >= 0 ? T.dealer_hi : T.dealer_lo, { x: Math.round(Math.abs(d)).toLocaleString("en-IN") }); }
  else $("q-res").textContent = "";
  const sb = $("speak-btn"); const lang = { gu: "gu-IN", hi: "hi-IN", en: "en-IN" }[S.lang];
  const hasVoice = "speechSynthesis" in window && speechSynthesis.getVoices().some((v) => v.lang && v.lang.replace("_", "-").toLowerCase().startsWith(lang.slice(0, 2)));
  sb.style.display = hasVoice ? "" : "none";
}
function summaryText() {
  const T = STR[S.lang] || STR.gu;
  return [fill(T.wa_head, { t: L ? L.generated_ist : "" }), $("a-main").textContent, $("a-reason").textContent,
    fill(T.wa_price, { p: $("p-big").textContent.replace(/[^\d₹,]/g, ""), tr: $("p-sub").textContent.split(" · ")[0] }),
    fill(T.wa_prem, { s: $("i-main").textContent.replace(/^\S+\s/, "") }), fill(T.wa_hit, { s: $("h-main").textContent.replace(/^\S+\s/, "") }),
    T.disclaimer, fill(T.wa_link, { u: location.href.split("#")[0] })].join("\n");
}

/* ---------- details: helpers ---------- */
function numIn(key, label, kind = "assume", step = "0.1", note = "") {
  return `<div class="row"><span>${label} ${pill(kind === "user" ? "input" : "assume", kind === "user" ? "your input" : "assumption")}${note ? `<br><span class="src">${note}</span>` : ""}</span><input type="number" step="${step}" data-k="${key}" class="${kind === "assume" ? "assume" : ""}" value="${S[key] == null ? "" : S[key]}"></div>`;
}
function spark(h, w = 120, hgt = 28) {
  if (!h || h.length < 2) return "";
  const v = h.map((x) => x[1]); const mn = Math.min(...v), mx = Math.max(...v); const r = mx - mn || 1;
  const pts = v.map((y, i) => `${(i / (v.length - 1) * w).toFixed(1)},${(hgt - (y - mn) / r * hgt).toFixed(1)}`).join(" ");
  const col = v[v.length - 1] >= v[0] ? "#4ade80" : "#f87171";
  return `<svg class="spark" width="${w}" height="${hgt}"><polyline fill="none" stroke="${col}" stroke-width="1.5" points="${pts}"/></svg>`;
}
const callTxt = (c) => c === "buy now" ? "✅ Buy now" : c === "wait" ? "⏳ Wait" : "🟡 Buy part now, rest later";

/* ---------- 1. Today ---------- */
function rToday() {
  const c = todaysCall(); const ln = landedNow(); const ind = indicative();
  const cards = [["ibja999", "IBJA gold 999 (24K), ₹/10 g", (it) => rs(it.value), "ibja999_pm"], ["ibja916", "IBJA gold 916 (22K), ₹/10 g", (it) => rs(it.value), "ibja916"],
    ["comex", "COMEX gold, US$/oz", (it) => "$" + f2(it.value), "comex"], ["usdinr", "USD/INR (FBIL)", (it) => "₹" + f2(it.value, 4), "usdinr_ecb"],
    ["real10", "US 10-yr real yield", (it) => f2(it.value) + "%", "real10"], ["dollar", "US dollar index (broad)", (it) => f2(it.value), "dollar"],
    ["fedfunds", "US fed funds rate", (it) => f2(it.value) + "%", "fedfunds"], ["repo", "RBI repo rate", (it) => f2(it.value) + "%", null]];
  const cardHtml = cards.map(([k, t, fmt, hk]) => { const it = item(k); const h = hk ? ser(hk) : [];
    return `<div class="card"><div class="ct">${t} ${h.length ? spark(h.slice(-90)) : ""}</div><div class="big">${it ? itemAudit(k, fmt(it)) : '<span class="grey">no live source</span>'}</div><div class="sub">${h.length > 1 ? (k === "real10" || k === "fedfunds" ? "1-month change " + f2((h[h.length - 1][1] - (atOrBefore(h, addDays(h[h.length - 1][0], -30)) || h[h.length - 1][1]))) + " pp" : "1-month change " + pct(changeOver(h, 30))) : ""}</div></div>`; }).join("");
  const sess = (item("ibja999") && item("ibja999").sessions || []).slice().reverse().slice(0, 8).map((s) => `<tr><td>${esc(s[0])}</td><td>${s[1]}</td><td>${rs(s[2])}</td><td>${rs(s[3])}</td></tr>`).join("");
  const r1 = M.rules.backtest;
  $("s-today").innerHTML = `
  <div class="note"><b>How this thinks (3 layers).</b> <b>1. Trader rules of thumb</b> (editable in tab 3): buy after a sharp dip; be careful when India trades at a big premium to import cost. <b>2. Market context</b>: COMEX gold, the rupee, US real yields and the dollar, RBI and Fed rates, customs duty. <b>3. Learning loop</b>: every day it logs its call, scores it when the time is up, and a variable or rule only counts after it has beaten the simple alternative in a walk-forward test (tab 5). No AI picks numbers, weights or calls.</div>
  <div class="grid">${cardHtml}</div>
  <div class="grid2"><div class="card"><div class="ct">Today's call ${pill("est")}</div>
    <div class="call ${c.call === "buy now" ? "up" : c.call === "wait" ? "down" : "flat"}">${callTxt(c.call)}</div>
    <div class="sub">For a purchase you plan within about 30 days. Made on IBJA closing rate of ${esc(c.made_on || "")}${c.fromLedger ? " (logged in the public ledger)" : " (recomputed with your rule settings; the ledger keeps the default call)"}.</div>
    <table style="margin-top:8px"><tr><th>Input</th><th>Reading</th><th>Signal</th><th>Used?</th></tr>
    <tr><td>Gold in rupees, last ${S.dipDays} days</td><td>${pct(c.move)}</td><td>${c.dip || "none"}</td><td>${c.dip ? (M.rules.backtest.active["dip_" + (c.dip === "buy now" ? "buy" : "wait")] ? pill("live", "yes") : pill("none", "no: failed back-test")) : "—"}</td></tr>
    <tr><td>India premium vs import cost</td><td>${pct(c.premV)}</td><td>${c.prem || "none"}</td><td>${c.prem ? (M.rules.backtest.active["prem_" + (c.prem === "buy now" ? "buy" : "wait")] ? pill("live", "yes") : pill("none", "no: not enough evidence")) : "—"}</td></tr>
    <tr><td>Learning model (30 days)</td><td>${M.horizons["30"].gate.mask.some(Boolean) ? "has weights" : "all weights 0"}</td><td>no change</td><td>${c.basis === "model" ? pill("live", "yes") : pill("none", "no: has not beaten 'no change'")}</td></tr>
    <tr><td>News (duty-cut headline)</td><td colspan="2">${c.news ? `<a href="${esc(c.news.url)}" target="_blank" rel="noopener">${esc(c.news.title)}</a>` : "none in last 21 days"}</td><td>${c.news ? pill("bad", "softens call") : "—"}</td></tr></table>
    ${c.soft ? `<div class="warn" style="margin-top:8px">Softened: ${esc(c.soft === "recent" ? "the dip rule has been wrong more often than right in the last 180 days of the back-test" : c.soft === "news" ? "duty-cut headline" : c.soft)}. Raw rule call was "${esc(c.raw || "")}".</div>` : ""}
    ${ind ? `<div class="sub" style="margin-top:8px">Since that IBJA rate, COMEX × USD/INR moved ${pct(ind.ch)} → indicative IBJA now ≈ ${audit(rs(ind.v), { status: "est", formula: `IBJA close ${rs(ind.base)} × (COMEX now ${f2(item("comex").value)} × FBIL ${f2(fxNow(), 4)}) ÷ (COMEX ref ${f2(ind.ref)} × ECB ${f2(ind.refFx, 2)} on ${ind.d})`, note: "COMEX ref = average of the previous and same-day COMEX close. Indicative only; the next IBJA rate is what counts." })}</div>` : ""}
    <div class="ct" style="margin-top:12px">Latest IBJA sessions (₹/10 g, excl. GST)</div><table><tr><th>Date</th><th>Session</th><th>999</th><th>916</th></tr>${sess}</table></div>
  <div class="card"><div class="ct">Coming festivals (context only, never used in the call)</div>
    ${nextFestivals().map((f) => `<div class="sub">${esc(f.date)} · <b>${esc(f.name)}</b> · ${f.left} days · <a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.source)}</a></div>`).join("") || '<div class="grey">none listed</div>'}
    <div class="src">Wedding-season demand (roughly Nov–Feb and Apr–Jun) is also context only. The app does not assume any festival price effect.</div>
    <div class="ct" style="margin-top:12px">Headlines (context only, not used in numbers)</div>
    ${(L.headlines || []).slice(0, 8).map((h) => `<div class="sub">${esc(h.date)} · <a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a></div>`).join("") || '<div class="grey">none</div>'}
    <div class="src">${esc(L.headlines_source || "")}</div></div></div>`;
}

/* ---------- 2. Import cost & premium ---------- */
function rLanded() {
  const ln = landedNow(); const ib = item("ibja999"); const pl = premLast();
  if (!ln) { $("s-landed").innerHTML = '<div class="card grey">COMEX price or FX missing — cannot compute.</div>'; return; }
  const r = (l, v, a) => `<tr><td>${l}</td><td>${a ? audit(rs(v), a) : rs(v)}</td></tr>`;
  const gst = R.gst_pct.value / 100;
  const ph = (M.premium_history || []).slice(-30).reverse().map(([d, v]) => `<tr><td>${esc(d)}</td><td class="${v > S.premPct ? "down" : v < -S.premPct ? "up" : "flat"}">${pct(v, 2)}</td></tr>`).join("");
  $("s-landed").innerHTML = `<div class="grid2"><div class="card"><div class="ct">Import cost of 10 g of gold, right now (₹)</div>
   <table><tr><th>Item</th><th>₹ per 10 g</th></tr>
   ${r("COMEX gold → US$ per 10 g", null).replace("—", "$" + f2(ln.usd10))}
   ${r(`× USD/INR (FBIL ${f2(ln.fx, 4)}) = international price in rupees`, ln.intl, { status: "est", formula: `COMEX ${f2(item("comex").value)} $/oz ÷ 31.1035 × 10 × ${f2(ln.fx, 4)}`, asof: item("comex").as_of + " (COMEX), " + item("usdinr").as_of + " (FBIL)", source: "COMEX via Sina (unofficial); FBIL via RBI" })}
   ${r(`Customs duty ${dutyPct()}% (BCD ${R.bcd_pct.value}% + AIDC ${R.aidc_pct.value}%), on market value`, ln.duty, { status: "official", source: R.bcd_pct.source + "; " + R.aidc_pct.source, url: R.bcd_pct.url, asof: "checked " + R.verified_on, formula: "international price × " + dutyPct() + "%" })}
   <tr style="font-weight:700"><td>Landed cost (before GST), market-value basis</td><td>${rs(ln.landed)}</td></tr>
   ${r(`Duty on the CBIC tariff value instead (US$${R.tariff_value.value}/10 g × FBIL × ${dutyPct()}%)`, ln.dutyTV, { status: ln.tvStale ? "stale" : "official", source: R.tariff_value.source, url: R.tariff_value.url, asof: "in force from " + R.tariff_value.from + (ln.tvStale ? " — older than 16 days, check for a newer notification" : ""), note: "Customs charges duty on the notified tariff value, revised every two weeks. Customs also uses its own notified exchange rate; FBIL is used here." })}
   <tr><td>Landed cost (before GST), tariff-value basis</td><td>${rs(ln.landedTV)}</td></tr>
   ${r(`GST ${R.gst_pct.value}% on landed cost (market basis)`, ln.landed * gst, { status: "official", source: R.gst_pct.source, url: R.gst_pct.url, asof: "checked " + R.verified_on })}
   </table>
   <div class="src">SWS: ${esc(R.sws_pct.source)}. Previous regime: ${esc(R.previous_regime.text)}</div></div>
   <div class="card"><div class="ct">Indian premium (+) or discount (−) vs import cost</div>
   <div class="box"><div class="sub">IBJA 999 close ${pl ? esc(pl.d) : ""} vs landed cost at that time</div><div class="big ${pl ? (pl.v > S.premPct ? "down" : pl.v < -S.premPct ? "up" : "flat") : ""}">${pl ? audit(pct(pl.v, 2), { status: "est", formula: "IBJA 999 PM ÷ (COMEX ref × ECB USD/INR ÷ 31.1035 × 10 × (1 + " + dutyPct() + "%)) − 1\nCOMEX ref = average of previous and same-day COMEX close", note: "Timing mismatch between IBJA's afternoon rate and COMEX closes makes this noisy by roughly ±1%. Market-value basis." }) : "—"}</div>
   <div class="sub">A big premium means Indian buyers are paying more than import parity (tight supply, duty-hike fears); a discount means dealers are cutting prices to sell (weak demand, duty-cut hopes).</div></div>
   <table style="margin-top:8px"><tr><th>IBJA date</th><th>Premium</th></tr>${ph}</table>
   <div class="src">History starts with the IBJA data the app holds (${esc((M.premium_history || [[""]])[0][0])}); it grows with every refresh. Only dates under the current ${dutyPct()}% duty (from ${esc(R.bcd_pct.from)}) are computed.</div></div></div>`;
}

/* ---------- 3. Rules ---------- */
function rRules() {
  const c = todaysCall(); const b = M.rules.backtest; const act = b.active; const rf = b.recent_fail;
  const ib = item("ibja999"); const repo = item("repo"); const rate = repo ? repo.value + Number(S.ccSpread) : null;
  const carry = ib && rate ? ib.value * rate / 100 * S.holdDays / 365 : null;
  const bc = (x, k) => x && x.by_call[k] ? `right ${x.by_call[k].hit_rate}% of ${x.by_call[k].n} vs ${x.by_call[k].opposite_hit_rate}% for the opposite action` : "no signals";
  const use = (k) => act[k] ? pill("live", "used") : pill("none", "not used");
  const rows = [
    [`1a. Buy after gold in rupees falls at least <b>${S.dipPct}%</b> in <b>${S.dipDays}</b> days ("buy on dips").`, `Moved ${pct(c.move)}`, c.dip === "buy now" ? pill("live", "fires") : "—", use("dip_buy") + (rf.dip_buy ? " " + pill("bad", "failing lately") : ""), `${bc(b.dip, "buy now")} (30-day outcome, ${b.dip.start} on). Last 180 days: ${bc(b.dip.recent, "buy now")}.`],
    [`1b. Wait after gold in rupees rises at least <b>${S.dipPct}%</b> in <b>${S.dipDays}</b> days ("don't chase a rally").`, `Moved ${pct(c.move)}`, c.dip === "wait" ? pill("bad", "fires") : "—", use("dip_wait") + (rf.dip_wait ? " " + pill("bad", "failing lately") : ""), `${bc(b.dip, "wait")}. Last 180 days: ${bc(b.dip.recent, "wait")}.`],
    [`2a. Wait when India trades more than <b>${S.premPct}%</b> above import cost.`, `Premium ${pct(c.premV, 2)}`, c.prem === "wait" ? pill("bad", "fires") : "—", use("prem_wait"), `${bc(b.premium, "wait")} (IBJA data from ${b.premium.start}; needs 30 signals).`],
    [`2b. Buy when India trades more than <b>${S.premPct}%</b> below import cost (dealer discount).`, `Premium ${pct(c.premV, 2)}`, c.prem === "buy now" ? pill("live", "fires") : "—", use("prem_buy"), `${bc(b.premium, "buy now")}.`],
    [`3. Buying early costs interest. Holding ${S.holdDays} days of stock at repo + ${S.ccSpread}% costs:`, carry == null ? "—" : `${rs(carry)} per 10 g (${f2(rate)}% p.a.)`, "", "info", "A jeweller funding stock on cash credit should buy ahead only if the expected rise beats this."],
    [`4. When no rule fires, or the evidence is weak: buy in parts (stagger).`, "", c.call === "buy part" ? pill("input", "applies") : "—", "default", "Averages the price; the honest choice when nothing beats a coin toss."]];
  const cb = b.combined;
  $("s-rules").innerHTML = `<div class="grid2"><div class="card"><div class="ct">Layer 1 — trader rules of thumb (edit the numbers)</div>
   <table><tr><th>Rule</th><th>Today</th><th>Signal</th><th>Status</th><th>Evidence</th></tr>${rows.map((r) => `<tr><td>${r[0]}</td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td><td class="src">${r[4]}</td></tr>`).join("")}</table>
   <div class="src" style="margin-top:6px">A rule side is <b>used</b> only if, in the back-test with default settings, it was right more often than the opposite action, with at least 30 signals. If it has been wrong more often than right in the last 180 days, a "buy now" or "wait" from it is softened to "buy part". Status and evidence are recomputed on every refresh (tab 5 shows the changes). Combined rules call on the IBJA history held: right ${cb.hit_rate}% of ${cb.n} days (${Object.entries(cb.by_call).map(([k, v]) => `${k}: ${v.hit_rate}% of ${v.n}`).join(", ")}); too short to judge.</div></div>
   <div class="card"><div class="ct">Rule settings ${isDefault() ? "" : pill("input", "changed: back-test figures are for the defaults")}</div>
   ${numIn("dipPct", "Rule 1: move that counts as a dip / jump (%)", "assume", "0.5")}${numIn("dipDays", "Rule 1: over how many days", "assume", "1")}
   ${numIn("premPct", "Rule 2: premium / discount that counts (%)", "assume", "0.25")}
   ${numIn("holdDays", "Rule 3: days you hold stock", "user", "1")}${numIn("ccSpread", "Rule 3: your bank rate above RBI repo (%)", "assume", "0.25", "Typical MSME cash-credit spread; check your sanction letter")}
   <div class="src" style="margin-top:8px">Defaults: dip 3% over 7 days, premium 2%. These are starting points for traders to confirm; they are not taken from any published study.</div></div></div>`;
}

/* ---------- 4. Trends ---------- */
function rTrend() {
  const keys = ["ibja999_pm", "ibja916", "comex", "usdinr_ecb", "real10", "dollar", "fedfunds"];
  const isPP = (k) => k === "real10" || k === "fedfunds";
  const chg = (h, d, k) => { if (isPP(k)) { const last = h[h.length - 1]; const p = atOrBefore(h, addDays(last[0], -d)); return p == null ? null : last[1] - p; } return changeOver(h, d); };
  const fmt = (x, k) => x == null ? "—" : isPP(k) ? (x > 0 ? "+" : "") + x.toFixed(2) + " pp" : pct(x);
  const rows = keys.map((k) => { const it = item(k); if (!it) return `<tr><td>${k}</td><td colspan=6 class="grey">no live source</td></tr>`; const h = it.history || [];
    return `<tr><td>${esc(it.label)}</td><td>${itemAudit(k, f2(it.value, it.value > 1000 ? 0 : 2))}</td>${[7, 30, 91, 365].map((d) => { const x = chg(h, d, k); return `<td class="${cls(x)}">${fmt(x, k)}</td>`; }).join("")}<td>${spark(h.slice(-250))}</td></tr>`; }).join("");
  const is = intlSeries();
  const iRow = `<tr><td><b>Gold in rupees before duty (₹/10 g)</b> ${pill("est")}</td><td>${rs(is.length ? is[is.length - 1][1] : null)}</td>${[7, 30, 91, 365].map((d) => `<td class="${cls(changeOver(is, d))}">${pct(changeOver(is, d))}</td>`).join("")}<td>${spark(is.slice(-250))}</td></tr>`;
  const fc = [7, 30].map((h) => { const p = latestPred("model", h); const mh = M.horizons[String(h)]; if (!p) return "";
    return `<tr><td>${h} days</td><td>${esc(p.made_on)}</td><td>${p.direction} (${pct(p.pred_pct, 2)})</td><td>${rs(p.pred_ibja_rs)} ± ${f2(p.error_band_pct, 1)}%</td><td>${mh.gate.mask.some(Boolean) ? Object.entries(mh.weights).map(([k, v]) => k + " " + v).join(", ") : "all weights 0 → forecast = no change"}</td><td>${esc(p.model_version)}</td></tr>`; }).join("");
  $("s-trend").innerHTML = `<div class="card" style="margin-bottom:14px"><div class="ct">Prices and drivers — change over time</div>
   <table><tr><th>Series</th><th>Latest</th><th>1 week</th><th>1 month</th><th>3 months</th><th>1 year</th><th>Last ~1 year</th></tr>${rows}${iRow}</table>
   <div class="src">IBJA history held by the app starts ${esc((ser("ibja999_pm")[0] || [""])[0])} and grows with each refresh, so long changes may be blank. COMEX is a continuous front-month contract (small roll jumps possible).</div></div>
   <div class="card"><div class="ct">Model forecast of the IBJA 999 rate (from the daily ledger)</div>
   <table><tr><th>Horizon</th><th>Made on</th><th>Direction</th><th>Expected IBJA</th><th>Weights in use</th><th>Model</th></tr>${fc}</table>
   <div class="src">Error band = 80th percentile of walk-forward errors. "Flat" with all weights 0 means no variable has beaten "no change" — see tab 5.</div></div>`;
}

/* ---------- 5. Track record ---------- */
function rTrack() {
  const bt = M.backtest; const preds = P ? P.predictions : [];
  const sc = preds.filter((p) => p.scored);
  const btRows = ["7", "30"].map((h) => { const b = bt[h]; return `<tr><td>${h} days</td><td>${b.start} → ${b.end}</td><td>${b.n}</td><td>${b.hit_rate}%</td><td>${b.naive_hit_rate}%</td><td>${b.ungated_hit_rate}%</td><td>${b.mae_pct}%</td><td>${b.naive_mae_pct}%</td><td>${b.ungated_mae_pct}%</td></tr>`; }).join("");
  const vars = ["7", "30"].map((h) => Object.entries(M.horizons[h].gate.why).map(([v, why]) => `<tr><td>${h}d</td><td>${v}</td><td>${M.horizons[h].weights[v]}</td><td>${M.horizons[h].gate.mask[["momentum", "real_yield", "dollar", "rupee"].indexOf(v)] ? pill("live", "weight") : pill("none", "zero")}</td><td class="src">${esc(why)}</td></tr>`).join("")).join("");
  const live = (k) => { const x = sc.filter((p) => p.kind === k && p.hit_buy_call != null); return x.length ? `${x.filter((p) => p.hit_buy_call).length} of ${x.length}` : "none scored yet"; };
  const recent = preds.slice(-40).reverse().map((p) => `<tr><td>${esc(p.made_on)}</td><td>${p.kind === "call" ? "call" : "model " + p.horizon_days + "d"}</td><td>${p.kind === "call" ? esc(p.buy_call) : esc(p.direction) + " " + pct(p.pred_pct, 2)}</td><td>${rs(p.inputs.ibja_rs)}</td><td>${esc(p.target_date)}</td><td>${p.scored ? rs(p.realised_ibja_rs) + " (" + pct(p.realised_pct, 2) + ")" : '<span class="grey">pending</span>'}</td><td>${p.scored ? (p.kind === "call" ? (p.hit_buy_call ? pill("live", "right") : pill("bad", "wrong")) : (p.hit_direction ? pill("live", "right") : pill("bad", "wrong"))) : ""}</td><td>${esc(p.model_version)}</td></tr>`).join("");
  $("s-track").innerHTML = `<div class="card" style="margin-bottom:14px"><div class="ct">Walk-forward back-test of the learning model (gold in rupees, COMEX × USD/INR)</div>
   <table><tr><th>Horizon</th><th>Period</th><th>Calls</th><th>Direction right (model in use)</th><th>"No change"</th><th>Un-gated model</th><th>Avg error (in use)</th><th>"No change"</th><th>Un-gated</th></tr>${btRows}</table>
   <div class="src">Every 5th trading day the model is re-fitted only on outcomes known by then and asked to forecast; "right" = same direction, where moves under ±${M.band_pct["7"]}% (7 days) or ±${M.band_pct["30"]}% (30 days) count as flat. Back-test runs on international gold in rupees because the app holds only ~4 months of IBJA history; duty changes are excluded.</div></div>
   <div class="grid2"><div class="card"><div class="ct">Layer 3 — each variable's weight and why (model ${esc(M.version)})</div><table><tr><th>Horizon</th><th>Variable</th><th>Weight</th><th></th><th>Why</th></tr>${vars}</table>
   <div class="ct" style="margin-top:10px">Live track record</div><div class="sub">Daily calls (30-day): ${live("call")} right. Model forecasts: ${(() => { const x = sc.filter((p) => p.kind === "model"); return x.length ? x.filter((p) => p.hit_direction).length + " of " + x.length : "none scored yet"; })()} right. First results due ${esc((preds.find((p) => p.kind === "model" && p.horizon_days === 7) || {}).target_date || "")}.</div></div>
   <div class="card"><div class="ct">Current lessons</div>${M.lessons.map((l) => `<div class="sub" style="margin-bottom:6px">• ${esc(l)}</div>`).join("")}
   <div class="ct" style="margin-top:10px">What the model changed and why</div>${M.changelog.slice(0, 15).map((c) => `<div class="sub" style="margin-bottom:6px"><b>${esc(c.date)} · ${esc(c.version)}</b><br>${c.changes.map(esc).join("<br>")}</div>`).join("")}
   <div class="src">Archived model files: data/models/. All lesson text is fixed templates filled with computed numbers; no AI writes or picks anything.</div></div></div>
   <div class="card"><div class="ct">Recent calls, including misses <a class="btn ghost" href="data/track_record.csv" download>Download track record (CSV)</a></div>
   <table><tr><th>Made on</th><th>Type</th><th>Call / forecast</th><th>IBJA at call</th><th>Due</th><th>Actual</th><th>Result</th><th>Model</th></tr>${recent}</table></div>`;
}

/* ---------- 6. Sources ---------- */
function rSources() {
  const rows = Object.entries(L.items).map(([k, it]) => `<tr><td>${esc(it.label)}</td><td>${pill(it.status)}</td><td>${f2(it.value, it.value < 20 ? 4 : 2)} ${esc(it.unit)}</td><td>${esc(it.as_of)}</td><td><a href="${esc(it.source_url)}" target="_blank" rel="noopener">${esc(it.source)}</a></td></tr>`).join("");
  const duty = ["bcd_pct", "aidc_pct", "sws_pct", "gst_pct"].map((k) => `<tr><td>${{ bcd_pct: "Basic customs duty", aidc_pct: "AIDC", sws_pct: "Social welfare surcharge", gst_pct: "GST / IGST" }[k]}</td><td>${pill("official")}</td><td>${R[k].value}%</td><td>checked ${esc(R.verified_on)}</td><td><a href="${esc(R[k].url)}" target="_blank" rel="noopener">${esc(R[k].source)}</a></td></tr>`).join("")
    + `<tr><td>CBIC tariff value, gold</td><td>${pill("official")}</td><td>US$${R.tariff_value.value} per 10 g</td><td>from ${esc(R.tariff_value.from)}</td><td><a href="${esc(R.tariff_value.url)}" target="_blank" rel="noopener">${esc(R.tariff_value.source)}</a> (copy on gazettetracker.com; egazette.gov.in not reachable from our server)</td></tr>`;
  const na = [["MCX gold futures", "Exchange data needs a licence; not used. The app does not give MCX or ETF trade calls."], ["SPDR GLD holdings", "The fund's data download is behind a bot check; not automated."],
    ["RBI SGB issue / redemption prices", "Published as RBI press releases (text); not automated. They are based on IBJA 999 averages, which the app already shows."],
    ["Surat / Ahmedabad local bullion and jeweller rates", "No free dated source. Enter your dealer's rate on the main screen."], ["Making charges", "Vary by jeweller and design; not included anywhere."],
    ["Stooq XAU/USD", "Blocked by a browser check; COMEX via Sina is used instead."], ["CBIC customs exchange rate", "Notified fortnightly as PDFs; FBIL is used instead (usually within 0.5%)."]];
  $("s-sources").innerHTML = `<div class="card" style="margin-bottom:14px"><div class="ct">Every data item <span class="sub">data refreshed ${esc(L.generated_ist)}</span></div><table><tr><th>Item</th><th>Status</th><th>Value</th><th>As of</th><th>Source</th></tr>${rows}${duty}
   ${na.map(([a, b]) => `<tr><td>${a}</td><td>${pill("none", "no live source")}</td><td class="grey">—</td><td></td><td class="src">${b}</td></tr>`).join("")}</table>
   ${Object.keys(L.errors || {}).length ? `<div class="warn">Last refresh errors: ${esc(JSON.stringify(L.errors))}</div>` : '<div class="src">Last refresh: all sources OK.</div>'}</div>
   <div class="grid2"><div class="card"><div class="ct">Formulas</div><div class="formula">${esc(M.formula)}

Daily call (30-day purchase window):
  rule 1: gold in rupees moved ≤ −dip% in N days → buy now; ≥ +dip% → wait
  rule 2: premium > +p% → wait; < −p% → buy now
  only rule sides that beat the opposite action in the back-test (≥30 signals) count;
  sum (+1 buy, −1 wait): >0 buy now, <0 wait, 0 buy part
  softened to "buy part" if the rule failed in the last 180 days, or a duty-cut headline appeared in the last 21 days
  the model replaces the rules only if it beats "no change"
Holding interest = rate × (repo + your spread) × days / 365</div><p class="sub" style="margin-top:8px"><a href="methodology.html">Full methodology →</a></p></div>
   <div class="card"><div class="ct">Refresh schedule</div><div class="sub">GitHub Actions runs at 08:30, 14:30 and 20:30 IST every day (03:00, 09:00, 15:00 UTC), fetches all sources, logs and scores predictions, re-fits the model and commits the JSON. Cost: zero (public repo). If a source fails, the last good value is kept and shown as <span class="pill p-stale">stale</span>.</div>
   <div class="ct" style="margin-top:12px">Disclaimer</div><div class="sub">Decision support for timing physical gold purchases. Not investment advice, and not a recommendation to buy or sell MCX contracts, ETFs or any financial product. IBJA rates exclude GST and making charges; your jeweller's price will differ. IBJA asks commercial users to take its rates through its official API.</div></div></div>`;
}

/* ---------- plumbing ---------- */
function renderDetails() {
  $("meta-data").innerHTML = `Data refreshed: <b>${esc(L.generated_ist)}</b>`;
  $("meta-model").textContent = M ? `Model ${M.version} · fitted ${M.updated_ist}` : "";
  const errs = Object.keys(L.errors || {}); $("err").style.display = errs.length ? "" : "none"; $("err").textContent = errs.length ? "Some sources failed on the last refresh and show their last good value (stale): " + errs.join(", ") : "";
  [rToday, rLanded, rRules, rTrend, rTrack, rSources].forEach((f) => { try { f(); } catch (e) { console.error(f.name, e); $("s-" + { rToday: "today", rLanded: "landed", rRules: "rules", rTrend: "trend", rTrack: "track", rSources: "sources" }[f.name]).innerHTML = '<div class="warn">Could not render: ' + esc(e.message) + "</div>"; } });
}
function renderAll() { renderSimple(); if (location.hash === "#details" || location.hash.startsWith("#tab-")) renderDetails(); }
function route() {
  const det = location.hash === "#details" || location.hash.startsWith("#tab-");
  $("simple").style.display = det ? "none" : ""; $("details").style.display = det ? "" : "none";
  if (det && L && M) { renderDetails(); const t = location.hash.startsWith("#tab-") ? location.hash.slice(5) : null; if (t) showTab(t); }
  window.scrollTo(0, 0);
}
function showTab(s) { document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.s === s)); document.querySelectorAll(".screen").forEach((x) => x.classList.toggle("active", x.id === "s-" + s)); }
document.addEventListener("click", (ev) => {
  const t = ev.target.closest(".tab"); if (t) { showTab(t.dataset.s); history.replaceState(null, "", "#tab-" + t.dataset.s); }
  const l = ev.target.closest("#langs button"); if (l) { S.lang = l.dataset.l; save(); renderSimple(); }
});
document.addEventListener("change", (ev) => { const k = ev.target.dataset && ev.target.dataset.k; if (k) { S[k] = ev.target.value === "" ? DEF[k] : Number(ev.target.value); save(); setTimeout(renderAll, 0); } });
$("back-link").onclick = (e) => { e.preventDefault(); history.pushState(null, "", location.pathname); route(); };
window.addEventListener("hashchange", route);
$("q-input").addEventListener("change", () => { const v = Number($("q-input").value); S.dealer = v >= 30000 && v <= 400000 ? v : null; save(); setTimeout(renderAll, 0); });
$("q-clear").onclick = () => { S.dealer = null; save(); renderAll(); };
$("wa-btn").onclick = () => window.open("https://wa.me/?text=" + encodeURIComponent(summaryText()), "_blank");
$("speak-btn").onclick = () => { const u = new SpeechSynthesisUtterance([$("a-main").textContent, $("a-reason").textContent, $("p-title").textContent, $("p-big").textContent, $("i-main").textContent].join(". ").replace(/[✅⏳🟡⬆️⬇️➡️🔺🔻⚖️🌍]/gu, ""));
  u.lang = { gu: "gu-IN", hi: "hi-IN", en: "en-IN" }[S.lang]; speechSynthesis.cancel(); speechSynthesis.speak(u); };
if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = renderSimple;

const j = (u) => fetch(u + "?t=" + Date.now()).then((r) => { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); });
Promise.all([j("data/live.json"), j("data/model.json"), j("data/predictions.json").catch(() => null), j("data/rates.json")])
  .then(([l, m, p, r]) => { L = l; M = m; P = p; R = r; renderSimple(); route(); })
  .catch((e) => { console.error(e); renderSimple(); $("a-reason").textContent = String(e); });
renderSimple();
})();
