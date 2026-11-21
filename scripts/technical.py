"""Technical view: standard chart indicators on gold in rupees, each back-tested walk-forward before it may count.

Series: international gold in rupees before duty (Rs/10 g) = COMEX close x USD/INR (ECB) / 31.1035 x 10; daily highs and
lows the same way from COMEX highs/lows (for ATR, Donchian and swing levels). About 10 years of daily data (2016 on).
No look-ahead: every reading on day t uses data up to t only; a swing high/low becomes a level only K days after it.
Each indicator gives +1 (points up), -1 (points down) or 0 (no signal).
Scores, for horizons of 5, 10 and 21 trading days:
  hit rate      = share of signal days where the price moved the way the signal pointed; compared with
                  'always assume the usual direction' (the drift) on the same days
  error         = forecast a + b*signal, re-fitted every 21 trading days on outcomes already known; compared with
                  'no change' (0) and with the drift alone (a)
  decision value= a buyer who must hold gold by day N: signal up -> buy now (pays carrying cost), down -> buy on day N,
                  none -> half and half; average cost compared with buying immediately and with buying on day N
Gate (same rule as the model): an indicator may feed the main call only if, at 21 trading days (about 30 calendar days,
the call's window), it cuts walk-forward error by at least 1% versus the drift alone AND versus 'no change'.
Numbers only from data/live.json; plain arithmetic, no AI."""
import bisect
from datetime import date
import numpy as np

OZ = 31.1034768
HORIZONS = (5, 10, 21)
GATE_H = 21
CARRY = 0.12           # 12% a year carrying cost (interest + storage) for the decision test
K_SWING = 5            # swing high/low = extreme of 5 days either side; confirmed 5 days later
LOOKBACK = 120         # levels from swings in the last 120 trading days
HOLD_WIN = 10          # a touched level 'held' if price moves 1 ATR away before closing 1 ATR through it, within 10 days
PERIODS = [("2017-18", 2017, 2018), ("2019-20", 2019, 2020), ("2021-22", 2021, 2022), ("2023-24", 2023, 2024), ("2025-26", 2025, 2026)]
MIN_TRAIN = 500


def _at(ds, vs, d):
    i = bisect.bisect_right(ds, d) - 1
    return vs[i] if i >= 0 else None


def series(live):
    it = live["items"]
    g = it["comex"]["history"]; fx = it["usdinr_ecb"]["history"]
    fd = [x[0] for x in fx]; fv = [x[1] for x in fx]
    hl = {d: (h, l) for d, h, l in it["comex"].get("hl", [])}
    ds, c, hi, lo = [], [], [], []
    for d, v in g:
        r = _at(fd, fv, d)
        if r is None:
            continue
        k = r / OZ * 10
        h, l = hl.get(d, (v, v))
        ds.append(d); c.append(v * k); hi.append(max(h, v) * k); lo.append(min(l, v) * k)
    return ds, np.array(c), np.array(hi), np.array(lo), bool(hl)


def sma(x, n):
    out = np.full(len(x), np.nan); cs = np.cumsum(np.insert(x, 0, 0.0))
    out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def rstd(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = np.std(x[i - n + 1:i + 1], ddof=1)
    return out


def ema(x, span=None, alpha=None):
    a = alpha if alpha is not None else 2 / (span + 1)
    out = np.full(len(x), np.nan); first = None
    for i, v in enumerate(x):
        if np.isnan(v):
            continue
        out[i] = v if first is None else a * v + (1 - a) * out[i - 1]
        first = 1
    return out


def rsi(c, n=14):
    d = np.diff(c, prepend=np.nan)
    up = ema(np.where(np.isnan(d), np.nan, np.clip(d, 0, None)), alpha=1 / n)
    dn = ema(np.where(np.isnan(d), np.nan, np.clip(-d, 0, None)), alpha=1 / n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100 - 100 / (1 + up / dn)


def atr(c, hi, lo, n=14):
    pc = np.insert(c[:-1], 0, np.nan)
    tr = np.nanmax(np.vstack([hi - lo, np.abs(hi - pc), np.abs(lo - pc)]), axis=0)
    return ema(tr, alpha=1 / n)


def roll_max_prev(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n, len(x)):
        out[i] = x[i - n:i].max()
    return out


def roll_min_prev(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n, len(x)):
        out[i] = x[i - n:i].min()
    return out


def indicators(c, hi, lo):
    """Raw readings and +1/0/-1 signals for every day (each uses data up to that day only)."""
    ma = {n: sma(c, n) for n in (20, 50, 200)}
    macd = ema(c, 12) - ema(c, 26); sig = ema(macd, 9)
    r = rsi(c); sd = rstd(c, 20)
    up = {n: roll_max_prev(hi, n) for n in (20, 55)}; dn = {n: roll_min_prev(lo, n) for n in (20, 55)}
    sg = np.sign
    S = {}
    for n in (20, 50, 200):
        S[f"ma{n}"] = sg(c - ma[n])
    S["ma50_200"] = sg(ma[50] - ma[200])
    S["ma20_50"] = sg(ma[20] - ma[50])
    x = sg(ma[50] - ma[200]); fresh = np.zeros(len(c))
    for i in range(10, len(c)):
        if not np.isnan(x[i]) and not np.isnan(x[i - 10]) and x[i] != x[i - 10]:
            fresh[i] = x[i]
    S["cross_fresh"] = fresh
    S["rsi_rev"] = np.where(r < 30, 1, np.where(r > 70, -1, 0)).astype(float)
    S["rsi_mom"] = sg(r - 50)
    S["macd_sig"] = sg(macd - sig)
    S["macd_zero"] = sg(macd)
    for n in (20, 55):
        S[f"don{n}"] = np.where(c > up[n], 1, np.where(c < dn[n], -1, 0)).astype(float)
    bb = np.where(c < ma[20] - 2 * sd, 1, np.where(c > ma[20] + 2 * sd, -1, 0)).astype(float)
    S["bb_rev"] = bb; S["bb_brk"] = -bb
    for k in S:
        S[k] = np.where(np.isnan(ma[200]), np.nan, S[k])   # one common sample: needs 200 days of history
    raw = dict(ma20=ma[20], ma50=ma[50], ma200=ma[200], rsi=r, macd=macd, macd_sig=sig, bb_lo=ma[20] - 2 * sd, bb_hi=ma[20] + 2 * sd,
               don20_hi=up[20], don20_lo=dn[20], don55_hi=up[55], don55_lo=dn[55])
    return S, raw


NAMES = {
    "ma20": "Price above/below 20-day average", "ma50": "Price above/below 50-day average", "ma200": "Price above/below 200-day average",
    "ma50_200": "50-day average above/below 200-day (golden/death cross state)", "ma20_50": "20-day average above/below 50-day",
    "cross_fresh": "Fresh 50/200-day cross (last 10 days)", "rsi_rev": "RSI(14): below 30 = up, above 70 = down (reversal reading)",
    "rsi_mom": "RSI(14) above/below 50 (momentum reading)", "macd_sig": "MACD above/below its signal line", "macd_zero": "MACD above/below zero",
    "don20": "20-day breakout (Donchian)", "don55": "55-day breakout (Donchian)",
    "bb_rev": "Bollinger: below lower band = up, above upper = down (reversal)", "bb_brk": "Bollinger: above upper band = up (breakout reading)",
}


def walk_error(s, y, h):
    n = len(y); idx = np.arange(n); f = np.full(n, np.nan); dr = np.full(n, np.nan); last = -10 ** 9; coef = d0 = None
    for i in range(n):
        if np.isnan(s[i]) or np.isnan(y[i]):
            continue
        if i - last >= 21 or coef is None:
            m = (idx <= i - h) & ~np.isnan(s) & ~np.isnan(y)
            if m.sum() < MIN_TRAIN:
                continue
            X = np.c_[np.ones(m.sum()), s[m]]; coef = np.linalg.lstsq(X, y[m], rcond=None)[0]; d0 = y[m].mean(); last = i
        f[i] = coef[0] + coef[1] * s[i]; dr[i] = d0
    ok = ~np.isnan(f)
    if ok.sum() == 0:
        return None
    return dict(n=int(ok.sum()), mae=float(np.abs(y[ok] - f[ok]).mean() * 100), mae_nochange=float(np.abs(y[ok]).mean() * 100),
                mae_drift=float(np.abs(y[ok] - dr[ok]).mean() * 100))


def decision(s, c, h):
    out = []
    for i in range(len(c) - h):
        if np.isnan(s[i]):
            continue
        now = CARRY * h / 252; jit = c[i + h] / c[i] - 1
        rule = now if s[i] > 0 else jit if s[i] < 0 else 0.5 * (now + jit)
        out.append((now, jit, rule))
    a = np.array(out)
    return dict(cost_rule=float(a[:, 2].mean() * 100), cost_now=float(a[:, 0].mean() * 100), cost_wait=float(a[:, 1].mean() * 100),
                save_vs_now=float((a[:, 0] - a[:, 2]).mean() * 100), save_vs_wait=float((a[:, 1] - a[:, 2]).mean() * 100)), a


def score(S, c, ds):
    lc = np.log(c); years = np.array([int(d[:4]) for d in ds])
    res = {}
    for k, s in S.items():
        r = {"name": NAMES[k]}
        for h in HORIZONS:
            y = np.full(len(c), np.nan); y[:-h] = lc[h:] - lc[:-h]
            ok = ~np.isnan(s) & ~np.isnan(y); act = ok & (s != 0)
            drift_up = np.mean(y[ok]) > 0
            hit = float(np.mean(np.sign(y[act]) == s[act]) * 100) if act.any() else None
            base = float(np.mean((y[act] > 0) == drift_up) * 100) if act.any() else None
            e = walk_error(s, y, h)
            dv, _ = decision(s, c, h)
            sub = {}
            for pn, a, b in PERIODS:
                m = act & (years >= a) & (years <= b)
                if m.sum() >= 20:
                    sub[pn] = dict(n=int(m.sum()), hit=round(float(np.mean(np.sign(y[m]) == s[m]) * 100), 1), drift=round(float(np.mean((y[m] > 0) == drift_up) * 100), 1))
            beats = sum(1 for v in sub.values() if v["hit"] > v["drift"])
            cut_d = (1 - e["mae"] / e["mae_drift"]) * 100 if e else None; cut_0 = (1 - e["mae"] / e["mae_nochange"]) * 100 if e else None
            r[str(h)] = dict(signals=int(act.sum()), days=int(ok.sum()), hit=round(hit, 1) if hit is not None else None, drift_hit=round(base, 1) if base is not None else None,
                             mae=round(e["mae"], 3) if e else None, mae_nochange=round(e["mae_nochange"], 3) if e else None, mae_drift=round(e["mae_drift"], 3) if e else None,
                             err_cut_vs_drift=round(cut_d, 2) if e else None, err_cut_vs_nochange=round(cut_0, 2) if e else None,
                             passes=bool(e and e["mae"] <= 0.99 * e["mae_drift"] and e["mae"] <= 0.99 * e["mae_nochange"]),
                             decision={kk: round(v, 3) for kk, v in dv.items()}, periods=sub, periods_beating_drift=f"{beats} of {len(sub)}")
        r["passes_gate"] = r[str(GATE_H)]["passes"]
        res[k] = r
    return res


def swings(hi, lo):
    n = len(hi); K = K_SWING
    sl = [j for j in range(K, n - K) if lo[j] == lo[j - K:j + K + 1].min()]
    sh = [j for j in range(K, n - K) if hi[j] == hi[j - K:j + K + 1].max()]
    return sl, sh


def level_at(t, kind, c, hi, lo, sl, sh):
    """Nearest confirmed swing level below (support) or above (resistance) the previous close, known before day t opens (confirmed by the close of day t-1)."""
    if kind == "sup":
        lv = [lo[j] for j in sl if j + K_SWING <= t - 1 and t - j <= LOOKBACK and lo[j] < c[t - 1]]
        return max(lv) if lv else None
    lv = [hi[j] for j in sh if j + K_SWING <= t - 1 and t - j <= LOOKBACK and hi[j] > c[t - 1]]
    return min(lv) if lv else None


def _touched(t, L, kind, c, hi, lo, a):
    return (lo[t] <= L + 0.5 * a[t] and c[t - 1] > L + 0.5 * a[t]) if kind == "sup" else (hi[t] >= L - 0.5 * a[t] and c[t - 1] < L - 0.5 * a[t])


def _outcome(t, L, kind, c, a):
    for u in range(t, min(len(c), t + HOLD_WIN + 1)):
        if kind == "sup":
            if c[u] < L - a[t]:
                return "break"
            if u > t and c[u] >= L + a[t]:
                return "hold"
        else:
            if c[u] > L + a[t]:
                return "break"
            if u > t and c[u] <= L - a[t]:
                return "hold"
    return "none"


def levels_test(c, hi, lo, a, ds):
    """Touch-and-hold rate of real swing levels vs random levels at the same distance (in ATRs) on random days."""
    sl, sh = swings(hi, lo); n = len(c); rng = np.random.default_rng(1); out = {}
    years = [int(d[:4]) for d in ds]
    for kind in ("sup", "res"):
        ev, dist = [], []
        for t in range(200, n):
            L = level_at(t, kind, c, hi, lo, sl, sh)
            if L is None or np.isnan(a[t]):
                continue
            if _touched(t, L, kind, c, hi, lo, a):
                ev.append((years[t], _outcome(t, L, kind, c, a))); dist.append(abs(c[t - 1] - L) / a[t])
        rb, tries = [], 0
        while dist and len(rb) < 5000 and tries < 400000:
            tries += 1; u = int(rng.integers(200, n)); d = dist[int(rng.integers(len(dist)))]
            L = c[u - 1] - d * a[u] if kind == "sup" else c[u - 1] + d * a[u]
            if _touched(u, L, kind, c, hi, lo, a):
                rb.append((years[u], _outcome(u, L, kind, c, a)))

        def rate(x):
            x = [o for _, o in x if o != "none"]
            return (round(100 * sum(o == "hold" for o in x) / len(x), 1) if x else None, len(x))
        per = {pn: dict(real=rate([e for e in ev if a_ <= e[0] <= b_]), random=rate([e for e in rb if a_ <= e[0] <= b_])) for pn, a_, b_ in PERIODS}
        hr, nn = rate(ev); rr, rn = rate(rb)
        out[kind] = dict(touches=len(ev), decided=nn, hold_pct=hr, random_hold_pct=rr, random_n=rn, periods=per,
                         undecided_pct=round(100 * sum(o == "none" for _, o in ev) / len(ev), 1) if ev else None)
    return out, sl, sh


def range_test(c, a, h=5):
    """80% range for the next h trading days, two ways, scored walk-forward:
    'blend': exponentially weighted recent volatility mixed half-and-half with 1-year volatility, times past quantiles of standardised moves;
    'atr'  : ATR(14)/price times past quantiles of standardised moves."""
    lc = np.log(c); r = np.diff(lc, prepend=np.nan); r[0] = 0.0
    ew = np.sqrt(ema(r ** 2, alpha=0.06))
    v252 = np.full(len(c), np.nan)
    for i in range(251, len(c)):
        v252[i] = np.std(r[i - 251:i + 1], ddof=1)
    blend = np.sqrt(0.5 * ew ** 2 + 0.5 * v252 ** 2)
    y = np.full(len(c), np.nan); y[:-h] = lc[h:] - lc[:-h]
    res = {}
    for name, sc in (("blend", blend * np.sqrt(h)), ("atr", a / c * np.sqrt(h))):
        inside, wid, scales, last = [], [], [], None
        z = y / sc
        for i in range(500, len(c)):
            past = z[:i - h + 1]; past = past[~np.isnan(past)]
            if len(past) < 250 or np.isnan(sc[i]):
                continue
            q10, q90 = np.quantile(past, 0.1), np.quantile(past, 0.9)
            lo_, hi_ = q10 * sc[i], q90 * sc[i]; last = (lo_, hi_)
            if not np.isnan(y[i]):
                inside.append(lo_ <= y[i] <= hi_); wid.append(hi_ - lo_); scales.append(sc[i])
        inside = np.array(inside); scales = np.array(scales); q1, q2 = np.quantile(scales, [1 / 3, 2 / 3])
        res[name] = dict(n=int(len(inside)), coverage=round(float(inside.mean() * 100), 1), calm=round(float(inside[scales <= q1].mean() * 100), 1),
                         turbulent=round(float(inside[scales > q2].mean() * 100), 1), width_pct=round(float(np.mean(wid) * 100), 2),
                         today_lo_pct=round(float((np.exp(last[0]) - 1) * 100), 2), today_hi_pct=round(float((np.exp(last[1]) - 1) * 100), 2))
        res[name]["calibrated"] = bool(75 <= res[name]["coverage"] <= 85 and res[name]["calm"] >= 70 and res[name]["turbulent"] >= 70)
    return res


def run(live):
    ds, c, hi, lo, has_hl = series(live)
    S, raw = indicators(c, hi, lo)
    a = atr(c, hi, lo)
    sc = score(S, c, ds)
    lv, sl, sh = levels_test(c, hi, lo, a, ds)
    rg = range_test(c, a, 5)
    t = len(c)   # levels known for the next session use all data to the last day
    sup = [lo[j] for j in sl if j + K_SWING <= t - 1 and t - 1 - j <= LOOKBACK and lo[j] < c[-1]]
    res = [hi[j] for j in sh if j + K_SWING <= t - 1 and t - 1 - j <= LOOKBACK and hi[j] > c[-1]]
    sup = sorted(sup, reverse=True)[:2]; res = sorted(res)[:2]
    i = len(c) - 1
    now = dict(date=ds[i], close=round(float(c[i]), 0), atr=round(float(a[i]), 0), atr_pct=round(float(a[i] / c[i] * 100), 2),
               rsi=round(float(raw["rsi"][i]), 1), macd=round(float(raw["macd"][i]), 0), macd_signal=round(float(raw["macd_sig"][i]), 0),
               **{k: round(float(raw[k][i]), 0) for k in ("ma20", "ma50", "ma200", "bb_lo", "bb_hi", "don20_hi", "don20_lo", "don55_hi", "don55_lo")},
               signals={k: int(S[k][i]) for k in S}, supports=[round(float(x), 0) for x in sup], resistances=[round(float(x), 0) for x in res])
    return dict(series="International gold in rupees before duty (Rs/10 g) = COMEX gold x USD/INR (ECB) / 31.1035 x 10; highs/lows the same way",
                has_high_low=has_hl, first_date=ds[0], last_date=ds[-1], days=len(ds), horizons=list(HORIZONS), gate_horizon=GATE_H, carry_pct=CARRY * 100,
                indicators=sc, levels=lv, ranges=rg, now=now, method=__doc__.strip(),
                passed=[k for k, v in sc.items() if v["passes_gate"]])


def vote(tech):
    """Signals of indicators that passed the gate, as calls for the main 30-day call."""
    out = []
    for k in tech.get("passed", []):
        s = tech["now"]["signals"].get(k, 0)
        if s:
            out.append("buy now" if s > 0 else "wait")
    return out


if __name__ == "__main__":
    import json, time
    from pathlib import Path
    t0 = time.time()
    T = run(json.loads((Path(__file__).resolve().parent.parent / "data/live.json").read_text()))
    print(round(time.time() - t0, 1), "s")
    for k, v in T["indicators"].items():
        print(f"{v['name'][:55]:55s}", " | ".join(f"{h}d hit {v[str(h)]['hit']} vs {v[str(h)]['drift_hit']} cut {v[str(h)]['err_cut_vs_drift']}" for h in HORIZONS), "PASS" if v["passes_gate"] else "")
    print(json.dumps(T["levels"], indent=0)[:1500]); print(T["ranges"]); print(T["now"])
