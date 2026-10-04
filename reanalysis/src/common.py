"""Paths, input loading and hashing for the reanalysis. No machine-specific paths:
everything is resolved relative to this file (override with REANALYSIS_PAPER_DIR)."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from parquet_fallback import engine_name, read_parquet

REANALYSIS = Path(__file__).resolve().parents[1]
PAPER = Path(os.environ.get("REANALYSIS_PAPER_DIR", REANALYSIS.parent)).resolve()
DATA = PAPER / "data"
SCRIPTS = PAPER / "scripts"
REV2 = PAPER / "revision_v2"
OUT = Path(os.environ.get("REANALYSIS_OUT_DIR", REANALYSIS / "outputs")).resolve()
COINS = ("BTC", "ETH")
KINDS = ("liquidations", "klines", "oi", "funding", "adl")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_hashes() -> dict:
    v = json.loads((REV2 / "verification.json").read_text())
    return v["input_sha256"]


def verify_inputs() -> dict:
    """Compare every supplied Hyperliquid input with the hashes recorded by the
    editorial verification. Raises if any differs."""
    exp = expected_hashes()
    rows = {}
    for rel, h in exp.items():
        p = PAPER / rel
        got = sha256(p) if p.exists() else None
        rows[rel] = {"expected": h, "actual": got, "match": got == h}
    bad = [k for k, r in rows.items() if not r["match"]]
    if bad:
        raise RuntimeError(f"input hash mismatch: {bad}")
    return rows


_CACHE: dict = {}


def load(coin: str, kind: str) -> pd.DataFrame:
    key = (coin, kind)
    if key not in _CACHE:
        d = read_parquet(DATA / f"hyperliquid_{coin}_{kind}.parquet")
        if "ts" in d.columns:
            d["ts"] = d["ts"].dt.as_unit("ns")   # engines differ (us vs ns); normalise
        _CACHE[key] = d
    return _CACHE[key].copy()


def price_bars(coin: str) -> pd.DataFrame:
    k = load(coin, "klines")
    return k.set_index("ts").sort_index()[["open", "high", "low", "close"]]


def oi_series(coin: str) -> pd.Series:
    o = load(coin, "oi")
    return o.set_index("ts").sort_index()["oi"]


def environment() -> dict:
    return {"python": sys.version.split()[0], "platform": platform.platform(),
            "numpy": np.__version__, "pandas": pd.__version__,
            "parquet_engine": engine_name()}


def write_json(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)

    def default(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if np.isnan(o) else float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, (pd.Timestamp,)):
            return o.isoformat()
        if isinstance(o, np.ndarray):
            return o.tolist()
        return str(o)
    path.write_text(json.dumps(obj, indent=2, default=default))
