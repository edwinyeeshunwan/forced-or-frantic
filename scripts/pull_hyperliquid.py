"""Hyperliquid: 5m candles + funding history via the public info API.

Historical OI is NOT served by the REST info API — current snapshots only.
Full historical data (incl. complete liquidations) lives in Hyperliquid's
public S3 archive (s3://hyperliquid-archive) — that's a Phase 2 job and the
clean-benchmark cornerstone of the paper. This script gets candles + funding
so the venue is in the prototype price panel.
Run:  python pull_hyperliquid.py
"""
import time
import datetime as dt

import pandas as pd
import requests

from config import ASSETS, DATA_DIR, END, REQUEST_PAUSE, START, save_df, dataset_exists, http_request

INFO = "https://api.hyperliquid.xyz/info"


def _ms(d: str) -> int:
    return int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def _post(body: dict) -> list:
    r = http_request("POST", INFO, json=body)
    r.raise_for_status()
    return r.json()


def pull_candles(coin: str) -> pd.DataFrame:
    """Walk BACKWARDS from the window end in ~17-day chunks. Hyperliquid's
    candleSnapshot may not serve old/empty ranges; going newest-first means we
    capture whatever exists and report honest coverage. Diagnostics printed if
    the venue returns nothing at all."""
    rows = []
    floor = _ms(START)
    cur_end = _ms(END) + 86_400_000
    step = 4900 * 300_000
    logged_empty = False
    while cur_end > floor:
        cur_start = max(cur_end - step, floor)
        batch = _post({"type": "candleSnapshot",
                       "req": {"coin": coin, "interval": "5m",
                               "startTime": cur_start, "endTime": cur_end}})
        if not isinstance(batch, list):
            print(f"  unexpected API response: {str(batch)[:200]}")
            break
        if batch:
            rows.extend(batch)
        elif not rows and not logged_empty:
            print(f"  empty response for newest window — diagnosing, raw req coin={coin}")
            logged_empty = True
        cur_end = cur_start
        time.sleep(REQUEST_PAUSE)
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["t"].astype("int64"), unit="ms", utc=True)
    for col, src in [("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"), ("volume", "v")]:
        df[col] = df[src].astype(float)
    return (df[["ts", "open", "high", "low", "close", "volume"]]
            .drop_duplicates("ts").sort_values("ts"))


def _old_pull_candles(coin: str) -> pd.DataFrame:
    rows, start = [], _ms(START)
    end = _ms(END) + 86_400_000
    step = 5000 * 300_000  # ~5000 bars per request window
    while start < end:
        batch = _post({"type": "candleSnapshot",
                       "req": {"coin": coin, "interval": "5m",
                               "startTime": start, "endTime": min(start + step, end)}})
        if batch:
            rows.extend(batch)
            start = int(batch[-1]["t"]) + 300_000
        else:
            start += step  # venue may not exist yet in this window
        time.sleep(REQUEST_PAUSE)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["t"].astype("int64"), unit="ms", utc=True)
    for col, src in [("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"), ("volume", "v")]:
        df[col] = df[src].astype(float)
    return (df[["ts", "open", "high", "low", "close", "volume"]]
            .drop_duplicates("ts").sort_values("ts"))


def pull_funding(coin: str) -> pd.DataFrame:
    rows, start = [], _ms(START)
    end = _ms(END) + 86_400_000
    while start < end:
        batch = _post({"type": "fundingHistory", "coin": coin,
                       "startTime": start, "endTime": end})
        if not batch:
            break
        rows.extend(batch)
        nxt = int(batch[-1]["time"]) + 1
        if nxt <= start:
            break
        start = nxt
        time.sleep(REQUEST_PAUSE)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["time"].astype("int64"), unit="ms", utc=True)
    df["funding_rate"] = df["fundingRate"].astype(float)
    return df[["ts", "funding_rate"]].drop_duplicates("ts").sort_values("ts")


def main() -> None:
    for coin in ASSETS["hyperliquid"]:
        for name, fn in [("klines", pull_candles), ("funding", pull_funding)]:
            stem = f"hyperliquid_{coin}_{name}"
            if dataset_exists(stem):
                print(f"skip {stem} (exists)")
                continue
            print(f"pulling hyperliquid {coin} {name} ...")
            df = fn(coin)
            save_df(df, stem)
            span = (df["ts"].min(), df["ts"].max()) if len(df) else ("EMPTY", "EMPTY")
            print(f"  -> {len(df):,} rows, {span[0]} .. {span[1]}")
    print("NOTE: Hyperliquid historical OI/liquidations come from the S3 archive "
          "(Phase 2) — see module docstring.")


if __name__ == "__main__":
    main()
