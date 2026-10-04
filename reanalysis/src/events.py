"""Corrected event construction and outcome measurement (see protocol/CORRECTION_PROTOCOL.md).

Time conventions (protocol section 2):
  * liquidation bins are left-closed and labelled by their RIGHT edge E; a bin's
    contents are available at E.  R(E) = sell notional with fill time in [E-15m, E).
  * price bar labelled L covers context-price snapshots in [L, L+5m); its close is
    treated as available at L+5m (the bar end).
  * OI is read as of time g: most recent snapshot at or before g, if no older than
    `oi_max_age_min`; otherwise missing.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

import numpy as np
import pandas as pd

MIN = pd.Timedelta(minutes=1)
LONG_CLOSE_DIRECTIONS = ("Close Long", "Liquidated Cross Long", "Liquidated Isolated Long")


@dataclass(frozen=True)
class Params:
    # trigger
    trig_q: float = 0.99
    bin_min: int = 5
    roll_bins: int = 3                # 15-min rolling notional
    trail_days: int = 30              # threshold baseline length
    warmup_days: float = 30.0         # calendar days of baseline required (primary: full 30)
    include_current: bool = False     # legacy True (bug A2)
    bin_label: str = "right"          # legacy "left" (bug A1)
    quiet_min: int = 120              # onset needs > quiet_min since previous trigger
    # windows
    win_pre_min: int = 15             # event window W starts E0 - 15m
    win_post_min: int = 120           # W ends E0 + 120m (classification time A)
    ref_mode: str = "primary"         # "primary" | "legacy_aligned"
    ref_min_bars: int = 4
    w_max_missing_bars: int = 2
    oi_base_len_min: int = 60
    oi_max_age_min: int = 2
    oi_base_max_missing: int = 2
    oi_trough_max_missing: int = 3
    # outcomes
    kappa: float = 0.0010
    horizon_h: int = 24
    horizon_max_age_min: int = 10
    max_gap_min: int = 15             # largest allowed gap between consecutive bar ends
    # classification
    classify: str = "expanding"       # "expanding" | "fixed"
    delev_pct: float = 0.10
    delev_fixed: float = -0.025
    churn_cut: float = -0.005
    min_prior: int = 20
    # intensity used as regression control
    intensity: str = "onset"          # "onset" | "window_total" | "none"
    # liquidation input treatment
    missing_zero_run_h: Optional[float] = None   # S8: zero runs >= this many hours -> missing

    def with_(self, **kw) -> "Params":
        return replace(self, **kw)


# --------------------------------------------------------------------------- liquidations
def check_side_mapping(liq: pd.DataFrame) -> dict:
    """Every sell must close a long, every buy must close a short. Raise otherwise."""
    sell = liq[liq["side"] == "sell"]
    buy = liq[liq["side"] == "buy"]
    other = liq[~liq["side"].isin(["sell", "buy"])]
    bad_sell = ~sell["direction"].isin(LONG_CLOSE_DIRECTIONS)
    bad_buy = ~buy["direction"].str.contains("Short", na=False)
    if len(other) or bad_sell.any() or bad_buy.any():
        raise ValueError(f"side/direction mapping inconsistent: other={len(other)} "
                         f"bad_sell={int(bad_sell.sum())} bad_buy={int(bad_buy.sum())}")
    return {"sell_rows": len(sell), "buy_rows": len(buy)}


def coverage_bounds(liq: pd.DataFrame):
    """Coverage assumed from 00:00 UTC of the first fill's date to 00:00 after the last."""
    start = liq["ts"].min().floor("D")
    end = liq["ts"].max().floor("D") + pd.Timedelta(days=1)
    return start, end


def sell_bins(liq: pd.DataFrame, p: Params, start=None, end=None) -> pd.Series:
    """5-min sell-side liquidation notional on a complete grid.

    right labels: index = bin end E, contents fills with ts in [E-5m, E).
    left labels (legacy): index = bin start, contents [t, t+5m)."""
    check_side_mapping(liq)
    s = liq[liq["side"] == "sell"].copy()
    s["ts"] = s["ts"].dt.as_unit("ns")
    if start is None:
        start, end = coverage_bounds(liq)
    width = pd.Timedelta(minutes=p.bin_min)
    start_bin = s["ts"].dt.floor(f"{p.bin_min}min")
    if p.bin_label == "right":
        key = start_bin + width
        grid = pd.date_range(start + width, end, freq=width)
    else:
        key = start_bin
        grid = pd.date_range(start, end - width, freq=width)
    b = s.groupby(key)["notional"].sum()
    out = b.reindex(grid, fill_value=0.0).astype(float)
    out.index.name = "bin_end" if p.bin_label == "right" else "bin_start"
    return out


def zero_runs(liq: pd.DataFrame, p: Params, min_hours: float) -> list:
    """Runs of >= min_hours with NO liquidation rows of either side (right-labelled bins)."""
    allp = p.with_(bin_label="right")
    start, end = coverage_bounds(liq)
    width = pd.Timedelta(minutes=p.bin_min)
    key = liq["ts"].dt.floor(f"{p.bin_min}min") + width
    cnt = liq.groupby(key).size().reindex(pd.date_range(start + width, end, freq=width), fill_value=0)
    z = cnt.eq(0)
    grp = (z != z.shift()).cumsum()
    runs = []
    for _, g in z.groupby(grp):
        if g.iloc[0] and len(g) * p.bin_min / 60 >= min_hours:
            # interval of time with no rows: [first_end - 5m, last_end)
            runs.append((g.index[0] - width, g.index[-1]))
    return runs


def rolling_notional(bins: pd.Series, p: Params) -> pd.Series:
    return bins.rolling(p.roll_bins, min_periods=p.roll_bins).sum()


def thresholds(R: pd.Series, p: Params) -> pd.Series:
    """Rolling quantile of R over the trailing window.
    include_current=False: window [E - trail, E)  (prior decision times only)
    include_current=True : window (E - trail, E]  (legacy)"""
    closed = "right" if p.include_current else "left"
    return R.rolling(f"{p.trail_days}D", closed=closed, min_periods=1).quantile(p.trig_q)


def trigger_table(liq: pd.DataFrame, p: Params, bins: pd.Series | None = None) -> pd.DataFrame:
    """Per-bin table: notional, R, threshold, eligibility, trigger flag."""
    if bins is None:
        bins = sell_bins(liq, p)
    if p.missing_zero_run_h:
        for a, b in zero_runs(liq, p, p.missing_zero_run_h):
            m = (bins.index > a) & (bins.index <= b)   # bins whose content lies in the run
            bins = bins.copy()
            bins[m] = np.nan
    R = rolling_notional(bins, p)
    thr = thresholds(R, p)
    width = pd.Timedelta(minutes=p.bin_min)
    first_R = bins.index[0] + (p.roll_bins - 1) * width
    eligible_from = first_R + pd.Timedelta(days=p.warmup_days)
    elig = bins.index >= eligible_from
    trig = elig & R.notna().to_numpy() & (R > 0).to_numpy() & (R >= thr).to_numpy()
    return pd.DataFrame({"notional": bins, "R": R, "thr": thr, "eligible": elig, "trigger": trig})


def onsets_from_triggers(tt: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Chaining rule (legacy-identical): a trigger is an onset if > quiet_min after the
    previous trigger. Windows and intensity are then fixed relative to the onset."""
    trig = tt.index[tt["trigger"].to_numpy()]
    if len(trig) == 0:
        return pd.DataFrame(columns=["E0", "chain_end", "n_triggers_chain", "n_triggers_in_window"])
    gaps = np.diff(trig.as_unit("ns").asi8) / 6e10
    new = np.concatenate([[True], gaps > p.quiet_min])
    ids = np.cumsum(new) - 1
    rows = []
    for k in range(ids.max() + 1):
        t = trig[ids == k]
        E0 = t[0]
        in_w = ((t >= E0) & (t <= E0 + pd.Timedelta(minutes=p.win_post_min))).sum()
        rows.append({"E0": E0, "chain_end": t[-1], "n_triggers_chain": len(t),
                     "n_triggers_in_window": int(in_w)})
    ev = pd.DataFrame(rows)
    ev["chain_span_min"] = (ev["chain_end"] - ev["E0"]).dt.total_seconds() / 60
    ev["cascade_continues"] = ev["chain_span_min"] > p.win_post_min
    return ev


def detect(liq: pd.DataFrame, p: Params, bins: pd.Series | None = None):
    tt = trigger_table(liq, p, bins)
    ev = onsets_from_triggers(tt, p)
    if len(ev):
        ev["R_onset"] = tt.loc[ev["E0"], "R"].to_numpy()
        ev["thr_onset"] = tt.loc[ev["E0"], "thr"].to_numpy()
        w0 = pd.Timedelta(minutes=p.win_pre_min)
        w1 = pd.Timedelta(minutes=p.win_post_min)
        width = pd.Timedelta(minutes=p.bin_min)
        nb = tt["notional"]
        # bins whose contents lie in W=[E0-15m, E0+post): ends in (E0-15m, E0+post]
        ev["notional_W"] = [nb[(nb.index > e - w0) & (nb.index <= e + w1)].sum() for e in ev["E0"]]
        ev["R_max_chain"] = [tt["R"].loc[e:c].max() for e, c in zip(ev["E0"], ev["chain_end"])]
    return ev, tt


# --------------------------------------------------------------------------- as-of helpers
def asof_values(ts: np.ndarray, vals: np.ndarray, at: np.ndarray, max_age: pd.Timedelta):
    """Most recent value with ts <= at, if at - ts <= max_age; else NaN."""
    ts = pd.DatetimeIndex(ts).as_unit("ns").asi8
    at_i = pd.DatetimeIndex(at).as_unit("ns").asi8
    idx = np.searchsorted(ts, at_i, side="right") - 1
    out = np.full(len(at_i), np.nan)
    ok = idx >= 0
    age = np.where(ok, at_i - ts[np.clip(idx, 0, None)], np.iinfo(np.int64).max)
    ok &= age <= max_age.value
    out[ok] = np.asarray(vals, float)[idx[ok]]
    return out


def _grid(a, b, step_min=5):
    return pd.date_range(a, b, freq=f"{step_min}min")


# --------------------------------------------------------------------------- outcomes
def _followup(bars: pd.DataFrame, start_end_time, stop_time, p: Params):
    """Bars usable for follow-up after time `start_end_time` (a bar-end time), up to
    bars ending at or before `stop_time`, stopping at the first gap between
    consecutive bar ends longer than max_gap_min.  Returns (bars, followup_end)."""
    width = pd.Timedelta(minutes=p.bin_min)
    seg = bars.loc[(bars.index + width > start_end_time) & (bars.index + width <= stop_time)]
    ends = seg.index + width
    prev = start_end_time
    keep = 0
    for e in ends:
        if (e - prev) > pd.Timedelta(minutes=p.max_gap_min):
            break
        prev = e
        keep += 1
    seg = seg.iloc[:keep]
    fu_end = prev
    return seg, fu_end


def measure(ev: pd.DataFrame, bars: pd.DataFrame, oi: pd.Series, p: Params) -> pd.DataFrame:
    """Compute reference, window, OI response and post-window outcomes per onset."""
    width = pd.Timedelta(minutes=p.bin_min)
    w0 = pd.Timedelta(minutes=p.win_pre_min)
    w1 = pd.Timedelta(minutes=p.win_post_min)
    H = pd.Timedelta(hours=p.horizon_h)
    data_end = bars.index.max() + width
    oi_ts, oi_v = oi.index, oi.to_numpy()
    close_ts = bars.index + width   # bar end times
    close_v = bars["close"].to_numpy()
    rows = []
    for r in ev.itertuples(index=False):
        E0 = r.E0
        out = {"E0": E0, "reason": ""}
        # ---- reference price
        if p.ref_mode == "primary":
            ref_labels = _grid(E0 - pd.Timedelta(minutes=45), E0 - pd.Timedelta(minutes=20))
        else:  # legacy-aligned: bars ending E0-30 ... E0-5
            ref_labels = _grid(E0 - pd.Timedelta(minutes=35), E0 - pd.Timedelta(minutes=10))
        ref = bars["close"].reindex(ref_labels)
        out["ref_bars"] = int(ref.notna().sum())
        p_ref = ref.mean() if out["ref_bars"] >= p.ref_min_bars else np.nan
        out["p_ref"] = p_ref
        # ---- event window W
        w_labels = _grid(E0 - w0, E0 + w1 - width)
        W = bars.reindex(w_labels)
        out["W_bars"] = int(W["low"].notna().sum())
        w_ok = out["W_bars"] >= len(w_labels) - p.w_max_missing_bars and (E0 + w1) <= data_end
        if w_ok and np.isfinite(p_ref):
            tl = W["low"].idxmin()
            out["trough_label"] = tl
            out["disp"] = float(np.log(W["low"].min() / p_ref))
        else:
            out["trough_label"] = pd.NaT
            out["disp"] = np.nan
        # ---- OI response
        base_g = _grid(E0 - w0 - pd.Timedelta(minutes=p.oi_base_len_min), E0 - w0)
        tr_g = _grid(E0 - w0 + width, E0 + w1)
        base = asof_values(oi_ts, oi_v, base_g, pd.Timedelta(minutes=p.oi_max_age_min))
        trough = asof_values(oi_ts, oi_v, tr_g, pd.Timedelta(minutes=p.oi_max_age_min))
        out["oi_base_n"] = int(np.isfinite(base).sum())
        out["oi_trough_n"] = int(np.isfinite(trough).sum())
        base_ok = out["oi_base_n"] >= len(base_g) - p.oi_base_max_missing
        tr_ok = out["oi_trough_n"] >= len(tr_g) - p.oi_trough_max_missing
        if base_ok and tr_ok:
            b = np.nanmean(base)
            out["doi"] = float((np.nanmin(trough) - b) / b)
        else:
            out["doi"] = np.nan
        # ---- horizon persistence (as-of bar close)
        for h in (6, 24):
            t = E0 + pd.Timedelta(hours=h)
            v = asof_values(close_ts, close_v, pd.DatetimeIndex([t]),
                            pd.Timedelta(minutes=p.horizon_max_age_min))[0]
            out[f"p{h}h"] = float(np.log(v / p_ref)) if (np.isfinite(v) and np.isfinite(p_ref) and t <= data_end) else np.nan
        # ---- recovery (primary: post-window close-based)
        thr = p_ref * (1 - p.kappa) if np.isfinite(p_ref) else np.nan
        A = E0 + w1
        stop = E0 + H
        out.update(_recovery_close(bars, A, stop, thr, p, origin=A, prefix="rec"))
        # S6a / S6b: from the bar after the trough bar, durations from E0
        if pd.notna(out["trough_label"]):
            tb_end = out["trough_label"] + width
            out.update(_recovery_close(bars, tb_end, stop, thr, p, origin=E0, prefix="rec_trough_close"))
            out.update(_recovery_high(bars, tb_end, stop, thr, p, origin=E0, prefix="rec_trough_high"))
        else:
            for pre in ("rec_trough_close", "rec_trough_high"):
                out.update({f"{pre}_min": np.nan, f"{pre}_event": np.nan, f"{pre}_complete": np.nan})
        # ---- exclusion reason for the core contrast
        reasons = []
        if not np.isfinite(p_ref):
            reasons.append("reference_bars")
        if not w_ok:
            reasons.append("window_bars_or_beyond_data")
        if not base_ok:
            reasons.append("oi_baseline")
        if not tr_ok:
            reasons.append("oi_trough")
        out["reason"] = ";".join(reasons)
        rows.append(out)
    m = pd.DataFrame(rows)
    return ev.merge(m, on="E0", how="left")


def _recovery_close(bars, start_end_time, stop, thr, p, origin, prefix):
    seg, fu_end = _followup(bars, start_end_time, stop, p)
    width = pd.Timedelta(minutes=p.bin_min)
    if not np.isfinite(thr):
        return {f"{prefix}_min": np.nan, f"{prefix}_event": np.nan, f"{prefix}_complete": np.nan}
    hit = seg.index[(seg["close"] >= thr).to_numpy()]
    if len(hit):
        t = hit[0] + width
        return {f"{prefix}_min": max(0.0, (t - origin).total_seconds() / 60), f"{prefix}_event": True,
                f"{prefix}_complete": True}
    return {f"{prefix}_min": max(0.0, (fu_end - origin).total_seconds() / 60), f"{prefix}_event": False,
            f"{prefix}_complete": bool(fu_end >= stop)}


def _recovery_high(bars, start_end_time, stop, thr, p, origin, prefix):
    seg, fu_end = _followup(bars, start_end_time, stop, p)
    width = pd.Timedelta(minutes=p.bin_min)
    if not np.isfinite(thr):
        return {f"{prefix}_min": np.nan, f"{prefix}_event": np.nan, f"{prefix}_complete": np.nan}
    hit = seg.index[(seg["high"] >= thr).to_numpy()]
    if len(hit):
        t = hit[0] + width
        return {f"{prefix}_min": max(0.0, (t - origin).total_seconds() / 60), f"{prefix}_event": True,
                f"{prefix}_complete": True}
    return {f"{prefix}_min": max(0.0, (fu_end - origin).total_seconds() / 60), f"{prefix}_event": False,
            f"{prefix}_complete": bool(fu_end >= stop)}


# --------------------------------------------------------------------------- classification
def classify(ev: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Per-asset chronological classification (legacy rule; fixed-cut variant)."""
    ev = ev.sort_values("E0").copy()
    klass, cut_used = [], []
    prior: list = []
    for d in ev["doi"].to_numpy():
        if not np.isfinite(d):
            klass.append("unknown")
            cut_used.append(np.nan)
            continue
        if p.classify == "fixed":
            cut = p.delev_fixed
        else:
            cut = np.quantile(prior, p.delev_pct) if len(prior) >= p.min_prior else p.delev_fixed
        cut_used.append(cut)
        if d <= cut:
            klass.append("contraction")
        elif d > p.churn_cut:
            klass.append("limited")
        else:
            klass.append("intermediate")
        prior.append(d)
    ev["klass"] = klass
    ev["contraction_cut"] = cut_used
    return ev


def reversion_index(disp, p6):
    disp = np.asarray(disp, float)
    p6 = np.asarray(p6, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        v = 1 - p6 / disp
    v = np.where((disp != 0) & np.isfinite(v), np.clip(v, 0, 1), np.nan)
    return v


def build_asset(coin: str, liq: pd.DataFrame, bars: pd.DataFrame, oi: pd.Series, p: Params):
    ev, tt = detect(liq, p)
    if not len(ev):
        return pd.DataFrame(), tt
    ev = measure(ev, bars, oi, p)
    ev = classify(ev, p)
    ev["symbol"] = coin
    ev["reversion"] = reversion_index(ev["disp"], ev["p6h"])
    if p.intensity == "onset":
        ev["intensity"] = ev["R_onset"]
    elif p.intensity == "window_total":
        ev["intensity"] = ev["notional_W"]
    else:
        ev["intensity"] = np.nan
    ev["analysable"] = ev["reason"].eq("") & ev["klass"].ne("unknown")
    return ev, tt


def build_all(p: Params, loaders) -> tuple[pd.DataFrame, dict]:
    """loaders: callable(coin) -> (liq, bars, oi)."""
    parts, tts = [], {}
    for coin in ("BTC", "ETH"):
        liq, bars, oi = loaders(coin)
        ev, tt = build_asset(coin, liq, bars, oi, p)
        parts.append(ev)
        tts[coin] = tt
    ev = pd.concat([x for x in parts if len(x)], ignore_index=True)
    return ev.sort_values(["E0", "symbol"]).reset_index(drop=True), tts
