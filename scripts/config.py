"""Shared configuration for the Forced-or-Frantic data pipeline."""
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

START = "2023-06-01"
END = "2025-12-31"

ASSETS = {
    "binance": ["BTCUSDT", "ETHUSDT"],
    "bybit": ["BTCUSDT", "ETHUSDT"],
    "okx": ["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
    "hyperliquid": ["BTC", "ETH"],
}

BAR = "5m"          # base sampling frequency (see 00_Design_Spec.md §1)
REQUEST_PAUSE = 0.25  # seconds between REST calls — stay well under rate limits

# ---- resilient HTTP: retry with backoff on timeouts/transient errors ----
def http_request(method: str, url: str, *, params=None, json=None,
                 timeout: int = 60, retries: int = 6, backoff: float = 3.0):
    """requests.request with automatic retry. Long pulls WILL hit occasional
    timeouts; retrying with growing pauses keeps an hours-long job alive."""
    import time as _time

    import requests as _rq

    for attempt in range(retries):
        try:
            return _rq.request(method, url, params=params, json=json, timeout=timeout)
        except _rq.exceptions.RequestException as e:
            if attempt == retries - 1:
                raise
            wait = backoff * (attempt + 1)
            print(f"  network hiccup ({type(e).__name__}), retry {attempt + 1}/{retries - 1} "
                  f"in {wait:.0f}s ...")
            _time.sleep(wait)


# ---- storage helpers: parquet if pyarrow/fastparquet available, else csv.gz ----
try:
    import pyarrow  # noqa: F401
    HAVE_PARQUET = True
except ImportError:
    try:
        import fastparquet  # noqa: F401
        HAVE_PARQUET = True
    except ImportError:
        HAVE_PARQUET = False

import pandas as _pd


def dataset_path(stem: str):
    """Existing file for this dataset stem, or preferred path for writing."""
    pq, csv = DATA_DIR / f"{stem}.parquet", DATA_DIR / f"{stem}.csv.gz"
    if pq.exists():
        return pq
    if csv.exists():
        return csv
    return pq if HAVE_PARQUET else csv


def dataset_exists(stem: str) -> bool:
    return (DATA_DIR / f"{stem}.parquet").exists() or (DATA_DIR / f"{stem}.csv.gz").exists()


def save_df(df: "_pd.DataFrame", stem: str) -> None:
    p = dataset_path(stem)
    if p.suffix == ".parquet":
        df.to_parquet(p)
    else:
        df.to_csv(p, index=False)


def load_df(stem: str) -> "_pd.DataFrame":
    p = dataset_path(stem)
    if not p.exists():
        raise FileNotFoundError(stem)
    if p.suffix == ".parquet":
        return _pd.read_parquet(p)
    df = _pd.read_csv(p)
    if "ts" in df.columns:
        df["ts"] = _pd.to_datetime(df["ts"], utc=True)
    return df


def list_dataset_stems() -> list:
    return sorted({f.name.replace(".parquet", "").replace(".csv.gz", "")
                   for f in DATA_DIR.iterdir()
                   if f.name.endswith((".parquet", ".csv.gz"))})
