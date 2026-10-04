import numpy as np
import pandas as pd

from synth import T0, bars_frame, oi_frame
import events as E
import episodes as EP
from legacy import NS as LEGACY

E0 = T0 + pd.Timedelta(days=2, hours=12)


def _ev(e0=E0):
    return pd.DataFrame({"E0": [e0]})


def _vshape(depth=0.03, recover_at=None):
    """Price 100 before E0, falls to 100*(1-depth) by E0+30m, flat, recovers at recover_at."""
    def f(t):
        if t < E0 - pd.Timedelta(minutes=15):
            return 100.0
        if t < E0 + pd.Timedelta(minutes=30):
            return 100 * (1 - depth)
        if recover_at is not None and t >= recover_at:
            return 100.0
        return 100 * (1 - depth)
    return f


def test_oi_staleness_asof():
    oi = oi_frame(T0, T0 + pd.Timedelta(hours=10))
    last = oi.index[-1]
    v = E.asof_values(oi.index, oi.to_numpy(), pd.DatetimeIndex([last + pd.Timedelta(minutes=2),
                                                                 last + pd.Timedelta(minutes=3)]),
                      pd.Timedelta(minutes=2))
    assert np.isfinite(v[0]) and np.isnan(v[1])
    # legacy forward fill onto a 5-min grid carries the last value for up to 12 grid rows
    grid = pd.date_range(T0, T0 + pd.Timedelta(hours=12), freq="5min")
    leg = oi.reindex(grid, method="ffill", limit=12)
    assert leg.loc[T0 + pd.Timedelta(hours=10, minutes=55)] == oi.iloc[-1]   # 56 minutes stale
    assert np.isnan(leg.loc[T0 + pd.Timedelta(hours=11)])


def test_oi_missing_in_window_gives_unknown_class():
    bars = bars_frame(T0, T0 + pd.Timedelta(days=4), _vshape())
    oi = oi_frame(T0, E0 + pd.Timedelta(minutes=30))    # OI feed stops inside W
    p = E.Params()
    m = E.measure(_ev(), bars, oi, p)
    assert np.isnan(m.loc[0, "doi"]) and "oi_trough" in m.loc[0, "reason"]
    c = E.classify(m, p)
    assert c.loc[0, "klass"] == "unknown"


def test_oi_response_and_reference_timing():
    def oi_fn(t):
        return 1000.0 if t < E0 - pd.Timedelta(minutes=14) else 950.0
    bars = bars_frame(T0, T0 + pd.Timedelta(days=4), _vshape(recover_at=E0 + pd.Timedelta(hours=5)))
    oi = oi_frame(T0, T0 + pd.Timedelta(days=4), oi_fn)
    m = E.measure(_ev(), bars, oi, E.Params())
    assert np.isclose(m.loc[0, "doi"], -0.05)
    assert np.isclose(m.loc[0, "p_ref"], 100.0)         # reference ends before the trigger window
    assert np.isclose(m.loc[0, "disp"], np.log(0.97))
    # legacy-aligned reference includes bars inside the trigger window -> already depressed
    ml = E.measure(_ev(), bars, oi, E.Params(ref_mode="legacy_aligned"))
    assert ml.loc[0, "p_ref"] < 100.0


def test_intrabar_crossing_ambiguity():
    """Trough bar whose high reaches the reference: legacy counts a recovery inside the
    trough bar; corrected measures do not use that bar's high."""
    bars = bars_frame(T0, T0 + pd.Timedelta(days=4), _vshape())
    tl = E0 + pd.Timedelta(minutes=30)
    bars.loc[tl, "low"] = 95.0          # the trough
    bars.loc[tl, "high"] = 100.0        # ... and the same bar's high touches the reference
    oi = oi_frame(T0, T0 + pd.Timedelta(days=4))
    p = E.Params()
    m = E.measure(_ev(), bars, oi, p)
    assert m.loc[0, "trough_label"] == tl
    assert not m.loc[0, "rec_event"] and not m.loc[0, "rec_trough_high_event"]
    assert not m.loc[0, "rec_trough_close_event"]
    # legacy: crossing found at the trough bar itself
    ev = pd.DataFrame({"t0": [E0], "liq_notional": [1.0]})
    leg = LEGACY["outcomes"](bars, oi.reindex(bars.index, method="ffill", limit=12), ev)
    assert not leg.loc[0, "censored"]
    assert leg.loc[0, "ttr_min"] == (tl - E0).total_seconds() / 60


def test_close_based_recovery_after_window():
    rec_t = E0 + pd.Timedelta(hours=5)
    bars = bars_frame(T0, T0 + pd.Timedelta(days=4), _vshape(recover_at=rec_t))
    oi = oi_frame(T0, T0 + pd.Timedelta(days=4))
    m = E.measure(_ev(), bars, oi, E.Params())
    A = E0 + pd.Timedelta(minutes=120)
    assert m.loc[0, "rec_event"]
    assert m.loc[0, "rec_min"] == ((rec_t + pd.Timedelta(minutes=5)) - A).total_seconds() / 60


def test_insufficient_followup_is_censored_at_observed_end():
    end = E0 + pd.Timedelta(hours=10)
    bars = bars_frame(T0, end, _vshape())
    oi = oi_frame(T0, end)
    m = E.measure(_ev(), bars, oi, E.Params())
    A = E0 + pd.Timedelta(minutes=120)
    assert not m.loc[0, "rec_event"] and not m.loc[0, "rec_complete"]
    assert m.loc[0, "rec_min"] == (end - A).total_seconds() / 60       # not 22 h
    assert np.isnan(m.loc[0, "p24h"]) and np.isfinite(m.loc[0, "p6h"])
    # legacy assigns a full 24 h to the same event
    ev = pd.DataFrame({"t0": [E0], "liq_notional": [1.0]})
    leg = LEGACY["outcomes"](bars, oi.reindex(bars.index, method="ffill", limit=12), ev)
    assert leg.loc[0, "ttr_min"] == 1440 and leg.loc[0, "censored"]


def test_missing_bars_end_followup():
    rec_t = E0 + pd.Timedelta(hours=8)
    bars = bars_frame(T0, T0 + pd.Timedelta(days=4), _vshape(recover_at=rec_t))
    oi = oi_frame(T0, T0 + pd.Timedelta(days=4))
    gap_start = E0 + pd.Timedelta(hours=4)
    # two missing bars (gap between bar ends = 15 min): follow-up continues
    b2 = bars.drop([gap_start, gap_start + pd.Timedelta(minutes=5)])
    m2 = E.measure(_ev(), b2, oi, E.Params())
    assert m2.loc[0, "rec_event"]
    # three missing bars (20 min): follow-up stops at the last bar end before the gap
    b3 = bars.drop([gap_start + pd.Timedelta(minutes=5 * k) for k in range(3)])
    m3 = E.measure(_ev(), b3, oi, E.Params())
    A = E0 + pd.Timedelta(minutes=120)
    assert not m3.loc[0, "rec_event"] and not m3.loc[0, "rec_complete"]
    assert m3.loc[0, "rec_min"] == (gap_start - A).total_seconds() / 60


def test_horizon_price_max_age():
    bars = bars_frame(T0, T0 + pd.Timedelta(days=4), _vshape())
    oi = oi_frame(T0, T0 + pd.Timedelta(days=4))
    h6 = E0 + pd.Timedelta(hours=6)
    drop = [h6 - pd.Timedelta(minutes=5 * k) for k in range(1, 4)]   # bars ending at 6h, 6h-5m, 6h-10m
    m = E.measure(_ev(), bars.drop(drop), oi, E.Params())
    assert np.isnan(m.loc[0, "p6h"])
    m2 = E.measure(_ev(), bars.drop(drop[:2]), oi, E.Params())    # as-of close 10 min old is allowed
    assert np.isfinite(m2.loc[0, "p6h"])


def test_shared_btc_eth_episodes():
    t = pd.Series(pd.to_datetime(["2025-10-10 20:00", "2025-10-10 20:10", "2025-10-11 03:30",
                                  "2025-10-11 12:00", "2025-10-20 00:00"], utc=True))
    sym = ["BTC", "ETH", "BTC", "ETH", "BTC"]
    e6 = EP.linkage_episodes(t, 6)
    e24 = EP.linkage_episodes(t, 24)
    assert e6[0] == e6[1]                       # same shock in both assets -> one unit
    assert e6[1] != e6[2]                       # 7h20m later: separate at 6h linkage
    assert e24[0] == e24[1] == e24[2] == e24[3] # chained within 24h
    assert e24[4] != e24[3]
    # order of input rows does not matter
    perm = [4, 2, 0, 3, 1]
    e6p = EP.linkage_episodes(t.iloc[perm].reset_index(drop=True), 6)
    assert len(set(zip(e6[perm], e6p))) == len(set(e6))


def test_classification_rule():
    ev = pd.DataFrame({"E0": pd.date_range(T0, periods=25, freq="D"),
                       "doi": list(np.linspace(-0.04, 0.01, 24)) + [-0.03]})
    c = E.classify(ev, E.Params())
    assert c.loc[0, "klass"] == "contraction"                  # fixed -2.5% before 20 priors
    q = np.quantile(ev["doi"].iloc[:24], 0.10)
    assert np.isclose(c.loc[24, "contraction_cut"], q)
    assert c.loc[24, "klass"] == ("contraction" if -0.03 <= q else "intermediate")
    assert (c.loc[c["doi"] > -0.005, "klass"].iloc[1:] == "limited").all()
