"""Liquidation-based event table for Hyperliquid — the REAL test (spec 3b/3c/4).

Unlike build_event_table.py (OI-proxy prototype trigger, spec 3a), this uses
the complete on-chain liquidation record as the trigger, then conditions on ΔOI
to split events into deleverage vs churn. This is only possible on Hyperliquid,
the one venue with free, complete liquidation data.

Pipeline (00_Design_Spec.md):
  3b trigger : rolling 15-min LONG-liquidation notional >= trailing 30d 99th pctile
               (downside-only headline, spec decision #3). Merge within 120 min.
  3c split   : ΔOI over [t-1h baseline -> trough within t+2h]
                 deleverage : ΔOI <= trailing 10th pctile (headline)  OR  <= FIXED_CUT
                 churn      : ΔOI > -0.5%
                 middle     : excluded from headline (robustness only)
  4 outcomes : peak dislocation, time-to-recovery (first passage, κ=10bp, 24h
               censored), permanent component +6h/+24h, transitory share.

Inputs (from the free Hyperliquid pullers):
  data/hyperliquid_{COIN}_liquidations.parquet   (pull_hl_reservoir.py)
  data/hyperliquid_{COIN}_klines.parquet         (pull_hl_reservoir.py, 5m)
  data/hyperliquid_{COIN}_oi.parquet             (pull_hl_asset_ctxs.py)

The headline number this prints is N — the event count — which decides whether
the free window is a powered study or a cascade case-study.

Run:
  python build_event_table_liq.py                 # all HL coins with all 3 inputs
  python build_event_table_liq.py --coin BTC
  python build_event_table_liq.py --pctile 0.95   # robustness trigger
"""
import argparse

import numpy as np
import pandas as pd

from config import ASSETS, list_dataset_stems, load_df, save_df

# ---- spec parameters (00_Design_Spec.md — change only via spec amendment) ---
LIQ_ROLL_MIN = 15          # rolling long-liq notional window
TRIG_PCTILE = 0.99         # headline trigger (decision #1); 0.95 in robustness
TRAIL = "30D"
MERGE_MIN = 120
DELEV_PCTILE = 0.10        # trailing ΔOI percentile -> deleverage class
DELEV_FIXED_CUT = -0.025   # fixed-cut robustness value (calibrate outcome-blind)
CHURN_CUT = -0.005         # ΔOI > -0.5% => churn
KAPPA = 0.0010             # 10bp recovery threshold
CENSOR_H = 24
POST_TROUGH_H = 2
PRE_REF = ("30min", "5min")

# A LONG liquidation = a forced SELL (downside-only headline, spec decision #3).
# The data lives in the liquidations-only partition (every row is_liquidation),
# so the clean signal is `side`: a liquidated long is SOLD. We use side=='sell'.
# NOTE (verified 2026-06 via --inspect): the actual `direction` values are
# "Close Long" / "Close Short", NOT the docs' "Liquidated Cross Long" — so we do
# NOT rely on direction. It's kept only as a fallback substring match on "long".
LONG_LIQ_SIDES = ("sell", "a", "ask")


def _long_liq_notional(liq: pd.DataFrame) -> pd.Series:
    """5-min series of long-liquidation (forced-sell) notional, in 5m bins."""
    side = liq["side"].astype(str).str.lower()
    s = liq[side.isin(LONG_LIQ_SIDES)]
    if s.empty and "direction" in liq.columns:  # fallback if side encoding differs
        d = liq["direction"].astype(str).str.lower()
        s = liq[d.str.contains("long", na=False)]
    if s.empty:
        return pd.Series(dtype=float)
    return (s.set_index("ts")["notional"].resample("5min").sum())


def detect_events(liq: pd.DataFrame, pctile: float) -> pd.DataFrame:
    notional_5m = _long_liq_notional(liq)
    if notional_5m.empty:
        return pd.DataFrame()
    # rolling 15-min notional = sum of three 5m bins
    roll = notional_5m.rolling(f"{LIQ_ROLL_MIN}min").sum()
    thresh = roll.rolling(TRAIL, min_periods=int(288 * 7)).quantile(pctile)
    trig_idx = roll[(roll > 0) & (roll >= thresh)].index
    if len(trig_idx) == 0:
        return pd.DataFrame()

    events, current = [], None
    for ts in trig_idx:
        if current is None or (ts - current["end"]).total_seconds() / 60 > MERGE_MIN:
            if current is not None:
                events.append(current)
            current = {"t0": ts, "end": ts}
        else:
            current["end"] = ts
    events.append(current)
    ev = pd.DataFrame(events)
    ev["liq_notional"] = [roll.loc[r.t0:r.end].max() for r in ev.itertuples()]
    return ev


def _classify(doi_event: float, doi_trail_10: float) -> str:
    if np.isnan(doi_event):
        return "unknown"
    if doi_event <= (doi_trail_10 if not np.isnan(doi_trail_10) else DELEV_FIXED_CUT):
        return "deleverage"
    if doi_event > CHURN_CUT:
        return "churn"
    return "middle"


def outcomes(price: pd.DataFrame, oi: pd.Series, ev: pd.DataFrame) -> pd.DataFrame:
    # trailing 10th pctile of event-window ΔOI, computed expanding over prior events
    rows, prior_doi = [], []
    for r in ev.itertuples():
        t0 = r.t0
        pre = price.loc[t0 - pd.Timedelta(PRE_REF[0]): t0 - pd.Timedelta(PRE_REF[1]), "close"]
        if pre.empty:
            continue
        p0 = pre.mean()

        post2h = price.loc[t0: t0 + pd.Timedelta(hours=2), "low"]
        peak_disloc = np.log(post2h.min() / p0) if len(post2h) else np.nan

        oi_base = oi.loc[t0 - pd.Timedelta(hours=1): t0].mean()
        oi_trough = oi.loc[t0: t0 + pd.Timedelta(hours=POST_TROUGH_H)].min()
        doi_event = (oi_trough - oi_base) / oi_base if oi_base and not np.isnan(oi_base) else np.nan

        doi_trail_10 = np.quantile(prior_doi, DELEV_PCTILE) if len(prior_doi) >= 20 else np.nan
        klass = _classify(doi_event, doi_trail_10)
        if not np.isnan(doi_event):
            prior_doi.append(doi_event)

        horizon = price.loc[t0: t0 + pd.Timedelta(hours=CENSOR_H)]
        trough_ts = post2h.idxmin() if len(post2h) else t0
        rec = horizon.loc[trough_ts:]
        crossed = rec[rec["high"] >= p0 * (1 - KAPPA)]
        if len(crossed):
            ttr_min, censored = (crossed.index[0] - t0).total_seconds() / 60, False
        else:
            ttr_min, censored = CENSOR_H * 60, True

        def perm(h):
            w = price.loc[t0 + pd.Timedelta(hours=h):, "close"]
            return np.log(w.iloc[0] / p0) if len(w) else np.nan

        perm6, perm24 = perm(6), perm(24)
        transitory = (1 - perm6 / peak_disloc) if (peak_disloc and not np.isnan(perm6)
                                                   and peak_disloc != 0) else np.nan

        rows.append(dict(
            t0=t0, p0=p0, liq_notional=r.liq_notional, doi_event=doi_event, klass=klass,
            peak_disloc=peak_disloc, ttr_min=ttr_min, censored=censored,
            perm_6h=perm6, perm_24h=perm24,
            transitory_share=np.clip(transitory, 0, 1) if not np.isnan(transitory) else np.nan,
            # finer UTC session bands than the prototype's crude 3-way split (H3)
            session=_session(t0)))
    return pd.DataFrame(rows)


def _session(t0) -> str:
    h = t0.hour
    if 0 <= h < 8:
        return "asia"
    if 8 <= h < 13:
        return "eu"
    if 13 <= h < 17:
        return "eu_us_overlap"
    return "us"


def run(coin: str, pctile: float) -> pd.DataFrame | None:
    try:
        liq = load_df(f"hyperliquid_{coin}_liquidations")
        price = load_df(f"hyperliquid_{coin}_klines").set_index("ts").sort_index()
        oi = load_df(f"hyperliquid_{coin}_oi").set_index("ts").sort_index()["oi"]
    except FileNotFoundError as e:
        print(f"hyperliquid {coin}: missing input ({e}) — run the pullers first")
        return None
    if liq.empty or price.empty or oi.empty:
        print(f"hyperliquid {coin}: an input is empty — check the pulls")
        return None
    oi = oi.reindex(price.index, method="ffill", limit=12)

    ev = detect_events(liq, pctile)
    if ev.empty:
        print(f"hyperliquid {coin}: 0 events")
        return None
    out = outcomes(price, oi, ev)
    out["venue"], out["symbol"] = "hyperliquid", coin
    save_df(out, f"events_liq_hyperliquid_{coin}")
    vc = out["klass"].value_counts().to_dict()
    print(f"hyperliquid {coin}: N={len(out)} events  "
          f"[deleverage={vc.get('deleverage',0)}, churn={vc.get('churn',0)}, "
          f"middle={vc.get('middle',0)}]  "
          f"median peak {out['peak_disloc'].median():.4f}, "
          f"median TTR {out['ttr_min'].median():.0f}m, {out['censored'].mean():.0%} censored")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin")
    ap.add_argument("--pctile", type=float, default=TRIG_PCTILE)
    a = ap.parse_args()

    coins = ([a.coin] if a.coin else
             [c for c in ASSETS["hyperliquid"]
              if f"hyperliquid_{c}_liquidations" in list_dataset_stems()])
    if not coins:
        print("no hyperliquid_*_liquidations datasets — run pull_hl_reservoir.py first")
        return
    all_ev = [e for c in coins if (e := run(c, a.pctile)) is not None]
    if all_ev:
        combined = pd.concat(all_ev, ignore_index=True)
        save_df(combined, "event_table_liq")
        print(f"\ncombined liquidation event table: N={len(combined)} -> data/event_table_liq")
        print("=> This N is the number that decides: powered study vs cascade case-study.")


if __name__ == "__main__":
    main()
