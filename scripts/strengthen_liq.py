"""Robustness extensions answering the referee's first three questions.

(1) CLASSIFICATION VALIDATION — does the OI-based deleverage/churn split actually
    track liquidation pressure? We check whether deleverage-classified events carry
    larger liquidation notional than churn events, and whether OI destruction and
    liquidation intensity are correlated across all events. If yes, the open-interest
    proxy is not arbitrary: it picks up genuine forced-selling pressure.

(2) CONTINUOUS MEASURE — instead of the deleverage/churn dummies, regress outcomes
    directly on continuous OI destruction (−ΔOI), controlling for liquidation size.
    This shows the result is not an artifact of an arbitrary bucket cut.

(3) EVENT-WINDOW SENSITIVITY — re-run the headline contrasts varying the trough
    window (2h), recovery horizon (24h), and merge rule (120 min), one at a time.

Plus ECONOMIC SIGNIFICANCE: the ≈0.55pp size-controlled effect expressed relative
to the median dislocation and to daily volatility.

Inputs: the per-coin hyperliquid_{BTC,ETH}_{liquidations,klines,oi} datasets and
event_table_liq. Outputs: paper/strengthening_results.md + console.

Run:  python strengthen_liq.py
"""
import os

import numpy as np
import pandas as pd

import build_event_table_liq as B
from analyze_liq_events import logrank, perm_test
from config import load_df
from robustness_liq import _prep, all_events, build_events

PAPER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COINS = ["BTC", "ETH"]
N_PERM = 10000
SEED = 0


def _f(x, d=4):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"


# ---------- continuous-regressor OLS with permutation inference ----------
def ols_perm_cont(d, ycol, xcol, controls, n=N_PERM, seed=SEED):
    d = d.dropna(subset=[ycol, xcol] + controls)
    if len(d) < 15:
        return np.nan, np.nan, len(d)
    y = d[ycol].to_numpy(float)
    x = d[xcol].to_numpy(float)
    ctrl = [d[c].to_numpy(float) for c in controls]

    def coef(xv):
        X = np.column_stack([np.ones(len(d)), xv] + ctrl)
        return np.linalg.lstsq(X, y, rcond=None)[0][1]
    obs = coef(x)
    rng = np.random.default_rng(seed)
    perm = x.copy()
    cnt = 0
    for _ in range(n):
        rng.shuffle(perm)
        if abs(coef(perm)) >= abs(obs):
            cnt += 1
    return obs, (cnt + 1) / (n + 1), len(d)


def spearman_perm(x, y, n=N_PERM, seed=SEED):
    """Spearman rank correlation with a permutation p-value (no scipy)."""
    m = ~(pd.isna(x) | pd.isna(y))
    x, y = np.asarray(x)[m], np.asarray(y)[m]
    if len(x) < 15:
        return np.nan, np.nan, len(x)
    rx = pd.Series(x).rank().to_numpy()
    ry = pd.Series(y).rank().to_numpy()
    obs = np.corrcoef(rx, ry)[0, 1]
    rng = np.random.default_rng(seed)
    ryp = ry.copy()
    cnt = 0
    for _ in range(n):
        rng.shuffle(ryp)
        if abs(np.corrcoef(rx, ryp)[0, 1]) >= abs(obs):
            cnt += 1
    return obs, (cnt + 1) / (n + 1), len(x)


# ---------- (1b) EXTERNAL validation (not based on liquidation magnitude) ----------
def adl_validation(ev):
    """ADL incidence by class. Auto-deleveraging is an independent forced-liquidation
    mechanism, recorded separately and NOT used to build the OI classification, so a
    higher ADL rate among deleverage events is external corroboration."""
    series = {}
    for c in COINS:
        try:
            a = load_df(f"hyperliquid_{c}_adl")
            series[c] = a.set_index("ts").sort_index() if len(a) else None
        except FileNotFoundError:
            series[c] = None
    if all(s is None for s in series.values()):
        return None
    flag = []
    for r in ev.itertuples():
        a = series.get(r.symbol)
        if a is None or not len(a):
            flag.append(0.0)
            continue
        w = a.loc[r.t0: r.t0 + pd.Timedelta(hours=2), "notional"]
        flag.append(1.0 if (len(w) and w.sum() > 0) else 0.0)
    ev = ev.assign(adl_flag=flag)
    dele, churn = ev[ev.klass == "deleverage"], ev[ev.klass == "churn"]
    diff, p, nd, nc = perm_test(dele.adl_flag.values, churn.adl_flag.values, stat=np.mean)
    return dict(rate_dele=dele.adl_flag.mean(), rate_churn=churn.adl_flag.mean(),
                n_dele=int(dele.adl_flag.sum()), n_churn=int(churn.adl_flag.sum()),
                diff=diff, p=p, nd=nd, nc=nc)


def funding_validation(ev):
    """Funding-swing by class — external to the OI/liquidation-magnitude split.
    Ex-ante prediction: a forced long-liquidation cascade drives the perp below
    spot, so deleverage events should show a more NEGATIVE funding swing (post
    minus pre) than churn."""
    fund = {}
    for c in COINS:
        try:
            f = load_df(f"hyperliquid_{c}_funding")
            col = next((x for x in ("funding", "funding_rate", "fundingRate") if x in f.columns), None)
            fund[c] = f.set_index("ts").sort_index()[col] if (col and len(f)) else None
        except (FileNotFoundError, KeyError):
            fund[c] = None
    if all(s is None for s in fund.values()):
        return None
    swing = []
    for r in ev.itertuples():
        s = fund.get(r.symbol)
        if s is None:
            swing.append(np.nan)
            continue
        pre = s.loc[r.t0 - pd.Timedelta(hours=1): r.t0].mean()
        post = s.loc[r.t0: r.t0 + pd.Timedelta(hours=2)].mean()
        swing.append(post - pre if (pd.notna(pre) and pd.notna(post)) else np.nan)
    ev = ev.assign(fswing=swing)
    dele, churn = ev[ev.klass == "deleverage"], ev[ev.klass == "churn"]
    diff, p, nd, nc = perm_test(dele.fswing.values, churn.fswing.values, stat=np.median)
    return dict(med_dele=dele.fswing.median(), med_churn=churn.fswing.median(),
                diff=diff, p=p, nd=nd, nc=nc)


def postvol_validation(ev):
    """Post-event realized volatility [t+2h, t+12h] by class — a price-based check
    external to the OI/liquidation-magnitude classification."""
    price = {c: load_df(f"hyperliquid_{c}_klines").set_index("ts").sort_index() for c in COINS}
    rv = []
    for r in ev.itertuples():
        w = price[r.symbol].loc[r.t0 + pd.Timedelta(hours=2): r.t0 + pd.Timedelta(hours=12), "close"]
        ret = np.log(w).diff().dropna()
        rv.append(ret.std() if len(ret) > 3 else np.nan)
    ev = ev.assign(postvol=rv)
    dele, churn = ev[ev.klass == "deleverage"], ev[ev.klass == "churn"]
    diff, p, nd, nc = perm_test(dele.postvol.values, churn.postvol.values, stat=np.median)
    return dict(med_dele=dele.postvol.median(), med_churn=churn.postvol.median(),
                diff=diff, p=p, nd=nd, nc=nc)


# ---------- (1) classification validation ----------
def validate(ev):
    dele = ev[ev.klass == "deleverage"]
    churn = ev[ev.klass == "churn"]
    diff, p, nd, nc = perm_test(np.log(dele.liq_notional), np.log(churn.liq_notional))
    rho, rp, n = spearman_perm(-ev["doi_event"].to_numpy(), ev["liq_notional"].to_numpy())
    return dict(med_liq_dele=dele.liq_notional.median(), med_liq_churn=churn.liq_notional.median(),
                log_liq_diff=diff, log_liq_p=p, nd=nd, nc=nc,
                spearman=rho, spearman_p=rp, n=n)


# ---------- (2) continuous measure ----------
def continuous(ev):
    ev = ev.copy()
    ev["oi_destroyed"] = -ev["doi_event"]           # positive = more OI destroyed
    h2a = ols_perm_cont(ev, "abs_peak", "oi_destroyed", ["log_notional", "asset_eth"])
    h2b = ols_perm_cont(ev, "transitory_share", "oi_destroyed",
                        ["abs_peak", "log_notional", "asset_eth"])
    rec = spearman_perm(ev["oi_destroyed"].to_numpy(), ev["ttr_min"].to_numpy())
    return dict(h2a=h2a, h2b=h2b, rec=rec)


# ---------- (3) event-window sensitivity ----------
def headline(df):
    dele, churn = df[df.klass == "deleverage"], df[df.klass == "churn"]
    pk, pkp, nd, nc = perm_test(dele.peak_disloc.abs(), churn.peak_disloc.abs())
    tr, trp, _, _ = perm_test(dele.transitory_share, churn.transitory_share)
    _, lrp = logrank(dele.ttr_min.values, (~dele.censored).values,
                     churn.ttr_min.values, (~churn.censored).values)
    return nd, nc, pk, pkp, tr, trp, lrp


def window_grid():
    base = dict(trough=B.POST_TROUGH_H, censor=B.CENSOR_H, merge=B.MERGE_MIN)
    rows = []
    variants = ([("trough(h)", "POST_TROUGH_H", v) for v in (1, 2, 3)] +
                [("recovery(h)", "CENSOR_H", v) for v in (12, 24, 48)] +
                [("merge(min)", "MERGE_MIN", v) for v in (60, 120, 180)])
    for label, attr, val in variants:
        setattr(B, "POST_TROUGH_H", base["trough"])
        setattr(B, "CENSOR_H", base["censor"])
        setattr(B, "MERGE_MIN", base["merge"])
        setattr(B, attr, val)
        ev = _prep(all_events(0.99))
        nd, nc, pk, pkp, tr, trp, lrp = headline(ev)
        rows.append(dict(param=label, value=val, n_d=nd, n_c=nc,
                         peak_diff=pk, peak_p=pkp, tr_p=trp, lr_p=lrp))
    setattr(B, "POST_TROUGH_H", base["trough"])
    setattr(B, "CENSOR_H", base["censor"])
    setattr(B, "MERGE_MIN", base["merge"])
    return pd.DataFrame(rows)


# ---------- (4) economic significance ----------
def econ(ev, coef=0.0055):
    out = {}
    for c in COINS:
        k = load_df(f"hyperliquid_{c}_klines").set_index("ts").sort_index()
        daily = k["close"].resample("1D").last().dropna()
        r = np.log(daily).diff().dropna()
        out[c] = dict(daily_vol=r.std(), med_abs_daily=r.abs().median())
    med_dele = ev.loc[ev.klass == "deleverage", "peak_disloc"].abs().median()
    avg_vol = np.mean([out[c]["daily_vol"] for c in COINS])
    out["frac_of_median_dislocation"] = coef / med_dele if med_dele else np.nan
    out["in_daily_sigma"] = coef / avg_vol if avg_vol else np.nan
    out["median_deleverage_dislocation"] = med_dele
    return out


def main():
    ev = _prep(all_events(0.99))
    v = validate(ev)
    adl = adl_validation(ev)
    fund = funding_validation(ev)
    pv = postvol_validation(ev)
    c = continuous(ev)
    grid = window_grid()
    e = econ(ev)

    lines = [
        "# Strengthening results (referee Q1–Q3 + economic significance)",
        "",
        "## (1) Classification validation",
        "",
        f"- Median liquidation notional: deleverage = {v['med_liq_dele']:.3g}, "
        f"churn = {v['med_liq_churn']:.3g}. Difference in log-notional (deleverage−churn) "
        f"= {_f(v['log_liq_diff'])}, permutation p = {_f(v['log_liq_p'])} "
        f"(n_d={v['nd']}, n_c={v['nc']}). Positive ⇒ deleverage-classified events carry "
        "more liquidation pressure, so the OI split is not arbitrary.",
        f"- Spearman(OI destroyed, liquidation notional) across all events = "
        f"{_f(v['spearman'],3)}, permutation p = {_f(v['spearman_p'])} (n={v['n']}). "
        "Positive ⇒ deeper OI destruction coincides with heavier liquidation flow.",
        "",
        "### (1b) External validation (independent of liquidation magnitude)",
        "",
        (f"- **Auto-deleveraging (ADL) incidence**: deleverage events show ADL within "
         f"[t, t+2h] at rate {_f(adl['rate_dele'],3)} ({adl['n_dele']}/{adl['nd']}) vs "
         f"{_f(adl['rate_churn'],3)} ({adl['n_churn']}/{adl['nc']}) for churn; "
         f"difference {_f(adl['diff'],3)}, permutation p = {_f(adl['p'])}. ADL is a "
         "separate forced-liquidation mechanism not used to build the classification."
         if adl else
         "- ADL incidence: hyperliquid_*_adl not found — run pull_hl_reservoir.py to pull "
         "the ADL partition, then re-run."),
        (f"- **Funding swing** (mean funding [t, t+2h] minus [t-1h, t]): median "
         f"{_f(fund['med_dele'],6)} (deleverage) vs {_f(fund['med_churn'],6)} (churn), "
         f"difference {_f(fund['diff'],6)}, permutation p = {_f(fund['p'])}. A more "
         "negative deleverage swing matches the forced-long-liquidation prediction."
         if fund else
         "- Funding swing: hyperliquid_*_funding not found — re-run pull_hl_asset_ctxs.py "
         "to extract funding, then re-run."),
        (f"- **Post-event realized volatility** [t+2h, t+12h]: median "
         f"{_f(pv['med_dele'],5)} (deleverage) vs {_f(pv['med_churn'],5)} (churn), "
         f"difference {_f(pv['diff'],5)}, permutation p = {_f(pv['p'])}. A price-based "
         "check external to the OI/liquidation-magnitude split."),
        "",
        "## (2) Continuous measure (no buckets): outcomes on −ΔOI (OI destroyed)",
        "",
        f"- **H2a** |peak| ~ OI-destroyed + log(liq notional) + asset: coef = "
        f"{_f(c['h2a'][0])}, p = {_f(c['h2a'][1])} (n={c['h2a'][2]}). Positive ⇒ more "
        "destruction, larger dislocation, at equal liquidation size.",
        f"- **H2b** transitory ~ OI-destroyed + |peak| + log(liq notional) + asset: coef = "
        f"{_f(c['h2b'][0])}, p = {_f(c['h2b'][1])} (n={c['h2b'][2]}).",
        f"- **H3** Spearman(OI destroyed, time-to-recovery) = {_f(c['rec'][0],3)}, "
        f"p = {_f(c['rec'][1])} (n={c['rec'][2]}).",
        "",
        "## (3) Event-window sensitivity (headline deleverage vs churn, 0.99 trigger)",
        "",
        grid.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## (4) Economic significance of the ≈0.55pp size-controlled effect",
        "",
        f"- Median deleverage dislocation = {e['median_deleverage_dislocation']*100:.2f}%; "
        f"the 0.55pp effect is {e['frac_of_median_dislocation']*100:.0f}% of it.",
        f"- BTC daily vol = {e['BTC']['daily_vol']*100:.2f}%, ETH daily vol = "
        f"{e['ETH']['daily_vol']*100:.2f}%; the effect is ≈{e['in_daily_sigma']:.2f} "
        "of a daily standard deviation.",
    ]
    out = os.path.join(PAPER, "strengthening_results.md")
    open(out, "w").write("\n".join(lines))

    print("(1) VALIDATION: median liq notional dele=%.3g churn=%.3g | log-diff %s p=%s | "
          "spearman(OIdestroyed,liq)=%s p=%s"
          % (v['med_liq_dele'], v['med_liq_churn'], _f(v['log_liq_diff']), _f(v['log_liq_p']),
             _f(v['spearman'], 3), _f(v['spearman_p'])))
    if adl:
        print("(1b) EXTERNAL ADL: rate dele=%s (%d/%d) churn=%s (%d/%d) diff=%s p=%s"
              % (_f(adl['rate_dele'], 3), adl['n_dele'], adl['nd'], _f(adl['rate_churn'], 3),
                 adl['n_churn'], adl['nc'], _f(adl['diff'], 3), _f(adl['p'])))
    else:
        print("(1b) EXTERNAL ADL: hyperliquid_*_adl not found — run pull_hl_reservoir.py first")
    if fund:
        print("(1b) EXTERNAL funding swing: dele=%s churn=%s diff=%s p=%s"
              % (_f(fund['med_dele'], 6), _f(fund['med_churn'], 6), _f(fund['diff'], 6), _f(fund['p'])))
    else:
        print("(1b) EXTERNAL funding swing: hyperliquid_*_funding not found — re-run pull_hl_asset_ctxs.py")
    print("(1b) EXTERNAL post-event vol: dele=%s churn=%s diff=%s p=%s"
          % (_f(pv['med_dele'], 5), _f(pv['med_churn'], 5), _f(pv['diff'], 5), _f(pv['p'])))
    print("(2) CONTINUOUS: H2a coef=%s p=%s | H2b coef=%s p=%s | H3 rho=%s p=%s"
          % (_f(c['h2a'][0]), _f(c['h2a'][1]), _f(c['h2b'][0]), _f(c['h2b'][1]),
             _f(c['rec'][0], 3), _f(c['rec'][1])))
    print("(3) WINDOW SENSITIVITY:")
    print(grid.to_string(index=False))
    print("(4) ECON: 0.55pp = %.0f%% of median dislocation; %.2f daily sigma "
          "(BTC vol %.2f%%, ETH vol %.2f%%)"
          % (e['frac_of_median_dislocation']*100, e['in_daily_sigma'],
             e['BTC']['daily_vol']*100, e['ETH']['daily_vol']*100))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
