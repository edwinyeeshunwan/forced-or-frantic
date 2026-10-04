"""Binance USD-M perpetuals: 5m OHLCV + funding (REST, full history) and
5-min open interest (data.binance.vision daily metrics files, full history).

REST OI history is limited to ~30 days, so OI comes from the Vision archive.
Run:  python pull_binance.py
Output: data/binance_{symbol}_{klines|funding|oi}.parquet + coverage report.
"""
import io
import time
import zipfile
import datetime as dt

import pandas as pd
import requests

from config import ASSETS, DATA_DIR, END, REQUEST_PAUSE, START, save_df, dataset_exists, http_request

FAPI = "https://fapi.binance.com"
VISION = "https://data.binance.vision/data/futures/um/daily/metrics"


def _ms(d: str) -> int:
    return int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def pull_klines(symbol: str) -> pd.DataFrame:
    rows, start = [], _ms(START)
    end = _ms(END) + 86_400_000
    while start < end:
        r = http_request("GET", f"{FAPI}/fapi/v1/klines", params={"symbol": symbol, "interval": "5m", "startTime": start, "limit": 1500})
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        start = batch[-1][0] + 300_000
        time.sleep(REQUEST_PAUSE)
    df = pd.DataFrame(
        rows,
        columns=["open_time", "open", "high", "low", "close", "volume", "close_time",
                 "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"],
    ).astype({"open": float, "high": float, "low": float, "close": float,
              "volume": float, "quote_volume": float})
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df[["ts", "open", "high", "low", "close", "volume", "quote_volume", "trades"]]


def pull_funding(symbol: str) -> pd.DataFrame:
    rows, start = [], _ms(START)
    end = _ms(END) + 86_400_000
    while start < end:
        r = http_request("GET", f"{FAPI}/fapi/v1/fundingRate", params={"symbol": symbol, "startTime": start, "limit": 1000})
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        start = batch[-1]["fundingTime"] + 1
        time.sleep(REQUEST_PAUSE)
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["fundingTime"].astype("int64"), unit="ms", utc=True)
    df["funding_rate"] = df["fundingRate"].astype(float)
    return df[["ts", "funding_rate"]]


def pull_oi_vision(symbol: str) -> pd.DataFrame:
    """Daily metrics ZIPs from data.binance.vision; 5-min OI snapshots.
    Missing days (404) are recorded, not fatal."""
    frames, missing = [], []
    day = dt.date.fromisoformat(START)
    last = dt.date.fromisoformat(END)
    while day <= last:
        url = f"{VISION}/{symbol}/{symbol}-metrics-{day.isoformat()}.zip"
        r = http_request("GET", url)
        if r.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                with z.open(z.namelist()[0]) as f:
                    d = pd.read_csv(f)
            d.columns = [c.strip().lower() for c in d.columns]
            # Vision metrics: create_time, symbol, sum_open_interest, sum_open_interest_value, ...
            d["ts"] = pd.to_datetime(d["create_time"], utc=True, format="mixed")
            d["oi"] = d["sum_open_interest"].astype(float)
            d["oi_value"] = d["sum_open_interest_value"].astype(float)
            frames.append(d[["ts", "oi", "oi_value"]])
        else:
            missing.append(day.isoformat())
        day += dt.timedelta(days=1)
        time.sleep(REQUEST_PAUSE / 2)
    if missing:
        (DATA_DIR / f"binance_{symbol}_oi_missing_days.txt").write_text("\n".join(missing))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def main() -> None:
    for symbol in ASSETS["binance"]:
        for name, fn in [("klines", pull_klines), ("funding", pull_funding), ("oi", pull_oi_vision)]:
            stem = f"binance_{symbol}_{name}"
            if dataset_exists(stem):
                print(f"skip {stem} (exists)")
                continue
            print(f"pulling binance {symbol} {name} ...")
            df = fn(symbol)
            save_df(df, stem)
            span = (df["ts"].min(), df["ts"].max()) if len(df) else ("EMPTY", "EMPTY")
            print(f"  -> {len(df):,} rows, {span[0]} .. {span[1]}")


if __name__ == "__main__":
    main()
