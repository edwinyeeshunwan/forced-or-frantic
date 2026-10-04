"""Build the prototype event table from pulled OI + price data.

Implements 00_Design_Spec.md §3a (OI-based prototype events) and §4 (outcomes):
  event trigger: 1h ΔOI ≤ trailing 30d 1st pctile  AND  1h return ≤ trailing 30d 5th pctile
  merge window:  120 minutes
  outcomes:      peak dislocation, time-to-recovery (first passage, κ=10bp,
                 censored 24h), permanent component at +6h/+24h, transitory share.

Run:  python build_event_table.py [--venue binance --symbol BTCUSDT]
Default: all venue/symbol pairs with both klines+oi parquets present.
Output: data/events_{venue}_{symbol}.parquet and a combined data/event_table.parquet
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from config import DATA_DIR, list_dataset_stems, load_df, save_df

# --- spec parameters (00_Design_Spec.md — change only via spec amendment) ---
OI_WINDOW = "1h"
RET_WINDOW = "1h"
TRAIL = "30D"
OI_PCTILE = 0.01
RET_PCTILE = 0.05
MERGE_MIN = 120
KAPPA = 0.0010          # 10bp recovery threshold
CENSOR_H = 24
POST_TROUGH_H = 2       # ΔOI trough search window after event
PRE_REF = ("30min", "5min")  # P0 = vwap-ish mean close over [t-30m, t-5m]


def load_panel(venue: str, symbol: str) -> pd.DataFrame:
    k = load_df(f"{venue}_{symbol}_klines")
    o = load_df(f"{venue}_{symbol}_oi")
    k = k.set_index("ts").sort_index()
    o = o.set_index("ts").sort_index()[["oi"]]
    df = k.join(o, how="left")
    df["oi"] = df["oi"].ffill(limit=6)  # tolerate ≤30min OI gaps
    return df


def detect_events(df: pd.DataFrame) -> pd.DataFrame:
    bars_1h = 12
    df = df.copy()
    df["doi_1h"] = df["oi"].pct_change(bars_1h)
    df["ret_1h"] = np.log(df["close"]).diff(bars_1h)

    roll = df["doi_1h"].rolling(TRAIL, min_periods=288 * 7)
    df["oi_thresh"] = roll.quantile(OI_PCTILE)
    df["ret_thresh"] = df["ret_1h"].rolling(TRAIL, min_periods=288 * 7).quantile(RET_PCTILE)

    trig = df[(df["doi_1h"] <= df["oi_thresh"]) & (df["ret_1h"] <= df["ret_thresh"])]
    if trig.empty:
        return pd.DataFrame()

    # merge triggers within MERGE_MIN
    events, current = [], None
    for ts in trig.index:
        if current is None or (ts - current["end"]).total_seconds() / 60 > MERGE_MIN:
            if current is not None:
                events.append(current)
            current = {"t0": ts, "end": ts}
        else:
            current["end"] = ts
    events.append(current)
    ev = pd.DataFrame(events)

    # event magnitude = worst values in merged span
    ev["doi_trigger"] = [df.loc[r.t0:r.end, "doi_1h"].min() for r in ev.itertuples()]
    ev["ret_trigger"] = [df.loc[r.t0:r.end, "ret_1h"].min() for r in ev.itertuples()]
    return ev


def outcomes(df: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in ev.itertuples():
        t0 = r.t0
        pre = df.loc[t0 - pd.Timedelta(PRE_REF[0]): t0 - pd.Timedelta(PRE_REF[1]), "close"]
        if pre.empty:
            continue
        p0 = pre.mean()

        post2h = df.loc[t0: t0 + pd.Timedelta(hours=2), "low"]
        peak_disloc = np.log(post2h.min() / p0) if len(post2h) else np.nan

        # ΔOI over [t-1h baseline → trough within t+2h]
        oi_base = df.loc[t0 - pd.Timedelta(hours=1): t0, "oi"].mean()
        oi_trough = df.loc[t0: t0 + pd.Timedelta(hours=POST_TROUGH_H), "oi"].min()
        doi_event = (oi_trough - oi_base) / oi_base if oi_base else np.nan

        # first passage back to P0*(1-kappa)
        horizon = df.loc[t0: t0 + pd.Timedelta(hours=CENSOR_H)]
        trough_ts = post2h.idxmin() if len(post2h) else t0
        rec = horizon.loc[trough_ts:]
        crossed = rec[rec["high"] >= p0 * (1 - KAPPA)]
        if len(crossed):
            ttr_min = (crossed.index[0] - t0).total_seconds() / 60
            censored = False
        else:
            ttr_min, censored = CENSOR_H * 60, True

        def perm(h):
            w = df.loc[t0 + pd.Timedelta(hours=h):, "close"]
            return np.log(w.iloc[0] / p0) if len(w) else np.nan

        perm6, perm24 = perm(6), perm(24)
        transitory = 1 - (perm6 / peak_disloc) if peak_disloc and not np.isnan(perm6) else np.nan

        rows.append(dict(t0=t0, p0=p0, doi_trigger=r.doi_trigger, ret_trigger=r.ret_trigger,
                         doi_event=doi_event, peak_disloc=peak_disloc, ttr_min=ttr_min,
                         censored=censored, perm_6h=perm6, perm_24h=perm24,
                         transitory_share=np.clip(transitory, 0, 1) if not np.isnan(transitory) else np.nan,
                         session=("asia" if t0.hour < 7 else "eu" if t0.hour < 13 else "us")))
    return pd.DataFrame(rows)


def run(venue: str, symbol: str) -> pd.DataFrame | None:
    try:
        df = load_panel(venue, symbol)
    except FileNotFoundError:
        return None
    ev = detect_events(df)
    if ev.empty:
        print(f"{venue} {symbol}: 0 events")
        return None
    out = outcomes(df, ev)
    out["venue"], out["symbol"] = venue, symbol
    save_df(out, f"events_{venue}_{symbol}")
    print(f"{venue} {symbol}: {len(out)} events "
          f"(median peak dislocation {out['peak_disloc'].median():.4f}, "
          f"median TTR {out['ttr_min'].median():.0f} min, "
          f"{out['censored'].mean():.0%} censored)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--venue"), ap.add_argument("--symbol")
    a = ap.parse_args()

    pairs = ([(a.venue, a.symbol)] if a.venue and a.symbol else
             sorted({tuple(s.split("_")[:2]) for s in list_dataset_stems()
                     if s.endswith("_oi") and not s.startswith(("events", "synth"))}))
    all_ev = [e for v, s in pairs if (e := run(v, s)) is not None]
    if all_ev:
        combined = pd.concat(all_ev, ignore_index=True)
        save_df(combined, "event_table")
        print(f"\ncombined event table: {len(combined)} events -> data/event_table")


if __name__ == "__main__":
    main()
