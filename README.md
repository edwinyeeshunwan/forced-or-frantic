# Open Interest Contraction and Price Recovery Around Liquidation Events

**Edwin Wan** · Independent researcher · Working paper v3, September 2026

📄 **[Read the paper (PDF)](Open_Interest_and_Price_Recovery_v3.pdf)**

> **Correction notice.** This repository previously hosted *"Forced or Frantic?"* (v1, July 2026). Its event construction contained look-ahead and measurement errors, and its headline results (162 events, a ~0.55pp size-controlled effect, p ≈ 10⁻⁴) are **superseded**. The study has been re-estimated under a correction protocol frozen before any corrected outcome was computed. See **[CORRECTIONS.md](CORRECTIONS.md)** for what changed and why. The original version is kept unchanged in [`legacy/`](legacy/) and at the [original v1 commit](https://github.com/edwinyeeshunwan/forced-or-frantic/tree/fe8e96ac2d22bc0fd40fd032f3075f2d47ec4f04).

## Question

Among liquidation-triggered stress onsets in BTC and ETH perpetual futures on Hyperliquid, do onsets with a large contemporaneous fall in open interest (OI) behave differently from onsets where OI changes little?

## Findings (exploratory)

134 onsets, 1 September – 31 December 2025: 30 in the contraction class, 27 in the limited-contraction class.

- **Deeper displacement** over the event window: difference in medians −1.04 log points × 100 (95% episode-bootstrap interval −1.44 to −0.46).
- **Lower price six hours later**: −1.17 (−2.02 to −0.30).
- **Slower recovery** after the window: 53% vs 22% not recovered after 22 hours (restricted-mean difference 373 minutes, 87 to 674).
- **Not supported:** a size-adjusted effect. With total liquidated notional held fixed, the class coefficient is small and its interval includes zero. Contraction events carry about four times the liquidated notional, so this sample cannot separate the two.
- The 24-hour difference is imprecise, and the reversion-index difference is fragile across the declared sensitivity analyses.

These are descriptive associations from one venue and a four-month event sample. Both groups are liquidation-triggered, and aggregate OI nets opening against closing, so the design does **not** identify forced versus voluntary flow or any causal mechanism.

## What is in this repository

```
Open_Interest_and_Price_Recovery_v3.pdf   the paper
CORRECTIONS.md                            what was wrong in v1 and how it was fixed
reanalysis/                               corrected pipeline (see reanalysis/README.md)
  protocol/                               frozen correction protocol, freeze hash, deviations
  src/  tests/                            code and 26 synthetic/integration tests
  outputs/                                every number in the paper, tables, audit, figures
  paper_v3/                               paper source (Markdown), Word, PDF, figures
  DATA_LIMITATIONS.md                     what the data cannot resolve
scripts/                                  original data-pull and legacy analysis scripts
revision_v2/verification.json             SHA-256 hashes of the input files + legacy benchmarks
data/                                     input files go here (see data/README.md)
legacy/                                   v1 paper and documents, unchanged, superseded
```

## Reproducing

1. Obtain the Hyperliquid input files and place them in `data/` (see [data/README.md](data/README.md)).
2. From `reanalysis/`:

```
pip install -r requirements.txt
python run_all.py        # about 2 minutes; verifies input hashes, runs tests, writes outputs/
python make_tables.py    # writes outputs/TABLES.md and outputs/results/key_numbers.json
```

`run_all.py` stops if any input hash differs from `revision_v2/verification.json`, or if the legacy benchmarks are not reproduced exactly. The full pipeline gave identical results in two environments with different Python, numpy and pandas versions.

## Data

Built entirely on free public data: Hyperliquid asset-context snapshots (open interest and mid-price) from the public S3 archive, and liquidation fills from the Hydromancer Reservoir archive. Known limitations, including missing record identifiers and rows removed during the original download, are documented in [reanalysis/DATA_LIMITATIONS.md](reanalysis/DATA_LIMITATIONS.md).

## Status

Exploratory pilot. Not peer reviewed and not prospectively validated. A follow-on design would test whether OI contraction adds **out-of-sample** predictive information about recovery beyond liquidation volume and the initial price move.

## Licence

MIT. See [LICENSE](LICENSE).
