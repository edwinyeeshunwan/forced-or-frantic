"""Legacy reconstruction: loads ONLY function definitions and literal constants from
the original scripts (no original I/O or entry points run), rebuilds the legacy event
tables in memory and checks them against the stored table and recorded benchmarks."""
from __future__ import annotations

import ast

import numpy as np
import pandas as pd

from common import DATA, REV2, SCRIPTS, load, price_bars
from parquet_fallback import read_parquet


def legacy_namespace() -> dict:
    ns = {"np": np, "pd": pd}
    src = SCRIPTS / "build_event_table_liq.py"
    tree = ast.parse(src.read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.Assign))
             and not (isinstance(n, ast.Assign) and any(isinstance(x, ast.Call) for x in ast.walk(n)))]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(src), "exec"), ns)
    return ns


NS = legacy_namespace()


def legacy_oi_on_price_grid(coin):
    price = price_bars(coin)
    oi = load(coin, "oi").set_index("ts").sort_index()["oi"]
    return oi.reindex(price.index, method="ffill", limit=12)


def legacy_triggers(liq: pd.DataFrame, q: float) -> pd.DatetimeIndex:
    """The four trigger lines of legacy detect_events, verbatim in effect."""
    n5 = NS["_long_liq_notional"](liq)
    roll = n5.rolling(f"{NS['LIQ_ROLL_MIN']}min").sum()
    thresh = roll.rolling(NS["TRAIL"], min_periods=int(288 * 7)).quantile(q)
    return roll[(roll > 0) & (roll >= thresh)].index


def legacy_table(q: float) -> pd.DataFrame:
    parts = []
    for coin in ("BTC", "ETH"):
        liq = load(coin, "liquidations")
        price = load(coin, "klines").set_index("ts").sort_index()
        oi = legacy_oi_on_price_grid(coin)
        ev = NS["detect_events"](liq, q)
        d = NS["outcomes"](price, oi, ev)
        d["venue"], d["symbol"] = "hyperliquid", coin
        ends = ev.set_index("t0")["end"]
        d["chain_end"] = d["t0"].map(ends)
        parts.append(d)
    return pd.concat(parts, ignore_index=True)


BENCH = {
    0.99: {"total": 162, "deleverage": 38, "churn": 28, "middle": 96, "coef": 0.005132523540803671,
           "n_contrast": 66},
    0.95: {"total": 425, "deleverage": 63, "churn": 125, "middle": 237, "coef": 0.005453804556876954,
           "n_contrast": 188},
}


def peak_coef(d):
    s = d[d.klass.isin(["deleverage", "churn"])]
    X = np.column_stack([np.ones(len(s)), (s.klass == "deleverage").astype(int),
                         np.log(s.liq_notional), (s.symbol == "ETH").astype(int)])
    return float(np.linalg.lstsq(X, s.peak_disloc.abs(), rcond=None)[0][1]), len(s)


def check(tables: dict) -> dict:
    saved = read_parquet(DATA / "event_table_liq.parquet")
    a = saved.sort_values(["symbol", "t0"]).reset_index(drop=True)
    b = tables[0.99].sort_values(["symbol", "t0"]).reset_index(drop=True)[saved.columns]
    cols = {}
    for c in saved.columns:
        if pd.api.types.is_numeric_dtype(a[c]) and a[c].dtype != bool:
            cols[c] = bool(np.allclose(a[c].astype(float), b[c].astype(float), equal_nan=True, rtol=1e-12, atol=0))
        else:
            cols[c] = bool((a[c].astype(str).to_numpy() == b[c].astype(str).to_numpy()).all())
    ref = pd.read_csv(REV2 / "verified_group_summary.csv")
    groups = []
    for q, d in tables.items():
        for k, g in d.groupby("klass"):
            r = ref[(ref.trigger == q) & (ref["class"] == k)].iloc[0]
            groups.append({"trigger": q, "class": k, "n": len(g),
                           "n_ok": len(g) == r.n,
                           "median_peak_ok": bool(np.isclose(100 * g.peak_disloc.median(), r.median_peak_logpercent, rtol=1e-12)),
                           "median_reversion_ok": bool(np.isclose(g.transitory_share.median(), r.median_reversion_share, rtol=1e-12)),
                           "median_minutes_ok": bool(g.ttr_min.median() == r.median_recorded_minutes),
                           "censored_ok": bool(np.isclose(100 * g.censored.mean(), r.censored_percent, rtol=1e-12))})
    coefs = {}
    for q, d in tables.items():
        c, n = peak_coef(d)
        coefs[str(q)] = {"coef": c, "n": n, "benchmark": BENCH[q]["coef"],
                         "abs_diff": abs(c - BENCH[q]["coef"]), "n_ok": n == BENCH[q]["n_contrast"]}
    counts = {str(q): {"total": len(d), **d.klass.value_counts().to_dict(),
                       "matches_benchmark": len(d) == BENCH[q]["total"] and all(
                           int((d.klass == k).sum()) == BENCH[q][k] for k in ("deleverage", "churn", "middle"))}
              for q, d in tables.items()}
    ok = all(cols.values()) and all(all(v for k, v in g.items() if k.endswith("_ok")) for g in groups) \
        and all(v["abs_diff"] < 1e-12 and v["n_ok"] for v in coefs.values()) \
        and all(v["matches_benchmark"] for v in counts.values())
    return {"all_benchmarks_reproduced": ok, "stored_table_column_equality": cols,
            "group_summaries": groups, "ols_coefficients": coefs, "counts": counts}
