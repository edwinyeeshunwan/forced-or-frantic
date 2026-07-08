# Forced or Frantic? — Replication Package

**Deleveraging Cascades and Price Dislocation on a Transparent Perpetual-Futures Venue**
Edwin Wan · Independent researcher · Working paper, 2026

📄 **[Read the paper (PDF)](Forced_or_Frantic_Working_Paper.pdf)**

## What this is

Liquidation cascades are widely blamed for crypto price crashes, but the public liquidation
feeds most studies rely on are **throttled** (one message per symbol per second since 2021)
and cannot separate *forced* selling from *frantic but voluntary* position-closing. This study
uses Hyperliquid's complete on-chain liquidation record to draw that distinction cleanly.

**Core finding:** forced-deleveraging events dislocate prices ~0.55 percentage points *more*
than voluntary-churn events of the same liquidation size (permutation p ≈ 10⁻⁴), robust across
a 16-specification pre-declared grid. The *mechanism* of a sell-off, not just its magnitude,
shapes its price impact.

- 162 liquidation-triggered events, BTC + ETH, Aug–Dec 2025 (includes the October 2025 cascade)
- ~760k liquidation fills, 530k+ price/open-interest observations
- Built entirely on **free, auditable public data** — no proprietary feeds
- Inference: permutation tests, Kaplan–Meier first-passage curves, magnitude-controlled regressions

## Reproducing the results

Every number, table, and figure regenerates from public data. See **[REPLICATION.md](REPLICATION.md)**
for the pipeline (data pull → event construction → analysis) and
**[00_Design_Spec.md](00_Design_Spec.md)** for the pre-registered design.

```
scripts/pull_hl_asset_ctxs.py     # open interest, price, funding (official HL archive)
scripts/pull_hl_reservoir.py      # complete liquidation fills (on-chain record)
scripts/build_event_table_liq.py  # events + deleverage/churn classification
scripts/analyze_liq_events.py     # headline tests (H2/H3)
scripts/robustness_liq.py         # magnitude controls + robustness grid
```

## License

Code: MIT (see LICENSE). Paper text and figures © Edwin Wan, all rights reserved.

## Contact

edwinyeeshunwan@outlook.com
