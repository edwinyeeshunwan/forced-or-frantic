"""Hyperliquid LIQUIDATIONS from Hydromancer's free 'Reservoir' S3 archive.

Verified against the Reservoir schema docs (2026-06):
  bucket : s3://hydromancer-reservoir   (requester pays)
  region : ap-northeast-1               (Tokyo — NOT your config default; set here)
  key    : by_dex/hyperliquid/fills/perp/liquidations/date=YYYY-MM-DD/fills.parquet
           (a dedicated, pre-filtered liquidations partition — one file per UTC day,
            created only for days that have liquidations)

Coverage: Reservoir's Hyperliquid fills start ~Aug 2025. That is the binding
sample limit of this easy free path. To go back into 2024, parse the official
raw node fills (README_phase2_freepath.md, 'free upgrade').

Price for the event study comes for FREE from asset_ctxs mid_px (see
pull_hl_asset_ctxs.py), so this script does NOT download the heavy all-markets
1-second candle files. (If you later want true tick OHLC, the candles live at
by_dex/hyperliquid/candles/1s/date=YYYY-MM-DD/candles.parquet — add a puller then.)

Schema kept (subset of the 27-col fills schema):
  ts, coin, side(buy/sell), direction, px, sz, notional, is_liquidation

Output: data/hyperliquid_{COIN}_liquidations.parquet

Run:
  python pull_hl_reservoir.py --inspect          # fetch one recent day, show schema
  python pull_hl_reservoir.py                      # full pull, ASSETS['hyperliquid']
  python pull_hl_reservoir.py --start 2025-08-01   # override window start
"""
import argparse
import datetime as dt
import io
import sys

import pandas as pd

from config import ASSETS, END, save_df, dataset_exists

BUCKET = "hydromancer-reservoir"
REGION = "ap-northeast-1"
# Reservoir fills coverage begins Aug 2025; default our scan there to skip empties.
RESERVOIR_START = "2025-08-01"


def _key(day: dt.date, kind: str = "liquidations") -> str:
    # kind in {"liquidations", "adl"} — both are perp fill sub-partitions
    return (f"by_dex/hyperliquid/fills/perp/{kind}/"
            f"date={day.isoformat()}/fills.parquet")


def _s3():
    try:
        import boto3  # noqa: F401
    except ImportError:
        sys.exit("boto3 not installed. Run: pip install boto3 pyarrow --break-system-packages")
    import boto3
    return boto3.client("s3", region_name=REGION)


def _read_parquet(raw: bytes) -> pd.DataFrame:
    """Reservoir's parquet is written by a Rust writer whose size-statistics
    pyarrow rejects ('Repetition level histogram size mismatch'). DuckDB — the
    reader Hydromancer documents — parses it fine, so we go through DuckDB."""
    try:
        import duckdb
    except ImportError:
        sys.exit("duckdb not installed. Run: pip install duckdb --break-system-packages")
    import os
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tf:
        tf.write(raw)
        path = tf.name
    try:
        return duckdb.query(f"SELECT * FROM read_parquet('{path}')").to_df()
    finally:
        os.unlink(path)


def _fetch_day(s3, day: dt.date, kind: str = "liquidations") -> pd.DataFrame | None:
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=_key(day, kind), RequestPayer="requester")
    except Exception as e:  # noqa: BLE001 — missing day (no file for this kind) -> skip
        if any(t in str(e) for t in ("NoSuchKey", "404", "Not Found")):
            return None
        raise
    return _read_parquet(obj["Body"].read())


def _normalise(raw: pd.DataFrame, coin: str) -> pd.DataFrame:
    df = raw[raw["coin"].astype(str) == coin].copy()
    if df.empty:
        return df
    out = pd.DataFrame({
        "ts": pd.to_datetime(df["timestamp"], utc=True),
        "coin": coin,
        "side": df["side"].astype(str),
        "direction": df.get("direction", pd.Series("", index=df.index)).astype(str),
        "px": pd.to_numeric(df["price"], errors="coerce"),
        "sz": pd.to_numeric(df["size"], errors="coerce"),
    })
    if "is_liquidation" in df.columns:
        out["is_liquidation"] = df["is_liquidation"].values
    out["notional"] = out["px"] * out["sz"]
    return out.dropna(subset=["ts", "notional"]).sort_values("ts")


def inspect(s3, start: dt.date) -> None:
    # walk forward from the window's later half to land on a populated day fast
    for off in (0, 1, 7, 30, 60, 90):
        probe = max(start, dt.date(2025, 10, 1)) + dt.timedelta(days=off)
        raw = _fetch_day(s3, probe)
        if raw is not None and len(raw):
            print(f"=== liquidations sample: {probe} ({_key(probe)}) ===")
            print("columns:", list(raw.columns))
            cols = [c for c in ["timestamp", "coin", "side", "direction", "price",
                                "size", "is_liquidation", "liquidation_method"]
                    if c in raw.columns]
            print(raw[cols].head(10).to_string())
            print(f"\nrows in day: {len(raw):,} | coins: "
                  f"{sorted(raw['coin'].astype(str).unique())[:12]}")
            print("direction values:", raw.get("direction", pd.Series(dtype=str)).value_counts().to_dict())
            return
    print("No liquidation files found near", start, "- check region/credentials.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--start", default=RESERVOIR_START)
    ap.add_argument("--end", default=END)
    a = ap.parse_args()
    s3 = _s3()
    start = dt.date.fromisoformat(a.start)
    end = dt.date.fromisoformat(a.end)

    if a.inspect:
        inspect(s3, start)
        return

    # liquidations = the event trigger; adl = the external validation (Auto-Deleveraging,
    # an independent forced-liquidation mechanism not used in the OI classification)
    for kind in ("liquidations", "adl"):
        pull_kind(s3, kind, start, end)


def pull_kind(s3, kind: str, start: dt.date, end: dt.date) -> None:
    coins = set(ASSETS["hyperliquid"])
    if all(dataset_exists(f"hyperliquid_{c}_{kind}") for c in coins):
        print(f"all hyperliquid {kind} datasets exist — delete to re-pull")
        return
    frames = {c: [] for c in coins}
    n_days, day = 0, start
    while day <= end:
        raw = _fetch_day(s3, day, kind)
        if raw is not None and len(raw):
            n_days += 1
            for c in coins:
                sub = _normalise(raw, c)
                if len(sub):
                    frames[c].append(sub)
        day += dt.timedelta(days=1)
    print(f"({kind}: {n_days} days with files)")
    for c in coins:
        stem = f"hyperliquid_{c}_{kind}"
        if dataset_exists(stem):
            continue
        df = (pd.concat(frames[c], ignore_index=True).drop_duplicates().sort_values("ts")
              if frames[c] else pd.DataFrame(columns=["ts", "coin", "side", "direction",
                                                      "px", "sz", "notional"]))
        save_df(df, stem)
        span = f", {df['ts'].min()} .. {df['ts'].max()}" if len(df) else ""
        print(f"{stem}: {len(df):,} {kind} fills{span}")


if __name__ == "__main__":
    main()
