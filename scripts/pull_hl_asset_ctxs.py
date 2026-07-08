"""Hyperliquid OPEN INTEREST (+ mark/oracle price, funding) from the OFFICIAL
free S3 archive:  s3://hyperliquid-archive/asset_ctxs/[YYYYMMDD].csv.lz4

Why this file exists
--------------------
The REST `info` API serves only CURRENT OI snapshots, so pull_hyperliquid.py
could not get historical OI. The official archive publishes one lz4-compressed
CSV of asset contexts per UTC day, back to launch — this is the FREE,
full-history OI source for the conditioning variable (spec 3c, ΔOI).

Requester-pays: you need AWS credentials on this machine and you pay the (small)
S3 transfer cost. See README_phase2_freepath.md.

Output: data/hyperliquid_{COIN}_oi.parquet  (ts, oi[, oi_value])
        — same stem convention as every other venue, so build_event_table*.py
          can join it with no changes.

VERIFY ON FIRST RUN: the exact column names inside asset_ctxs are confirmed by
`--inspect`, which downloads ONE day, prints the schema + head, and stops before
you spend egress on the whole window. Adjust the *_CANDIDATES lists below if the
detected columns look wrong.

Run:
  python pull_hl_asset_ctxs.py --inspect          # one day, print schema, stop
  python pull_hl_asset_ctxs.py                     # full window, all HL coins
  python pull_hl_asset_ctxs.py --start 2025-08-01  # override window start
"""
import argparse
import datetime as dt
import io
import sys

import pandas as pd

from config import ASSETS, DATA_DIR, END, START, save_df, dataset_exists

BUCKET = "hyperliquid-archive"
PREFIX = "asset_ctxs"  # s3://hyperliquid-archive/asset_ctxs/[YYYYMMDD].csv.lz4

# Column-name candidates (lower-cased). asset_ctxs mirrors the API's
# metaAndAssetCtxs fields; names vary by archive vintage, so we detect.
COIN_CANDIDATES = ["coin", "name", "asset", "symbol", "ticker"]
TIME_CANDIDATES = ["time", "timestamp", "ts", "date", "datetime"]
OI_CANDIDATES = ["open_interest", "openinterest", "oi", "open_interest_usd"]
OIVAL_CANDIDATES = ["open_interest_value", "oi_value", "open_interest_usd",
                    "open_interest_notional"]
# price for the event study: prefer mid, then mark, then oracle (all in asset_ctxs)
PX_CANDIDATES = ["mid_px", "mark_px", "oracle_px", "midpx", "markpx"]
# funding rate — external validator (not built from OI or liquidation magnitude)
FUNDING_CANDIDATES = ["funding", "funding_rate", "fundingrate", "funding_pct"]


def _s3():
    try:
        import boto3
    except ImportError:
        sys.exit("boto3 not installed. Run: pip install boto3 lz4 --break-system-packages")
    return boto3.client("s3")


def _decompress_lz4(raw: bytes) -> bytes:
    """asset_ctxs files use the lz4 *frame* format (what the `unlz4` CLI emits)."""
    import lz4.frame
    return lz4.frame.decompress(raw)


def _pick(cols, candidates):
    low = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand in low:
            return low[cand]
    return None


def _fetch_day(s3, day: dt.date) -> pd.DataFrame | None:
    key = f"{PREFIX}/{day.strftime('%Y%m%d')}.csv.lz4"
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key, RequestPayer="requester")
    except Exception as e:  # noqa: BLE001 — missing day / access error, record & skip
        if "NoSuchKey" in str(e) or "404" in str(e):
            return None
        raise
    csv_bytes = _decompress_lz4(obj["Body"].read())
    return pd.read_csv(io.BytesIO(csv_bytes))


def _normalise(raw: pd.DataFrame) -> pd.DataFrame:
    cols = list(raw.columns)
    c_coin = _pick(cols, COIN_CANDIDATES)
    c_time = _pick(cols, TIME_CANDIDATES)
    c_oi = _pick(cols, OI_CANDIDATES)
    if not (c_coin and c_time and c_oi):
        raise KeyError(f"could not map coin/time/oi in columns {cols} — "
                       "edit the *_CANDIDATES lists in pull_hl_asset_ctxs.py")
    c_oival = _pick([c for c in cols if c != c_oi], OIVAL_CANDIDATES)
    c_px = _pick(cols, PX_CANDIDATES)
    out = pd.DataFrame({"coin": raw[c_coin].astype(str),
                        "ts": pd.to_datetime(raw[c_time], utc=True, errors="coerce"),
                        "oi": pd.to_numeric(raw[c_oi], errors="coerce")})
    if c_oival:
        out["oi_value"] = pd.to_numeric(raw[c_oival], errors="coerce")
    if c_px:
        out["px"] = pd.to_numeric(raw[c_px], errors="coerce")
    c_fund = _pick(cols, FUNDING_CANDIDATES)
    if c_fund:
        out["funding"] = pd.to_numeric(raw[c_fund], errors="coerce")
    return out.dropna(subset=["ts", "oi"])


def _klines_from_px(sub: pd.DataFrame) -> pd.DataFrame:
    """1-min point prices (asset_ctxs mid_px) -> 5m OHLC bars for the event study.
    NOTE: high/low come from 1-min samples, so they slightly understate true
    intrabar extremes — a conservative (effect-shrinking) approximation, fine for
    the pilot. Swap in Reservoir 1s candles later if you want exact OHLC."""
    if "px" not in sub.columns:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    k = (sub.set_index("ts")["px"].resample("5min")
         .agg(open="first", high="max", low="min", close="last")
         .dropna(subset=["close"]))
    k["volume"] = float("nan")
    return k.reset_index()


def inspect(start: dt.date) -> None:
    s3 = _s3()
    for probe in (start, start + dt.timedelta(days=1), start + dt.timedelta(days=30)):
        raw = _fetch_day(s3, probe)
        if raw is not None and len(raw):
            print(f"=== asset_ctxs sample: {probe} ===")
            print("columns:", list(raw.columns))
            print(raw.head(8).to_string())
            print(f"\nrows in day: {len(raw):,} | distinct coins: "
                  f"{raw[_pick(raw.columns, COIN_CANDIDATES)].nunique()}")
            n_per_coin = len(raw) / max(raw[_pick(raw.columns, COIN_CANDIDATES)].nunique(), 1)
            print(f"~snapshots per coin per day: {n_per_coin:.0f}  "
                  "(>1 => intraday OI granularity; ~1 => daily only)")
            return
    print("No asset_ctxs files found near", start, "- check credentials / window.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true",
                    help="download one day, print schema + granularity, then stop")
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    a = ap.parse_args()

    start = dt.date.fromisoformat(a.start)
    end = dt.date.fromisoformat(a.end)

    if a.inspect:
        inspect(start)
        return

    coins = set(ASSETS["hyperliquid"])
    if all(dataset_exists(f"hyperliquid_{c}_oi") and dataset_exists(f"hyperliquid_{c}_funding")
           for c in coins):
        print("all hyperliquid OI + funding datasets exist — delete to re-pull")
        return

    s3 = _s3()
    frames = {c: [] for c in coins}
    missing, day = [], start
    while day <= end:
        raw = _fetch_day(s3, day)
        if raw is None:
            missing.append(day.isoformat())
        else:
            norm = _normalise(raw)
            for c in coins:
                sub = norm[norm["coin"] == c]
                if len(sub):
                    frames[c].append(sub.drop(columns="coin"))
        if day.day == 1:
            print(f"  ... {day} ({sum(len(f) for fs in frames.values() for f in fs):,} rows so far)")
        day += dt.timedelta(days=1)

    for c in coins:
        df = (pd.concat(frames[c], ignore_index=True).drop_duplicates("ts").sort_values("ts")
              if frames[c] else pd.DataFrame(columns=["ts", "oi", "px"]))
        oi_stem = f"hyperliquid_{c}_oi"
        if not dataset_exists(oi_stem):
            oi_df = df[[col for col in ["ts", "oi", "oi_value"] if col in df.columns]]
            save_df(oi_df, oi_stem)
            span = (df["ts"].min(), df["ts"].max()) if len(df) else ("EMPTY", "EMPTY")
            print(f"{oi_stem}: {len(oi_df):,} rows, {span[0]} .. {span[1]}")
        # price (5m OHLC from mid_px) — free, full history; for the liq event study.
        # Written unconditionally: the earlier API-pulled klines are empty (HL's
        # candle endpoint retains only recent history), so mid_px supersedes them.
        k = _klines_from_px(df)
        if len(k):
            save_df(k, f"hyperliquid_{c}_klines")
            print(f"hyperliquid_{c}_klines: {len(k):,} 5m bars (from mid_px)")
        # funding series — external validator for the classification (spec §6)
        f_stem = f"hyperliquid_{c}_funding"
        if not dataset_exists(f_stem) and "funding" in df.columns:
            f_df = df[["ts", "funding"]].dropna()
            save_df(f_df, f_stem)
            print(f"{f_stem}: {len(f_df):,} funding points")
    if missing:
        (DATA_DIR / "hyperliquid_asset_ctxs_missing_days.txt").write_text("\n".join(missing))
        print(f"({len(missing)} days missing from archive — logged)")


if __name__ == "__main__":
    main()
