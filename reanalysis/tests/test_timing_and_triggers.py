import numpy as np
import pandas as pd

from synth import T0, background_liq, decaying_liq, liq_frame
import events as E
from legacy import NS as LEGACY


def test_completed_bin_timing():
    liq = liq_frame([T0 + pd.Timedelta("12h3min30s"), T0 + pd.Timedelta("12h5min")], [7.0, 11.0])
    p = E.Params()
    b = E.sell_bins(liq, p, start=T0, end=T0 + pd.Timedelta(days=1))
    assert b[T0 + pd.Timedelta("12h5min")] == 7.0          # [12:00, 12:05) -> labelled 12:05
    assert b[T0 + pd.Timedelta("12h10min")] == 11.0        # a fill exactly at 12:05 belongs to the next bin
    assert b.index.name == "bin_end"
    # legacy labels the same fill at the bin START (information from 12:03 shown at 12:00)
    leg = LEGACY["_long_liq_notional"](liq)
    assert leg[T0 + pd.Timedelta("12h")] == 7.0
    # R(E) uses fills in [E-15m, E) only
    R = E.rolling_notional(b, p)
    assert R[T0 + pd.Timedelta("12h5min")] == 7.0
    assert R[T0 + pd.Timedelta("12h15min")] == 18.0
    assert R[T0 + pd.Timedelta("12h20min")] == 11.0


def test_threshold_excludes_current_observation():
    liq = background_liq(days=35, seed=3)
    p = E.Params()
    tt = E.trigger_table(liq, p)
    E_t = tt.index[-100]
    R = tt["R"].copy()
    prior = R[(R.index >= E_t - pd.Timedelta(days=30)) & (R.index < E_t)].dropna()
    assert np.isclose(tt.loc[E_t, "thr"], np.quantile(prior, 0.99))
    # changing the current value cannot change its own threshold
    R2 = R.copy()
    R2[E_t] = R2[E_t] * 1e6 + 1e9
    thr2 = E.thresholds(R2, p)
    assert np.isclose(thr2[E_t], tt.loc[E_t, "thr"])
    # the legacy (current-inclusive) threshold does move
    pl = p.with_(include_current=True)
    assert not np.isclose(E.thresholds(R2, pl)[E_t], E.thresholds(R, pl)[E_t])


def test_threshold_ignores_missing_bins():
    idx = pd.date_range(T0, periods=200, freq="5min")
    R = pd.Series(np.arange(200, dtype=float), index=idx)
    R.iloc[50:80] = np.nan
    p = E.Params(trail_days=30)
    thr = E.thresholds(R, p)
    prior = R.iloc[:150].dropna()
    assert np.isclose(thr.iloc[150], np.quantile(prior, 0.99))


def test_warmup_eligibility():
    liq = background_liq(days=40, seed=4)
    for days in (30, 7):
        p = E.Params(warmup_days=days)
        tt = E.trigger_table(liq, p)
        first_R = tt.index[0] + pd.Timedelta(minutes=10)
        assert tt.index[tt["eligible"]].min() == first_R + pd.Timedelta(days=days)
        assert not tt.loc[tt.index < first_R + pd.Timedelta(days=days), "trigger"].any()


def _with_spikes(seed=5):
    base = background_liq(days=45, seed=seed)
    spikes = [T0 + pd.Timedelta(days=d, hours=h) for d, h in [(32, 1), (33, 7.3), (36, 12), (36, 13.5), (40, 3)]]
    extra = liq_frame(spikes, [5e6] * len(spikes))
    return pd.concat([base, extra]).sort_values("ts").reset_index(drop=True)


def test_trigger_truncation_invariance():
    liq = _with_spikes()
    p = E.Params()
    ev_full, tt_full = E.detect(liq, p)
    assert len(ev_full) >= 3
    start, end = E.coverage_bounds(liq)
    for T in [T0 + pd.Timedelta(days=33, hours=7, minutes=20), T0 + pd.Timedelta(days=36, hours=13, minutes=33),
              T0 + pd.Timedelta(days=41)]:
        trunc = liq[liq["ts"] < T]
        bins = E.sell_bins(trunc, p, start=start, end=end)
        tt_tr = E.trigger_table(trunc, p, bins=bins)
        known = tt_tr.index <= T
        # every trigger flag and threshold decided by time T is identical
        pd.testing.assert_series_equal(tt_tr.loc[known, "trigger"], tt_full.loc[tt_tr.index[known], "trigger"])
        a = tt_tr.loc[known, "thr"].dropna()
        assert np.allclose(a, tt_full.loc[a.index, "thr"])
        ev_tr = E.onsets_from_triggers(tt_tr, p)
        e_full = ev_full.loc[ev_full.E0 <= T, "E0"].reset_index(drop=True)
        e_tr = ev_tr.loc[ev_tr.E0 <= T, "E0"].reset_index(drop=True)
        assert e_full.equals(e_tr)


def test_legacy_left_label_is_not_truncation_invariant():
    """Documents legacy bug A1: a legacy trigger stamped t0 can depend on fills after t0."""
    base = decaying_liq(days=12)
    spike_t = T0 + pd.Timedelta(days=10, hours=5, minutes=3)
    liq = pd.concat([base, liq_frame([spike_t], [5e6])]).sort_values("ts").reset_index(drop=True)
    ev = LEGACY["detect_events"](liq, 0.99)
    t0 = T0 + pd.Timedelta(days=10, hours=5)
    assert (ev["t0"] == t0).any()
    ev_tr = LEGACY["detect_events"](liq[liq.ts < t0 + pd.Timedelta(minutes=1)], 0.99)
    assert ev_tr.empty or not (ev_tr["t0"] == t0).any()   # stamped 05:00, but needs the 05:03 fill


def test_bounded_merging():
    base = decaying_liq(days=40)
    chain = [T0 + pd.Timedelta(days=35) + pd.Timedelta(minutes=100 * k) for k in range(7)]  # every 100 min, 10 h
    liq = pd.concat([base, liq_frame(chain, [5e6] * 7)]).sort_values("ts").reset_index(drop=True)
    p = E.Params()
    ev, _ = E.detect(liq, p)
    ev_c = ev[(ev.E0 >= chain[0]) & (ev.E0 <= chain[-1] + pd.Timedelta(hours=1))]
    assert len(ev_c) == 1                                     # one onset (legacy chaining rule)
    e = ev_c.iloc[0]
    assert e["chain_span_min"] > p.win_post_min and bool(e["cascade_continues"])
    # enlarge liquidations that occur after the event window: onset measures unchanged
    later = liq_frame(chain[2:], [5e8] * 5)
    liq2 = pd.concat([base, liq_frame(chain[:2], [5e6] * 2), later]).sort_values("ts").reset_index(drop=True)
    ev2, _ = E.detect(liq2, p)
    e2 = ev2[ev2.E0 == e["E0"]].iloc[0]
    for col in ("R_onset", "thr_onset", "notional_W", "n_triggers_in_window"):
        assert np.isclose(e[col], e2[col]), col
    # legacy intensity (max over the chained span) is not bounded
    l1 = LEGACY["detect_events"](liq, 0.99)
    l2 = LEGACY["detect_events"](liq2, 0.99)
    t = chain[0]
    a = l1[(l1.t0 >= t - pd.Timedelta(minutes=5)) & (l1.t0 <= t)].iloc[0]
    b = l2[(l2.t0 >= t - pd.Timedelta(minutes=5)) & (l2.t0 <= t)].iloc[0]
    assert b["liq_notional"] > 10 * a["liq_notional"]
    assert (a["end"] - a["t0"]) > pd.Timedelta(hours=2)


def test_side_mapping_is_checked():
    bad = liq_frame([T0], [1.0])
    bad.loc[0, "direction"] = "Close Short"
    try:
        E.check_side_mapping(bad)
    except ValueError:
        return
    raise AssertionError("inconsistent side mapping was accepted")
