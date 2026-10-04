"""Bybit v5 linear perpetuals: 5m OHLCV, funding history, OI history (5min).

Bybit's OI endpoint paginates backwards with a cursor; actual history depth
varies — the script reports the earliest timestamp it could reach.
Run:  python pull_bybit.py
"""
import time
import datetime as dt

import pandas as pd
import requests

from config import ASSETS, DATA_DIR, END, REQUEST_PAUSE, START, save_df, dataset_exists, http_request

BASE = "https://api.bybit.com"


def _ms(d: str) -> int:
    return int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def _get(path: str, **params) -> dict:
    r = http_request("GET", f"{BASE}{path}", params=params)
    r.raise_for_status()
    j = r.json()
    if j.get("retCode") != 0:
        raise RuntimeError(f"{path}: {j.get('retMsg')}")
    return j["result"]


def pull_klines(symbol: str) -> pd.DataFrame:
    rows, start = [], _ms(START)
    end = _ms(END) + 86_400_000
    while start < end:
        res = _get("/v5/market/kline", category="linear", symbol=symbol,
                   interval="5", start=start, limit=1000)
        batch = res.get("list", [])
        if not batch:
            break
        batch = sorted(batch, key=lambda x: int(x[0]))  # bybit returns newest-first
        rows.extend(batch)
        nxt = int(batch[-1][0]) + 300_000
        if nxt <= start:
            break
        start = nxt
        time.sleep(REQUEST_PAUSE)
    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume", "turnover"])
    df = df.astype({"open": float, "high": float, "low": float, "close": float,
                    "volume": float, "turnover": float})
    df["ts"] = pd.to_datetime(df["ts_ms"].astype("int64"), unit="ms", utc=True)
    return df.drop(columns="ts_ms").drop_duplicates("ts").sort_values("ts")


def pull_funding(symbol: str) -> pd.DataFrame:
    rows, end = [], _ms(END) + 86_400_000
    floor = _ms(START)
    while True:
        res = _get("/v5/market/funding/history", category="linear", symbol=symbol,
                   endTime=end, limit=200)
        batch = res.get("list", [])
        if not batch:
            break
        rows.extend(batch)
        oldest = min(int(b["fundingRateTimestamp"]) for b in batch)
        if oldest <= floor or oldest >= end:
            break
        end = oldest - 1
        time.sleep(REQUEST_PAUSE)
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["fundingRateTimestamp"].astype("int64"), unit="ms", utc=True)
    df["funding_rate"] = df["fundingRate"].astype(float)
    return (df[df["ts"] >= pd.Timestamp(START, tz="UTC")]
            [["ts", "funding_rate"]].drop_duplicates("ts").sort_values("ts"))


def pull_oi(symbol: str) -> pd.DataFrame:
    rows, cursor = [], None
    floor = pd.Timestamp(START, tz="UTC")
    while True:
        params = dict(category="linear", symbol=symbol, intervalTime="5min", limit=200)
        if cursor:
            params["cursor"] = cursor
        res = _get("/v5/market/open-interest", **params)
        batch = res.get("list", [])
        if not batch:
            break
        rows.extend(batch)
        cursor = res.get("nextPageCursor")
        oldest = pd.to_datetime(int(batch[-1]["timestamp"]), unit="ms", utc=True)
        if not cursor or oldest <= floor:
            break
        time.sleep(REQUEST_PAUSE)
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
    df["oi"] = df["openInterest"].astype(float)
    df = df[["ts", "oi"]].drop_duplicates("ts").sort_values("ts")
    print(f"  bybit {symbol} OI reaches back to: {df['ts'].min()}  "
          f"(window starts {START} — gap is a documented free-data limit)")
    return df


def main() -> None:
    for symbol in ASSETS["bybit"]:
        for name, fn in [("klines", pull_klines), ("funding", pull_funding), ("oi", pull_oi)]:
            stem = f"bybit_{symbol}_{name}"
            if dataset_exists(stem):
                print(f"skip {stem} (exists)")
                continue
            print(f"pulling bybit {symbol} {name} ...")
            df = fn(symbol)
            save_df(df, stem)
            span = (df["ts"].min(), df["ts"].max()) if len(df) else ("EMPTY", "EMPTY")
            print(f"  -> {len(df):,} rows, {span[0]} .. {span[1]}")


if __name__ == "__main__":
    main()
