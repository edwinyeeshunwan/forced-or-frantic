# Input data

The raw Hyperliquid input files are **not** included in this repository. Place them here before running `reanalysis/run_all.py`:

```
hyperliquid_{BTC,ETH}_liquidations.parquet   liquidation fills (Hydromancer Reservoir archive)
hyperliquid_{BTC,ETH}_oi.parquet             open-interest snapshots (Hyperliquid asset_ctxs S3 archive)
hyperliquid_{BTC,ETH}_klines.parquet         price bars built from asset-context snapshots
hyperliquid_{BTC,ETH}_funding.parquet
hyperliquid_{BTC,ETH}_adl.parquet
```

They were produced by `scripts/pull_hl_reservoir.py` and `scripts/pull_hl_asset_ctxs.py` (AWS S3 requester-pays; see `legacy/REPLICATION_v1.md`). The SHA-256 hash of every file used in the paper is recorded in `revision_v2/verification.json`, and the pipeline refuses to run on files that do not match.

A fresh download may not reproduce these hashes exactly: the original download removed rows that were identical on every retained field, and the archive keeps no record identifiers. See `reanalysis/DATA_LIMITATIONS.md`.

The three small `event*` files in this folder are outputs of the **v1** pipeline. They are used only to check that the legacy results are reproduced exactly.
