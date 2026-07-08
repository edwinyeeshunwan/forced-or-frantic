"""Magnitude controls + robustness grid for the H2/H3 liquidation results.

Addresses the two things a referee/supervisor will hit first:

  (A) MAGNITUDE CONFOUND — the deleverage class conditions on deeper OI
      destruction, which correlates with bigger liquidations, which are
      mechanically bigger moves. We re-test H2 controlling for event size:
        H2a |peak| ~ deleverage + log(liq_notional) + asset_eth
        H2b transitory ~ deleverage + |peak| + log(liq_notional) + asset_eth
      Permutation inference on the deleverage coefficient (shuffle the label).
      H3 recovery is re-tested with a magnitude median-split log-rank.
      Run at BOTH triggers (0.99 small / 0.95 ~3x larger) so the size-independent
      effect is judged with adequate power, not just the n=66 headline sample.

  (B) ROBUSTNESS GRID (spec §6) — recompute the three headline contrasts across
        trigger pctile {0.99, 0.95} x ΔOI rule {percentile, fixed -2.5%}
        x subset {all, ex-Oct-cascade-week, BTC-only, ETH-only}

Event tables for each trigger pctile are rebuilt IN MEMORY (no saved files are
overwritten). Outputs: paper/robustness_results.md + console.

Run:  python robustness_liq.py
"""
import os

import numpy as np
import pandas as pd

import build_event_table_liq as B
from analyze_liq_events import logrank, perm_test
from config import load_df

PAPER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COINS = ["BTC", "ETH"]
OCT_WEEK = ("2025-10-10", "2025-10-17")   # exclude the Oct-2025 cascade week
FIXED_CUT = -0.025
CHURN_CUT = -0.005
N_PERM = 10000
SEED = 0


# ---------- in-memory event builder (mirrors build_event_table_liq.run, no save) ----------
def build_events(coin: str, pctile: float) -> pd.DataFrame:
    liq = load_df(f"hyperliquid_{coin}_liquidations")
    price = load_df(f"hyperliquid_{coin}_klines").set_index("ts").sort_index()
    oi = load_df(f"hyperliquid_{coin}_oi").set_index("ts").sort_index()["oi"]
    oi = oi.reindex(price.index, method="ffill", limit=12)
    ev = B.detect_events(liq, pctile)
    if ev.empty:
        return pd.DataFrame()
    out = B.outcomes(price, oi, ev)
    out["symbol"] = coin
    return out


def all_events(pctile: float) -> pd.DataFrame:
    parts = [e for c in COINS if len(e := build_events(c, pctile))]
    return _prep(pd.concat(parts, ignore_index=True)) if parts else pd.DataFrame()


def reclassify_fixed(df: pd.DataFrame) -> np.ndarray:
    """Fixed-cut ΔOI rule (spec robustness): deleverage <= -2.5%, churn > -0.5%."""
    d = df["doi_event"]
    return np.where(d <= FIXED_CUT, "deleverage",
                    np.where(d > CHURN_CUT, "churn", "middle"))


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["abs_peak"] = df["peak_disloc"].abs()
    df["log_notional"] = np.log(df["liq_notional"].clip(lower=1e-9))
    df["asset_eth"] = (df["symbol"] == "ETH").astype(float)
    return df


# ---------- OLS with permutation inference ----------
def _ols_coef(y, X):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def ols_perm(d: pd.DataFrame, ycol: str, controls: list, n=N_PERM, seed=SEED):
    """Coef on the deleverage dummy in OLS(y ~ deleverage + controls), two-sided
    permutation p (shuffle the dummy). d must hold only deleverage+churn rows."""
    d = d.dropna(subset=[ycol] + controls).copy()
    if d["klass"].nunique() < 2 or len(d) < 10:
        return np.nan, np.nan, len(d)
    y = d[ycol].to_numpy(float)
    dummy = (d["klass"].to_numpy() == "deleverage").astype(float)
    ctrl = [d[c].to_numpy(float) for c in controls]
    X = np.column_stack([np.ones(len(d)), dummy] + ctrl)
    coef = _ols_coef(y, X)[1]
    rng = np.random.default_rng(seed)
    perm = dummy.copy()
    cnt = 0
    for _ in range(n):
        rng.shuffle(perm)
        Xp = np.column_stack([np.ones(len(d)), perm] + ctrl)
        if abs(_ols_coef(y, Xp)[1]) >= abs(coef):
            cnt += 1
    return coef, (cnt + 1) / (n + 1), len(d)


def magnitude_tests(base: pd.DataFrame) -> dict:
    """H2a/H2b magnitude-controlled regressions + H3 size-stratified log-rank."""
    dc = base[base["klass"].isin(["deleverage", "churn"])]
    res = {"a_peak": ols_perm(dc, "abs_peak", ["log_notional", "asset_eth"]),
           "a_tran": ols_perm(dc, "transitory_share",
                              ["abs_peak", "log_notional", "asset_eth"]),
           "strat": {}}
    med = dc["log_notional"].median()
    for label, sub in [("small (<= median size)", dc[dc["log_notional"] <= med]),
                       ("large (>  median size)", dc[dc["log_notional"] > med])]:
        de, ch = sub[sub.klass == "deleverage"], sub[sub.klass == "churn"]
        chi, p = logrank(de["ttr_min"].values, (~de["censored"]).values,
                         ch["ttr_min"].values, (~ch["censored"]).values)
        res["strat"][label] = (len(de), len(ch), chi, p)
    return res


# ---------- headline contrast (used across the grid) ----------
def headline(df: pd.DataFrame) -> dict:
    dele = df[df["klass"] == "deleverage"]
    churn = df[df["klass"] == "churn"]
    pk, pk_p, nd, nc = perm_test(dele["peak_disloc"].abs(), churn["peak_disloc"].abs())
    tr, tr_p, _, _ = perm_test(dele["transitory_share"], churn["transitory_share"])
    lr_chi, lr_p = logrank(dele["ttr_min"].values, (~dele["censored"]).values,
                           churn["ttr_min"].values, (~churn["censored"]).values)
    return dict(n_d=nd or len(dele), n_c=nc or len(churn),
                peak_diff=pk, peak_p=pk_p, tr_diff=tr, tr_p=tr_p,
                lr_chi=lr_chi, lr_p=lr_p)


def _f(x, d=4):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"


def main():
    events = {p: all_events(p) for p in (0.99, 0.95)}

    # ---- (A) magnitude-controlled tests at BOTH triggers ----
    mag = {p: magnitude_tests(events[p]) for p in (0.99, 0.95)}

    # ---- (B) robustness grid ----
    grid_rows = []
    for pctile in (0.99, 0.95):
        ev = events[pctile]
        for rule in ("percentile", "fixed"):
            ev_r = ev.copy()
            if rule == "fixed":
                ev_r["klass"] = reclassify_fixed(ev_r)
            for sub_name, sub in [
                ("all", ev_r),
                ("ex-Oct-week", ev_r[~ev_r["t0"].between(
                    pd.Timestamp(OCT_WEEK[0], tz="UTC"), pd.Timestamp(OCT_WEEK[1], tz="UTC"))]),
                ("BTC", ev_r[ev_r.symbol == "BTC"]),
                ("ETH", ev_r[ev_r.symbol == "ETH"])]:
                h = headline(sub)
                grid_rows.append(dict(
                    trigger=f"{pctile:.2f}", rule=rule, subset=sub_name,
                    n_d=h["n_d"], n_c=h["n_c"],
                    peak_diff=h["peak_diff"], peak_p=h["peak_p"],
                    tr_diff=h["tr_diff"], tr_p=h["tr_p"], lr_p=h["lr_p"]))
    grid = pd.DataFrame(grid_rows)

    # ---- write ----
    lines = [
        "# Robustness — magnitude controls + spec §6 grid",
        "",
        "## (A) Does the deleverage effect survive controlling for event size?",
        "",
        "OLS on the deleverage(1)/churn(0) subset; permutation p on the deleverage "
        f"coefficient ({N_PERM:,} shuffles). Run at both triggers for power.",
        "",
    ]
    for p in (0.99, 0.95):
        m = mag[p]
        lines += [
            f"### Trigger = {p:.2f}",
            "",
            f"- **H2a peak |dislocation|** ~ deleverage + log(liq_notional) + asset: "
            f"coef = {_f(m['a_peak'][0])}, perm p = {_f(m['a_peak'][1])} (n={m['a_peak'][2]}). "
            "Positive & significant ⇒ deleverage moves bigger at equal liquidation size.",
            f"- **H2b transitory share** ~ deleverage + |peak| + log(liq_notional) + "
            f"asset: coef = {_f(m['a_tran'][0])}, perm p = {_f(m['a_tran'][1])} "
            f"(n={m['a_tran'][2]}). Negative ⇒ more permanent at equal move/liq size.",
        ]
        for label, (nd, nc, chi, pp) in m["strat"].items():
            lines.append(f"- **H3 recovery, {label}**: deleverage n={nd}, churn n={nc} "
                         f"→ log-rank χ²={_f(chi,3)}, p={_f(pp)}")
        lines.append("")
    lines += [
        "## (B) Robustness grid",
        "",
        "`peak_diff`/`tr_diff` = median deleverage−churn (|peak| and transitory share); "
        "`*_p` are permutation/log-rank p-values. Stable sign across rows = robust.",
        "",
        grid.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Reading",
        "",
        "- **Direction** (sign of peak_diff > 0, tr_diff < 0) holding across the grid "
        "is the robust core; significance scales with sample size (0.95 trigger).",
        "- The (A) magnitude tests are the strict 'equal-magnitude' check (spec H2). "
        "Judge H2a/H2b mainly at the 0.95 trigger, where n is adequate.",
        "- Single venue (Hyperliquid); claims scoped accordingly.",
    ]
    out = os.path.join(PAPER, "robustness_results.md")
    with open(out, "w") as f:
        f.write("\n".join(lines))

    # ---- console ----
    for p in (0.99, 0.95):
        m = mag[p]
        print(f"(A) MAGNITUDE-CONTROLLED  [trigger {p:.2f}]")
        print(f"  H2a |peak| ~ deleverage + size:            coef={_f(m['a_peak'][0])} "
              f"p={_f(m['a_peak'][1])} n={m['a_peak'][2]}")
        print(f"  H2b transitory ~ deleverage + |peak| + size: coef={_f(m['a_tran'][0])} "
              f"p={_f(m['a_tran'][1])} n={m['a_tran'][2]}")
        for label, (nd, nc, chi, pp) in m["strat"].items():
            print(f"  H3 {label}: n_d={nd} n_c={nc} log-rank chi2={_f(chi,3)} p={_f(pp)}")
        print()
    print("(B) ROBUSTNESS GRID")
    print(grid.to_string(index=False))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
