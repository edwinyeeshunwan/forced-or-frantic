"""Offline pipeline test: injects one known deleverage flush into synthetic
noise and asserts the event-table builder finds it (and only it) with the
right magnitude, ΔOI, and recovery behaviour. No network needed.

Run:  python run_synthetic_test.py
"""
import subprocess
import sys

import numpy as np
import pandas as pd

from config import load_df, save_df


def make_fixture(stem: str, recovery_per_bar: float) -> pd.Timestamp:
    rng = np.random.default_rng(7)
    idx = pd.date_range("2024-01-01", periods=288 * 60, freq="5min", tz="UTC")
    ret = rng.normal(0, 0.0008, len(idx))
    oi = 100_000 + np.cumsum(rng.normal(0, 30, len(idx)))
    i0 = 288 * 45
    ret[i0:i0 + 12] -= 0.005                      # ~-6% crash over 1h
    ret[i0 + 24:i0 + 72] += recovery_per_bar      # recovery
    oi[i0:i0 + 12] -= np.linspace(0, 5000, 12)    # -5% OI = genuine deleverage
    oi[i0 + 12:] -= 5000
    price = 40_000 * np.exp(np.cumsum(ret))
    df = pd.DataFrame({"ts": idx, "close": price, "volume": 1.0})
    df["open"] = df["close"].shift(1).fillna(df["close"])
    df["high"] = df[["open", "close"]].max(axis=1) * 1.0005
    df["low"] = df[["open", "close"]].min(axis=1) * 0.9995
    save_df(df, f"{stem}_BTCTEST_klines")
    save_df(pd.DataFrame({"ts": idx, "oi": oi}), f"{stem}_BTCTEST_oi")
    return idx[i0]


def main() -> None:
    t_inject = make_fixture("synthrec", recovery_per_bar=0.0016)
    subprocess.run([sys.executable, "build_event_table.py",
                    "--venue", "synthrec", "--symbol", "BTCTEST"], check=True)
    ev = load_df("events_synthrec_BTCTEST")

    assert len(ev) == 1, f"expected 1 event, got {len(ev)}"
    t0 = pd.Timestamp(ev.t0.iloc[0])
    assert abs((t0 - t_inject).total_seconds()) <= 1800, f"event time off: {t0} vs {t_inject}"
    assert -0.08 < ev.peak_disloc.iloc[0] < -0.04, f"dislocation off: {ev.peak_disloc.iloc[0]}"
    assert -0.07 < ev.doi_event.iloc[0] < -0.03, f"ΔOI off: {ev.doi_event.iloc[0]}"
    assert not ev.censored.iloc[0], "recovery should be uncensored in this fixture"
    assert ev.ttr_min.iloc[0] < 600, f"TTR too long: {ev.ttr_min.iloc[0]}"
    print("ALL ASSERTIONS PASSED — pipeline detects the injected flush correctly.")
    print("(synth* fixture files in data/ are ignored by the default builder run.)")


if __name__ == "__main__":
    main()
