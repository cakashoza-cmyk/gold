"""Gold desk prediction ledger, scoring and learning. Numbers only from data/live.json and data/rates.json.
No AI is used anywhere here; every number is plain arithmetic or least squares, written to JSON.

Prices
  International gold in rupees (Rs/10 g, before duty) = COMEX gold (US$/oz) x USD/INR / 31.1035 x 10
  Landed cost (Rs/10 g, before GST)                   = international x (1 + customs duty%)          [market-value basis]
  Indian premium (+) / discount (-) %                  = IBJA 999 closing / landed cost - 1
     (COMEX reference = average of previous and same-day COMEX close, approximating the price at IBJA's afternoon rate)
Forecast of the % change of gold in rupees over h days (h = 7, 30):
  d% = w_mom * (gold-in-rupees % change over last h days)
     + w_real * (US 10-yr real yield change over last h days, percentage points)
     + w_usd * (US broad dollar index % change over last h days)
     + w_fx * (USD/INR % change over last h days)
  weights re-fitted every run by ridge least squares on realised history (heavy shrinkage toward 'no change');
  a variable keeps weight only if it cuts walk-forward error by at least 1%, and the model as a whole must beat 'no change'.
  The forecast is applied to the IBJA 999 closing rate; live predictions are scored on the IBJA closing rate.
"""
import json, bisect, csv, statistics as st
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
LIVE, PRED, MODEL, RATES = ROOT / "data/live.json", ROOT / "data/predictions.json", ROOT / "data/model.json", ROOT / "data/rates.json"
IST = timezone(timedelta(hours=5, minutes=30))
OZ = 31.1034768
VERSION_BASE = "v1"
BAND = {7: 1.0, 30: 2.0}           # % move treated as 'flat'
CC_SPREAD = 4.0                    # assumption: jeweller cash-credit rate = repo + 4.0%
RIDGE = 0.5                        # shrinkage strength (x number of samples)
VARS = ["momentum", "real_yield", "dollar", "rupee"]
RECENT_DAYS = 180                  # recent check window for an active rule side
MIN_N = 30                         # a rule side needs at least this many back-test signals before it may drive the call
RULES = dict(prem_pct=2.0, dip_pct=3.0, dip_days=7, call_days=30)   # trader rules of thumb (defaults; editable on the page)


def D(s):
    return date.fromisoformat(s[:10])


class Series:
    def __init__(self, hist):
        self.d = [D(a) for a, _ in hist]; self.v = [b for _, b in hist]

    def at(self, day):  # last value on or before day
        i = bisect.bisect_right(self.d, day) - 1
        return self.v[i] if i >= 0 else None

    def before(self, day):  # last value strictly before day
        i = bisect.bisect_left(self.d, day) - 1
        return self.v[i] if i >= 0 else None

    def first_on_or_after(self, day):
        i = bisect.bisect_left(self.d, day)
        return (self.d[i], self.v[i]) if i < len(self.d) else (None, None)


def duty_on(rates, d):
    pct = None
    for r in rates["duty_schedule"]:
        if d >= D(r["from"]):
            pct = r["pct"]
    return pct


def build(live):
    it = live["items"]
    S = {k: Series(it[k]["history"]) for k in ("comex", "usdinr_ecb", "real10", "dollar")}
    rows = {}
    for d, gc in zip(S["comex"].d, S["comex"].v):
        inr = S["usdinr_ecb"].at(d)
        ry, usd = S["real10"].at(d - timedelta(days=1)), S["dollar"].at(d - timedelta(days=1))   # FRED published with a lag
        if None in (inr, ry, usd):
            continue
        rows[d] = dict(gc=gc, inr=inr, intl=gc * inr / OZ * 10, ry=ry, usd=usd)
    return rows, sorted(rows)


def val(rows, ds, day, key):
    i = bisect.bisect_right(ds, day) - 1
    return rows[ds[i]][key] if i >= 0 else None


def features(rows, ds, d, h):
    p = d - timedelta(days=h)
    a = [val(rows, ds, p, k) for k in ("intl", "ry", "usd", "inr")]
    if None in a:
        return None
    r = rows[d]
    return [100 * (r["intl"] / a[0] - 1), r["ry"] - a[1], 100 * (r["usd"] / a[2] - 1), 100 * (r["inr"] / a[3] - 1)]


def realised(rows, ds, d, h):
    i = bisect.bisect_left(ds, d + timedelta(days=h))
    return (ds[i], rows[ds[i]]) if i < len(ds) else (None, None)


def table(rows, ds, h):
    """All (date, features, realised % change, realised date) for horizon h."""
    out = []
    for d in ds:
        f = features(rows, ds, d, h)
        r_d, r = realised(rows, ds, d, h)
        if f and r:
            out.append((d, np.array(f), 100 * (r["intl"] / rows[d]["intl"] - 1), r_d))
    return out


def ridge(X, y, mask):
    m = np.array(mask, dtype=float)
    if len(y) < 60 or not m.any():
        return np.zeros(len(VARS))
    Xm = X * m
    return np.linalg.solve(Xm.T @ Xm + RIDGE * len(y) * np.eye(len(VARS)), Xm.T @ y) * m


def fit(tab, mask, before=None):
    sub = [t for t in tab if before is None or t[3] < before]
    if len(sub) < 60:
        return None
    X = np.array([t[1] for t in sub]); y = np.array([t[2] for t in sub])
    w = ridge(X, y, mask)
    return w, float(((y - X @ w) ** 2).mean()), len(sub)


def direction(pct, h):
    return "up" if pct > BAND[h] else "down" if pct < -BAND[h] else "flat"


def backtest(tab, h, mask, step=5, warm=500):
    out = []
    for i in range(warm, len(tab), step):
        d, x, act, _ = tab[i]
        f = fit(tab, mask, before=d)
        if not f:
            continue
        out.append((d, float(np.dot(f[0], x)), act))
    if not out:
        return None
    hit = [direction(p, h) == direction(a, h) for _, p, a in out]
    naive = [direction(0, h) == direction(a, h) for _, p, a in out]
    return dict(n=len(out), start=out[0][0].isoformat(), end=out[-1][0].isoformat(),
                hit_rate=round(100 * sum(hit) / len(hit), 1), naive_hit_rate=round(100 * sum(naive) / len(naive), 1),
                mae_pct=round(st.mean(abs(p - a) for _, p, a in out), 3), naive_mae_pct=round(st.mean(abs(a) for _, p, a in out), 3),
                err_band_pct=round(float(np.percentile([abs(p - a) for _, p, a in out], 80)), 2),
                up_share=round(100 * sum(a > 0 for _, _, a in out) / len(out), 1))


# ---------- trader rules of thumb ----------
def premium_series(live, rates, rows, ds):
    """IBJA closing rate vs landed cost. COMEX reference = average of the previous and the same-day COMEX close
    (IBJA's PM rate is set in the Indian afternoon, between those two closes); if the same-day close is not in yet, the previous close."""
    ib = live["items"]["ibja999_pm"]["history"]
    gc, fx = Series(live["items"]["comex"]["history"]), Series(live["items"]["usdinr_ecb"]["history"])
    out = []
    for d, v in ib:
        dd = D(d); duty = duty_on(rates, dd); g0 = gc.before(dd); g1 = gc.at(dd); f = fx.at(dd)
        if duty is None or g0 is None or f is None:
            continue
        g = (g0 + g1) / 2
        landed = g * f / OZ * 10 * (1 + duty / 100)
        out.append([d, round(100 * (v / landed - 1), 2)])
    return out


def prem_call(prem, r=RULES):
    return None if prem is None else "wait" if prem > r["prem_pct"] else "buy now" if prem < -r["prem_pct"] else None


def dip_call(move_pct, r=RULES):
    return None if move_pct is None else "buy now" if move_pct <= -r["dip_pct"] else "wait" if move_pct >= r["dip_pct"] else None


def combine(calls):
    s = sum({"buy now": 1, "wait": -1}.get(c, 0) for c in calls if c)
    return "buy now" if s > 0 else "wait" if s < 0 else "buy part"


def call_hit(call, move_pct, h):
    return move_pct > 0 if call == "buy now" else move_pct < 0 if call == "wait" else abs(move_pct) <= BAND[h]


def summarise(res, h):
    by, opp = {}, {}
    for c, mv in res:
        by.setdefault(c, []).append(call_hit(c, mv, h))
        o = {"buy now": "wait", "wait": "buy now"}.get(c)
        opp.setdefault(c, []).append(call_hit(o, mv, h) if o else False)
    allm = [mv for _, mv in res]
    return dict(n=len(res), hit_rate=round(100 * sum(sum(v) for v in by.values()) / len(res), 1) if res else None,
                by_call={c: dict(n=len(v), hit_rate=round(100 * sum(v) / len(v), 1), opposite_hit_rate=round(100 * sum(opp[c]) / len(v), 1)) for c, v in by.items()},
                base_up=round(100 * sum(m > 0 for m in allm) / len(allm), 1) if allm else None,
                base_down=round(100 * sum(m < 0 for m in allm) / len(allm), 1) if allm else None,
                base_flat=round(100 * sum(abs(m) <= BAND[h] for m in allm) / len(allm), 1) if allm else None)


def rules_backtest(live, rates, rows, ds):
    r = RULES; h = r["call_days"]
    # dip rule on ~10 years of gold in rupees (COMEX x USD/INR), 30-day outcome
    dip, dated, alld = [], [], []
    for d in ds[250:]:
        p0 = val(rows, ds, d - timedelta(days=r["dip_days"]), "intl")
        r_d, rr = realised(rows, ds, d, h)
        if not rr:
            continue
        mv = 100 * (rr["intl"] / rows[d]["intl"] - 1); alld.append(mv)
        c = dip_call(100 * (rows[d]["intl"] / p0 - 1)) if p0 else None
        if c:
            dip.append((c, mv)); dated.append((d, c, mv))
    dip_bt = summarise(dip, h); dip_bt.update(start=ds[250].isoformat(), data="COMEX gold x USD/INR (ECB), daily, before duty",
                                              all_days=dict(n=len(alld), up_pct=round(100 * sum(m > 0 for m in alld) / len(alld), 1), down_pct=round(100 * sum(m < 0 for m in alld) / len(alld), 1)))
    # recent check: the last 180 days of realised signals
    cut = dated[-1][0] - timedelta(days=RECENT_DAYS) if dated else None
    rec = summarise([(c, mv) for d, c, mv in dated if d >= cut], h) if dated else None
    dip_bt["recent"] = dict(since=cut.isoformat() if cut else None, **(rec or {}))
    # premium rule and combined call on the IBJA history the app holds
    ps = premium_series(live, rates, rows, ds)
    ib = Series(live["items"]["ibja999_pm"]["history"])
    prem, comb = [], []
    for d, pv in ps:
        dd = D(d); v0 = ib.at(dd)
        r_d, v1 = ib.first_on_or_after(dd + timedelta(days=h))
        if v1 is None:
            continue
        mv = 100 * (v1 / v0 - 1)
        c1 = prem_call(pv)
        if c1:
            prem.append((c1, mv))
        p0 = val(rows, ds, dd - timedelta(days=r["dip_days"]), "intl"); p1 = val(rows, ds, dd, "intl")
        c2 = dip_call(100 * (p1 / p0 - 1)) if p0 and p1 else None
        comb.append((c1, c2, mv))
    prem_bt = summarise(prem, h)
    def active(b, c):
        x = b["by_call"].get(c)
        return bool(x and x["n"] >= MIN_N and x["hit_rate"] > x["opposite_hit_rate"])
    act = {"dip_buy": active(dip_bt, "buy now"), "dip_wait": active(dip_bt, "wait"), "prem_buy": active(prem_bt, "buy now"), "prem_wait": active(prem_bt, "wait")}
    def failing(c):
        x = (dip_bt.get("recent") or {}).get("by_call", {}).get(c)
        return bool(x and x["n"] >= 5 and x["hit_rate"] < x["opposite_hit_rate"])
    recent_fail = {"dip_buy": failing("buy now"), "dip_wait": failing("wait")}
    comb = [(combine([gate(c1, "prem", act), gate(c2, "dip", act)]), mv) for c1, c2, mv in comb]
    comb_bt = summarise(comb, h)
    for b in (prem_bt, comb_bt):
        b.update(start=ps[0][0] if ps else None, data="IBJA 999 closing rate (only the ~4 months of IBJA history the app holds; too few for a firm verdict)")
    return dict(dip=dip_bt, premium=prem_bt, combined=comb_bt, active=act, recent_fail=recent_fail), ps


def gate(c, rule, act):
    """A rule side drives the call only if, in the back-test, it was right more often than the opposite action (min. MIN_N signals)."""
    if not c:
        return None
    return c if act[f"{rule}_{'buy' if c == 'buy now' else 'wait'}"] else None


def main():
    live = json.loads(LIVE.read_text()); rates = json.loads(RATES.read_text())
    now = datetime.now(IST); today = now.date()
    rows, ds = build(live)
    last = ds[-1]
    model = json.loads(MODEL.read_text()) if MODEL.exists() else {"changelog": []}
    ledger = json.loads(PRED.read_text()) if PRED.exists() else {"predictions": []}
    it = live["items"]
    repo = it.get("repo", {}).get("value")
    ib = Series(it["ibja999_pm"]["history"]); ib_last_d = ib.d[-1]; ib_last = ib.v[-1]

    # ---- 1. learn: a variable keeps weight only if it lowered walk-forward error ----
    new, bt = {}, {}
    for h in (7, 30):
        tab = table(rows, ds, h)
        naive = backtest(tab, h, (0, 0, 0, 0))["naive_mae_pct"]
        mask, why = [1] * len(VARS), {}
        full = backtest(tab, h, tuple(mask))["mae_pct"]
        for j, v in enumerate(VARS):
            trial = list(mask); trial[j] = 0
            without = backtest(tab, h, tuple(trial))["mae_pct"] if any(trial) else naive
            if not (full <= without * 0.99):
                mask = trial
                why[v] = f"weight set to 0: walk-forward error {full}% with it vs {without}% without it, so it did not cut error by at least 1%"
                full = without
            else:
                why[v] = f"earned weight: walk-forward error {full}% with it vs {without}% without it"
        if any(mask) and not (full <= naive * 0.99):
            for j, v in enumerate(VARS):
                if mask[j]:
                    why[v] += f"; but the combined model ({full}%) did not beat 'assume no change' ({naive}%) by 1%, so weight set to 0"
            mask = [0] * len(VARS)
        b = backtest(tab, h, tuple(mask))
        if not any(mask):
            b["mae_pct"] = b["naive_mae_pct"]; b["hit_rate"] = b["naive_hit_rate"]
        model_full = backtest(tab, h, (1, 1, 1, 1))   # what the un-gated model would have scored, for transparency
        b["ungated_hit_rate"] = model_full["hit_rate"]; b["ungated_mae_pct"] = model_full["mae_pct"]
        bt[str(h)] = b
        f = fit(tab, tuple(mask)) if any(mask) else (np.zeros(len(VARS)), 0.0, len(tab))
        w, mse, n = f
        new[str(h)] = dict(gate=dict(mask=mask, why=why), weights={v: round(float(w[j]), 4) for j, v in enumerate(VARS)},
                           train_n=n, train_first=ds[0].isoformat(), train_last=last.isoformat(), error_band_pct=b["err_band_pct"])
    old = model.get("horizons", {})
    changes = []
    for h, nh in new.items():
        oh = old.get(h)
        if not oh:
            changes.append(f"{h}-day model first fitted on {nh['train_n']} realised outcomes: " + (
                "no variable (momentum, real yield, dollar, rupee) beat 'assume no change' in the walk-forward test, so all weights are 0 and the forecast is 'no change'."
                if not any(nh["gate"]["mask"]) else ", ".join(f"{k} {v}" for k, v in nh["weights"].items()) + "."))
            continue
        for v in VARS:
            if abs(nh["weights"][v] - oh["weights"][v]) >= 0.02:
                changes.append(f"{h}-day {v} weight {oh['weights'][v]} -> {nh['weights'][v]} after re-fitting on {nh['train_n']} realised outcomes (data to {nh['train_last']}).")
            j = VARS.index(v)
            if oh["gate"]["mask"][j] != nh["gate"]["mask"][j]:
                changes.append(f"{h}-day {v}: " + ("earned weight" if nh["gate"]["mask"][j] else "lost its weight") + f" ({nh['gate']['why'][v]}).")

    # ---- 2. score matured live predictions (on the IBJA closing rate) ----
    scored_now = []
    for p in ledger["predictions"]:
        if p.get("scored"):
            continue
        r_d, v1 = ib.first_on_or_after(D(p["made_on"]) + timedelta(days=p["horizon_days"]))
        if v1 is None:
            continue
        v0 = p["inputs"]["ibja_rs"]; mv = 100 * (v1 / v0 - 1)
        p.update(scored=True, realised_on=r_d.isoformat(), realised_ibja_rs=v1, realised_pct=round(mv, 2))
        if p.get("pred_pct") is not None:
            p.update(error_rs=round(p["pred_ibja_rs"] - v1, 0), hit_direction=direction(mv, p["horizon_days"]) == p["direction"])
        if p.get("buy_call"):
            p["hit_buy_call"] = call_hit(p["buy_call"], mv, p["horizon_days"])
        scored_now.append(p)

    rb, ps = rules_backtest(live, rates, rows, ds)
    oa = model.get("rules", {}).get("backtest", {}).get("active")
    names = {"dip_buy": "'buy after a dip'", "dip_wait": "'wait after a jump'", "prem_buy": "'buy when India is at a discount'", "prem_wait": "'wait when India is at a premium'"}
    for k, v in rb["active"].items():
        if oa is None or oa.get(k) != v:
            src = rb["dip"] if k.startswith("dip") else rb["premium"]; x = src["by_call"].get("buy now" if k.endswith("buy") else "wait") or {}
            changes.append(f"Rule {names[k]} " + ("is used for the call" if v else "is NOT used for the call") +
                           f": back-test right {x.get('hit_rate', '-')}% of {x.get('n', 0)} signals vs {x.get('opposite_hit_rate', '-')}% for the opposite action" + ("" if x.get("n", 0) >= MIN_N else f" (needs at least {MIN_N} signals)") + ".")
    version = f"{VERSION_BASE}.{len(model.get('changelog', [])) + (1 if changes else 0)}"
    if changes:
        model.setdefault("changelog", []).insert(0, {"date": today.isoformat(), "version": version, "changes": changes})
    model.update(version=version, updated_ist=now.strftime("%Y-%m-%d %H:%M IST"), horizons=new, backtest=bt, rules=dict(params=RULES, backtest=rb),
                 premium_history=ps[-120:], data_last_date=last.isoformat(), ibja_last_date=ib_last_d.isoformat(), formula=__doc__.strip(),
                 band_pct=BAND, cc_spread_assumption_pct=CC_SPREAD)

    # ---- 3. log today's predictions (once per IBJA closing date) ----
    stale = (today - ib_last_d).days > 4
    if not stale and not any(p["made_on"] == ib_last_d.isoformat() for p in ledger["predictions"]):
        dd = ib_last_d
        prem = ps[-1][1] if ps and ps[-1][0] == dd.isoformat() else None
        p0 = val(rows, ds, dd - timedelta(days=RULES["dip_days"]), "intl"); p1 = val(rows, ds, dd, "intl")
        move = 100 * (p1 / p0 - 1) if p0 and p1 else None
        c1, c2 = prem_call(prem), dip_call(move)
        base = dict(made_on=dd.isoformat(), logged_ist=now.strftime("%Y-%m-%d %H:%M IST"), model_version=version)
        for h in (7, 30):
            m = new[str(h)]; x = features(rows, ds, val_day(ds, dd), h)
            pct = sum(m["weights"][v] * x[j] for j, v in enumerate(VARS)) if x else 0.0
            edge = bool(any(m["gate"]["mask"]) and bt[str(h)]["mae_pct"] < bt[str(h)]["naive_mae_pct"])
            ledger["predictions"].append(dict(id=f"{dd}-{h}d", kind="model", horizon_days=h, target_date=(dd + timedelta(days=h)).isoformat(),
                                              pred_pct=round(pct, 3), direction=direction(pct, h), pred_ibja_rs=round(ib_last * (1 + pct / 100), 0),
                                              error_band_pct=m["error_band_pct"], model_has_edge=edge,
                                              inputs=dict(ibja_rs=ib_last, features=[round(v, 3) for v in x] if x else None, weights=m["weights"]), **base))
        m30 = ledger["predictions"][-1]
        act = model["rules"]["backtest"]["active"]
        rule_call = combine([gate(c1, "prem", act), gate(c2, "dip", act)])
        call = rule_call
        basis = "rules"
        rf = model["rules"]["backtest"]["recent_fail"]
        downgraded = None
        g2 = gate(c2, "dip", act)
        if g2 and rf.get("dip_buy" if g2 == "buy now" else "dip_wait") and call != "buy part":
            downgraded = f"'{call}' softened to 'buy part': the dip rule has been wrong more often than right in the last {RECENT_DAYS} days of the back-test"
            call = "buy part"
        if m30["model_has_edge"]:
            call = "buy now" if m30["direction"] == "up" else "wait" if m30["direction"] == "down" else "buy part"; basis = "model"
        news_flag = duty_cut_news(live, dd)
        if news_flag and call == "buy now":
            downgraded = f"'buy now' softened to 'buy part': recent headline about a possible import-duty cut ({news_flag['date']}: {news_flag['title'][:120]})"
            call = "buy part"
        ledger["predictions"].append(dict(id=f"{dd}-call", news_flag=news_flag, kind="call", horizon_days=RULES["call_days"], target_date=(dd + timedelta(days=RULES["call_days"])).isoformat(),
                                          buy_call=call, raw_call=rule_call, downgraded=downgraded, basis=basis, rule_premium=c1, rule_dip=c2, rules_active=act,
                                          inputs=dict(ibja_rs=ib_last, premium_pct=prem, gold_rupee_move_pct=round(move, 2) if move is not None else None,
                                                      rules=RULES, repo_pct=repo), **base))
    # ---- 4. live track record and lessons ----
    sc = [p for p in ledger["predictions"] if p.get("scored")]
    lessons = []
    for h in ("7", "30"):
        b = bt[h]
        lessons.append(f"{h}-day back-test ({b['start']} to {b['end']}, {b['n']} calls, gold in rupees): direction right {b['hit_rate']}% vs {b['naive_hit_rate']}% for 'assume no change'; "
                       f"average error {b['mae_pct']}% vs {b['naive_mae_pct']}%. Un-gated model (all four variables): {b['ungated_hit_rate']}% right, error {b['ungated_mae_pct']}%.")
        if not any(new[h]["gate"]["mask"]):
            lessons.append(f"{h}-day: no variable has proven predictive value, so the model forecast is 'no change' and it is not used for the call. Gold behaves close to a random walk.")
    d = rb["dip"]
    lessons.append(f"Rule 'buy on a {RULES['dip_pct']}% dip, wait after a {RULES['dip_pct']}% jump' (30-day outcome, since {d['start']}): right {d['hit_rate']}% of {d['n']} signals "
                   f"({', '.join(f'{k}: {v['hit_rate']}% of {v['n']}, opposite action {v['opposite_hit_rate']}%' for k, v in d['by_call'].items())}).")
    pb = rb["premium"]
    lessons.append(f"Rule 'premium/discount above {RULES['prem_pct']}%': {pb['n']} signals in the IBJA history held" + (f", right {pb['hit_rate']}% ({', '.join(f'{k}: {v['hit_rate']}% of {v['n']}' for k, v in pb['by_call'].items())})." if pb["n"] else "; nothing to score yet."))
    a = rb["active"]
    lessons.append("Rule sides used for today's call: " + (", ".join(names[k] for k, v in a.items() if v) or "none") + ". Not used: " + (", ".join(names[k] for k, v in a.items() if not v) or "none") + ".")
    if len(sc) < 10:
        lessons.append(f"Live track record: learning, too few results yet ({len(sc)} scored).")
    model["lessons"] = lessons
    ledger["predictions"] = ledger["predictions"][-2000:]
    PRED.write_text(json.dumps(ledger, indent=0))
    cols = ["id", "kind", "made_on", "horizon_days", "target_date", "model_version", "buy_call", "basis", "direction", "pred_pct", "pred_ibja_rs", "error_band_pct",
            "model_has_edge", "scored", "realised_on", "realised_ibja_rs", "realised_pct", "error_rs", "hit_direction", "hit_buy_call"]
    with open(ROOT / "data/track_record.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(cols + ["ibja_rs_at_call", "premium_pct_at_call"])
        for p in ledger["predictions"]:
            w.writerow([p.get(c, "") for c in cols] + [p["inputs"].get("ibja_rs"), p["inputs"].get("premium_pct", "")])
    arch = ROOT / "data/models"; arch.mkdir(exist_ok=True)
    if not (arch / f"model_{version}.json").exists():
        (arch / f"model_{version}.json").write_text(json.dumps({k: v for k, v in model.items() if k != "premium_history"}, indent=1))
    MODEL.write_text(json.dumps(model, indent=1))
    print("model", version, "| last COMEX", last, "| IBJA", ib_last_d, "| scored now", len(scored_now), "| changes", len(changes))
    for l in lessons:
        print(" -", l)


DUTY_CUT = r"(duty|customs|import tax)\b.{0,40}\b(cut|reduc|lower|slash|roll ?back)|\b(cut|reduc|lower|slash|roll ?back)\w*\b.{0,40}\b(duty|customs|import tax)"


def duty_cut_news(live, d, days=21):
    """News can only make the call more cautious: a recent headline about a gold import-duty cut (which would lower Indian prices)."""
    import re
    for h in live.get("headlines", []):
        if (d - D(h["date"])).days <= days and re.search(DUTY_CUT, h["title"], re.I) and re.search(r"gold", h["title"], re.I):
            return dict(date=h["date"], title=h["title"], url=h["url"])
    return None


def val_day(ds, day):
    i = bisect.bisect_right(ds, day) - 1
    return ds[i]


if __name__ == "__main__":
    main()
