"""Synthetic data builders for the tests (no real data needed)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

T0 = pd.Timestamp("2025-01-01", tz="UTC")


def liq_frame(times, notional, side="sell"):
    times = pd.DatetimeIndex(times)
    n = len(times)
    sides = [side] * n if isinstance(side, str) else list(side)
    dirs = ["Close Long" if s == "sell" else "Close Short" for s in sides]
    return pd.DataFrame({"ts": times.as_unit("ns"), "coin": "TEST", "side": sides, "direction": dirs,
                         "px": 100.0, "sz": np.asarray(notional, float) / 100.0,
                         "is_liquidation": True, "notional": np.asarray(notional, float)})


def background_liq(days=40, seed=1, rate_per_hour=2.0, start=T0):
    """Poisson small liquidations over `days`, one fill per event, lognormal notional."""
    rng = np.random.default_rng(seed)
    n = rng.poisson(rate_per_hour * 24 * days)
    secs = np.sort(rng.uniform(0, days * 86400, n))
    t = start + pd.to_timedelta(secs, unit="s")
    return liq_frame(t, rng.lognormal(8, 1, n))


def bars_frame(start, end, price_fn):
    lab = pd.date_range(start, end, freq="5min", inclusive="left")
    p = np.array([price_fn(x) for x in lab], float)
    return pd.DataFrame({"open": p, "high": p, "low": p, "close": p}, index=lab)


def oi_frame(start, end, fn=lambda t: 1000.0, freq="1min"):
    t = pd.date_range(start, end, freq=freq, inclusive="left")
    return pd.Series([fn(x) for x in t], index=t, name="oi", dtype=float)


def decaying_liq(days=40, start=T0, level=1000.0):
    """One fill per minute with strictly decreasing notional: the current rolling value
    is always below every prior value, so the background itself never triggers."""
    n = days * 1440
    t = start + pd.to_timedelta(np.arange(n) * 60 + 30, unit="s")
    return liq_frame(t, level * np.exp(-np.arange(n) / n))
