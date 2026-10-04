"""OKX perpetual swaps: 5m OHLCV (history-candles), funding history, OI history.

OKX free OI history (rubik stats) is coarser/shorter than Binance Vision —
the script reports actual coverage so the gap is documented, not discovered.
Run:  python pull_okx.py
"""
import time
import datetime as dt

import pandas as pd
import requests

from config import ASSETS, DATA_DIR, END, REQUEST_PAUSE, START, save_df, dataset_exists, http_request

BASE = "https://www.okx.com"


def _ms(d: str) -> int:
    return int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def _get(path: str, **params) -> list:
    r = http_request("GET", f"{BASE}{path}", params=params)
    r.raise_for_status()
    j = r.json()
    if j.get("code") != "0":
        raise RuntimeError(f"{path}: {j.get('msg')}")
    return j["data"]


def pull_klines(inst: str) -> pd.DataFrame:
    """history-candles paginates backwards via `after` (returns rows older than it)."""
    rows, after = [], _ms(END) + 86_400_000
    floor = _ms(START)
    while True:
        batch = _get("/api/v5/market/history-candles", instId=inst, bar="5m",
                     after=after, limit=100)
        if not batch:
            break
        rows.extend(batch)
        oldest = min(int(b[0]) for b in batch)
        if oldest <= floor:
            break
        after = oldest
        time.sleep(REQUEST_PAUSE)
    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close",
                                     "volume", "vol_ccy", "vol_quote", "confirm"])
    df = df.astype({"open": float, "high": float, "low": float, "close": float,
                    "volume": float})
    df["ts"] = pd.to_datetime(df["ts_ms"].astype("int64"), unit="ms", utc=True)
    df = df[df["ts"] >= pd.Timestamp(START, tz="UTC")]
    return (df[["ts", "open", "high", "low", "close", "volume"]]
            .drop_duplicates("ts").sort_values("ts"))


def pull_funding(inst: str) -> pd.DataFrame:
    """Start from the latest records (no cursor), then paginate backwards.
    Passing a future timestamp as `after` returns nothing on OKX."""
    rows, after = [], None
    floor = pd.Timestamp(START, tz="UTC")
    while True:
        params = dict(instId=inst, limit=100)
        if after is not None:
            params["after"] = after
        batch = _get("/api/v5/public/funding-rate-history", **params)
        if not batch:
            break
        rows.extend(batch)
        oldest = min(int(b["fundingTime"]) for b in batch)
        if pd.to_datetime(oldest, unit="ms", utc=True) <= floor:
            break
        after = oldest
        time.sleep(REQUEST_PAUSE)
    if not rows:
        print(f"  okx {inst} funding: API returned no records — logged as coverage gap")
        return pd.DataFrame(columns=["ts", "funding_rate"])
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["fundingTime"].astype("int64"), unit="ms", utc=True)
    df["funding_rate"] = df["fundingRate"].astype(float)
    return (df[df["ts"] >= floor][["ts", "funding_rate"]]
            .drop_duplicates("ts").sort_values("ts"))


def pull_oi(inst: str) -> pd.DataFrame:
    """Rubik contract OI history. Granularity/depth limited on the free API —
    pull what exists at 5m, fall back to 1H, report coverage."""
    ccy = inst.split("-")[0]
    for period in ("5m", "1H", "1D"):
        try:
            rows, end = [], _ms(END) + 86_400_000
            floor = _ms(START)
            while True:
                batch = _get("/api/v5/rubik/stat/contracts/open-interest-history",
                             instId=inst, period=period, end=end, limit=100)
                if not batch:
                    break
                rows.extend(batch)
                oldest = min(int(b[0]) for b in batch)
                if oldest <= floor or oldest >= end:
                    break
                end = oldest
                time.sleep(REQUEST_PAUSE)
            if rows:
                df = pd.DataFrame(rows, columns=["ts_ms", "oi", "oi_ccy", "oi_usd"][:len(rows[0])])
                df["ts"] = pd.to_datetime(df["ts_ms"].astype("int64"), unit="ms", utc=True)
                df["oi"] = df["oi"].astype(float)
                df = df[["ts", "oi"]].drop_duplicates("ts").sort_values("ts")
                print(f"  okx {ccy} OI period={period}, back to {df['ts'].min()}")
                return df
        except RuntimeError as e:
            print(f"  okx OI period={period} failed: {e} — trying coarser period")
    return pd.DataFrame()


def main() -> None:
    for inst in ASSETS["okx"]:
        tag = inst.replace("-", "")
        for name, fn in [("klines", pull_klines), ("funding", pull_funding), ("oi", pull_oi)]:
            stem = f"okx_{tag}_{name}"
            if dataset_exists(stem):
                print(f"skip {stem} (exists)")
                continue
            print(f"pulling okx {inst} {name} ...")
            df = fn(inst)
            save_df(df, stem)
            span = (df["ts"].min(), df["ts"].max()) if len(df) else ("EMPTY", "EMPTY")
            print(f"  -> {len(df):,} rows, {span[0]} .. {span[1]}")


if __name__ == "__main__":
    main()
