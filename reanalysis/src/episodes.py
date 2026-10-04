"""Market-episode clustering for dependence-aware inference (protocol section 7)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def linkage_episodes(times: pd.Series, horizon_h: float, pre_min: float = 45) -> np.ndarray:
    """Single-linkage clusters over pooled (both-asset) onset times: consecutive
    onsets (in time order) within horizon_h hours + pre_min minutes share an episode,
    i.e. their outcome intervals [E0 - pre, E0 + horizon] overlap."""
    raw = pd.DatetimeIndex(pd.to_datetime(times)).as_unit("ns").asi8
    order = np.argsort(raw, kind="stable")
    ts = raw[order]
    link = (horizon_h * 60 + pre_min) * 6e10
    new = np.concatenate([[True], np.diff(ts) > link])
    ids_sorted = np.cumsum(new) - 1
    ids = np.empty(len(ts), dtype=int)
    ids[order] = ids_sorted
    return ids


def calendar_clusters(times: pd.Series, kind: str) -> np.ndarray:
    t = pd.to_datetime(times)
    if kind == "day":
        key = t.dt.strftime("%Y-%m-%d")
    elif kind == "week":
        iso = t.dt.isocalendar()
        key = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    else:
        raise ValueError(kind)
    return pd.factorize(key)[0]


def assign(ev: pd.DataFrame) -> pd.DataFrame:
    """Attach all declared cluster definitions, built on the full eligible set."""
    ev = ev.copy()
    ev["ep6"] = linkage_episodes(ev["E0"], 6)
    ev["ep24"] = linkage_episodes(ev["E0"], 24)
    ev["day"] = calendar_clusters(ev["E0"], "day")
    ev["week"] = calendar_clusters(ev["E0"], "week")
    ev["none"] = np.arange(len(ev))
    return ev


def cluster_summary(ev: pd.DataFrame, col: str) -> dict:
    c = ev[ev["klass"].isin(["contraction", "limited"])]
    if not len(c):
        return {"G": 0}
    g = c.groupby(col)["klass"].agg(lambda s: set(s))
    size = c.groupby(col).size()
    return {"n_events": int(len(c)), "G": int(len(g)),
            "G_mixed": int(sum(len(x) == 2 for x in g)),
            "G_with_contraction": int(sum("contraction" in x for x in g)),
            "G_with_limited": int(sum("limited" in x for x in g)),
            "max_size": int(size.max()), "median_size": float(size.median())}
