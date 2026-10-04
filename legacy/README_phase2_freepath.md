# Phase 2 — the fully-free Hyperliquid path

Goal: run the *real* liquidation-based test (spec §3b/§3c) on Hyperliquid, the
one venue with complete, free liquidation data — **without buying Tardis ($300).**
The single number we're after is **N**, the event count, which tells us whether
this is a powered study or a cascade case-study.

## What's free, and where it comes from

| Layer | Source | Coverage | Cost |
|---|---|---|---|
| Open interest (ΔOI conditioning) | Official `s3://hyperliquid-archive/asset_ctxs` | Back to launch (2023) | requester-pays egress (cents) |
| Liquidations (the trigger) | Hydromancer **Reservoir** `s3://hydromancer-reservoir` | **~Aug 2025 →** | requester-pays egress (small) |
| Price (5m, for outcomes) | Reservoir 1s candles → resampled | ~Aug 2025 → | requester-pays egress (small) |

The binding limit is the **liquidation window: ~Aug–Dec 2025** (≈4–5 months
after a 30-day baseline warm-up). It *does* contain the October 2025 cascade.

## One-time setup: AWS credentials

These buckets are **requester-pays**, so you need your own AWS account and
credentials on this machine. The buckets are public to read — you only pay AWS's
transfer cost (cents for OI + fills; avoid pulling full L2 order-book history).

1. Create an AWS account (if you don't have one) and an IAM user with
   programmatic access (`AmazonS3ReadOnlyAccess` is enough).
2. Install the deps:
   ```
   pip install boto3 lz4 pyarrow pandas duckdb --break-system-packages
   ```
   (duckdb is used to read Reservoir's parquet — pyarrow rejects its Rust-written
   files with a "Repetition level histogram size mismatch" error.)
3. Configure credentials (either works):
   ```
   aws configure          # paste Access Key ID + Secret, region e.g. us-east-1
   # or export them:
   export AWS_ACCESS_KEY_ID=...
   export AWS_SECRET_ACCESS_KEY=...
   export AWS_DEFAULT_REGION=us-east-1
   ```

## Run order (always `--inspect` first — it's free-ish and catches schema drift)

```
cd paper/scripts

# 1. Confirm the archives' real schemas before bulk-pulling
python pull_hl_asset_ctxs.py --inspect
python pull_hl_reservoir.py  --inspect

# 2. If the printed columns look right, pull (else edit the *_CANDIDATES lists)
python pull_hl_asset_ctxs.py            # OI, full history
python pull_hl_reservoir.py             # liquidations + 5m price (Aug 2025+)

# 3. Build the liquidation event table — prints N
python build_event_table_liq.py
```

**Read off N.** Rough rule of thumb:
- **N ≳ 150** across BTC+ETH → enough for survival curves + class regressions →
  write it up as a study.
- **N ≈ 30–150** → honest pilot / cascade-anatomy paper; lean descriptive, wide
  confidence bands, lots of robustness.
- **N < 30** → do the free upgrade below before writing.

## The "free upgrade" — extend the sample back into 2024

If N is too thin, the same data exists further back; it's just not pre-packaged.
Hyperliquid's official **raw node fills** go back to launch:
`s3://hl-mainnet-node-data/node_fills_by_block` (newer) and
`s3://hl-mainnet-node-data/node_fills` / `node_trades` (older format).

Liquidations there aren't a tidy file — they're individual fills tagged as
liquidations, mixed into the full trade firehose. The upgrade is: download all
fills, keep only the liquidation-tagged ones, same as Reservoir does internally.

- **Payoff:** sample stretches from ~5 months back to ~18 months (into 2024,
  when HL first had real volume) → N likely jumps from dozens to hundreds.
- **Cost:** more code (a `pull_hl_node_fills.py`), much more data to download and
  process (the whole trade history, not a curated slice) → higher egress + run
  time; older data is in a different schema that needs its own parser.

When you're ready, ask and I'll write `pull_hl_node_fills.py` to the same
interface so `build_event_table_liq.py` runs on it unchanged.

## Honest scope reminders (for the paper's limitations section)

- **Single venue** → claims scoped to Hyperliquid; no cross-venue H3 contrast.
- **Short window** → the easy path leans on one major cascade (Oct 2025).
- **Schema not guaranteed** → both archives can change layout; the `--inspect`
  steps and the `*_CANDIDATES` lists are how we stay robust to that.
- **`side` semantics** → confirm which `side` value means "a long was
  liquidated" (forced sell) and narrow `LONG_LIQ_SIDE_TOKENS` in
  `build_event_table_liq.py` accordingly (see the note there).

Sources: Hyperliquid docs <https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data> ·
Hydromancer Reservoir <https://hydromancer.xyz/historical-data>
