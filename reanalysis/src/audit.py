"""Provenance and missing-data audit of the supplied local inputs."""
from __future__ import annotations

import numpy as np
import pandas as pd

from common import load
from events import LONG_CLOSE_DIRECTIONS, Params, coverage_bounds, zero_runs

IDENTIFIER_CANDIDATES = ["tid", "hash", "oid", "user", "trade_id", "fill_id", "order_id", "crossed",
                         "liquidation_method", "liquidated_user", "block", "block_number"]


def dropped_row_positions(liq: pd.DataFrame) -> pd.DataFrame:
    """The stored index is the pre-deduplication position (concat(ignore_index) ->
    drop_duplicates() -> sort by ts). Raw order was already time-sorted, so a gap after
    retained row i means the missing rows were exact copies of retained rows with the
    same timestamp as row i. Returns one record per retained row followed by a gap."""
    L = liq.sort_index()
    idx = L.index.to_numpy()
    gap = np.diff(idx) - 1
    has = gap > 0
    rec = L.iloc[:-1][has].copy()
    rec["n_dropped_after"] = gap[has]
    return rec


def reinstate_dropped(liq: pd.DataFrame) -> pd.DataFrame:
    """S9: reinstate each dropped row as a copy of the retained row immediately before
    its index gap (adjacent-row assumption; timestamp is exact, other fields assumed)."""
    rec = dropped_row_positions(liq)
    extra = rec.loc[rec.index.repeat(rec["n_dropped_after"].to_numpy())].drop(columns="n_dropped_after")
    return pd.concat([liq, extra]).sort_values("ts", kind="stable")


def side_ambiguity(liq: pd.DataFrame, rec: pd.DataFrame) -> float:
    """Share of dropped rows whose timestamp has retained rows of both sides (so the
    dropped row's side cannot be inferred from the timestamp alone)."""
    sides = liq.groupby("ts")["side"].nunique()
    amb = rec["ts"].map(sides) > 1
    return float((rec["n_dropped_after"] * amb).sum() / rec["n_dropped_after"].sum()) if len(rec) else 0.0


def coverage_audit(coin: str) -> dict:
    liq = load(coin, "liquidations")
    out = {"asset": coin}
    out["liquidation_columns"] = list(liq.columns)
    out["identifier_columns_retained"] = [c for c in liq.columns if c.lower() in IDENTIFIER_CANDIDATES]
    ct = pd.crosstab(liq["side"], liq["direction"])
    out["side_by_direction"] = {s: {d: int(v) for d, v in row.items() if v} for s, row in ct.iterrows()}
    out["is_liquidation_values"] = {str(k): int(v) for k, v in liq["is_liquidation"].value_counts().items()}
    sell = liq[liq.side == "sell"]
    out["sell_rows"] = int(len(sell))
    out["sell_rows_all_close_long"] = bool(sell["direction"].isin(LONG_CLOSE_DIRECTIONS).all())
    m = sell.merge(liq[liq.side == "buy"], on=["ts", "px", "sz"])
    out["sell_rows_with_matching_buy_row_same_ts_px_sz"] = int(len(m))
    out["rows"] = int(len(liq))
    out["unique_timestamps"] = int(liq["ts"].nunique())
    out["rows_sharing_a_timestamp"] = int(liq["ts"].duplicated(keep=False).sum())
    out["exact_duplicate_rows_remaining"] = int(liq.duplicated().sum())
    idx = liq.index.to_numpy()
    out["index_min"], out["index_max"] = int(idx.min()), int(idx.max())
    out["index_is_time_ordered"] = bool(liq.sort_index()["ts"].is_monotonic_increasing)
    rec = dropped_row_positions(liq)
    n_drop = int(rec["n_dropped_after"].sum())
    out["implied_pre_dedup_rows_at_least"] = int(idx.max() + 1)
    out["rows_dropped_by_legacy_dedup_at_least"] = n_drop
    out["dropped_share_at_least"] = n_drop / (idx.max() + 1)
    out["dropped_rows_on_sell_timestamps_share"] = float(
        (rec["n_dropped_after"] * rec["side"].eq("sell")).sum() / max(n_drop, 1))
    out["dropped_rows_side_ambiguous_share"] = side_ambiguity(liq, rec)
    adj_notional = float((rec["n_dropped_after"] * rec["notional"] * rec["side"].eq("sell")).sum())
    out["sell_notional_retained"] = float(sell["notional"].sum())
    out["sell_notional_reinstated_adjacent_assumption"] = adj_notional
    by_month = rec.assign(m=rec["ts"].dt.strftime("%Y-%m")).groupby("m")["n_dropped_after"].sum()
    out["dropped_by_month"] = {k: int(v) for k, v in by_month.items()}
    start, end = coverage_bounds(liq)
    out["assumed_coverage"] = [start.isoformat(), end.isoformat()]
    out["dates_with_rows"] = int(liq["ts"].dt.floor("D").nunique())
    out["calendar_dates_in_coverage"] = int((end - start).days)
    width = pd.Timedelta(minutes=5)
    cnt = liq.groupby(liq["ts"].dt.floor("5min") + width).size().reindex(
        pd.date_range(start + width, end, freq=width), fill_value=0)
    out["share_5min_bins_without_any_liquidation"] = float(cnt.eq(0).mean())
    p = Params()
    r6, r12 = zero_runs(liq, p, 6), zero_runs(liq, p, 12)
    out["zero_runs_ge_6h"] = len(r6)
    out["zero_runs_ge_12h"] = len(r12)
    out["longest_zero_run_h"] = max(((b - a).total_seconds() / 3600 for a, b in zero_runs(liq, p, 1)), default=0)
    # price / OI grids
    for kind, step in (("oi", 1), ("klines", 5), ("funding", 1)):
        d = load(coin, kind)
        grid = pd.date_range(d.ts.min().floor("min"), d.ts.max(), freq=f"{step}min")
        on_grid = d.ts[d.ts.dt.second.eq(0) & d.ts.dt.microsecond.eq(0)]
        out[f"{kind}_rows"] = int(len(d))
        out[f"{kind}_first"], out[f"{kind}_last"] = d.ts.min().isoformat(), d.ts.max().isoformat()
        out[f"{kind}_grid_points"] = int(len(grid))
        out[f"{kind}_grid_points_missing"] = int(len(grid.difference(on_grid)))
        out[f"{kind}_offgrid_rows"] = int(len(d) - len(on_grid))
        gaps = d.ts.sort_values().diff().dt.total_seconds() / 60
        out[f"{kind}_max_gap_min"] = float(gaps.max())
        out[f"{kind}_columns"] = list(d.columns)
    k = load(coin, "klines")
    out["klines_volume_all_missing"] = bool(k["volume"].isna().all())
    adl = load(coin, "adl")
    out["adl_rows"] = int(len(adl))
    out["adl_dates"] = sorted(adl["ts"].dt.strftime("%Y-%m-%d").unique().tolist())
    return out


def gap_price_moves(coin: str, runs) -> pd.DataFrame:
    """Absolute log price range during zero-liquidation runs (context for S8)."""
    k = load(coin, "klines").set_index("ts").sort_index()
    rows = []
    for a, b in runs:
        seg = k.loc[a:b]
        if len(seg):
            rows.append({"asset": coin, "start": a, "end": b, "hours": (b - a).total_seconds() / 3600,
                         "log_range_pct": 100 * np.log(seg.high.max() / seg.low.min())})
    return pd.DataFrame(rows)
