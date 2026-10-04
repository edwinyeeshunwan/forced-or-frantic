# Reanalysis of the Hyperliquid liquidation-event study

This folder contains the corrected empirical analysis described in `protocol/CORRECTION_PROTOCOL.md`, which was frozen on 11 September 2026 before any corrected outcome was computed. It holds the code, synthetic tests and generated outputs. Nothing outside this folder is modified: the original paper, scripts, data and `revision_v2/` stay as supplied.

## Layout

```
reanalysis/
  protocol/CORRECTION_PROTOCOL.md   frozen protocol (post-hoc correction, not a preregistration)
  protocol/PROTOCOL_FREEZE.json     SHA-256 and UTC freeze time
  protocol/DEVIATIONS.md            clarifications and labelled post-hoc additions
  src/common.py                     paths (relative to this folder), input hashing, loading
  src/parquet_fallback.py           minimal Parquet reader used only if pyarrow is absent
  src/legacy.py                     legacy reconstruction (loads original function definitions only)
  src/events.py                     corrected event clock, triggers, onsets, outcomes, classification
  src/episodes.py                   cross-asset market-episode and calendar clusters
  src/inference.py                  cluster bootstrap, CR1, wild cluster bootstrap, G*, KM, RMST, log-rank
  src/audit.py                      provenance and missing-data audit
  src/analysis.py                   effects, descriptive tables, legacy-to-corrected matching
  src/figures.py                    figures (matplotlib)
  tests/                            synthetic tests + legacy benchmark integration test
  run_all.py                        full pipeline
  make_tables.py                    formats outputs/TABLES.md and results/key_numbers.json
  outputs/                          generated (see below)
  paper_v3/                         updated paper: Markdown source, Word, PDF, figures, build_docx.js
  DATA_LIMITATIONS.md               what the local files cannot resolve
```

The paper is built from `paper_v3/Open_Interest_and_Price_Recovery_v3.md` with `node build_docx.js` (npm package `docx`), and the PDF is converted from the Word file with LibreOffice (`soffice --headless --convert-to pdf`). Every number in the paper comes from `outputs/`.

## How to run

From this folder (`paper/reanalysis/`), with Python 3.10 or newer:

```
pip install -r requirements.txt        # pyarrow and matplotlib recommended
python run_all.py                      # about 2 minutes; writes outputs/
python make_tables.py                  # writes outputs/TABLES.md and outputs/results/key_numbers.json
python tests/run_tests.py              # tests only (also run inside run_all.py)
```

The code reads `../data/` and `../revision_v2/verification.json` relative to this folder. Paths are never hard-coded; set `REANALYSIS_PAPER_DIR` or `REANALYSIS_OUT_DIR` to override. No network access is needed and no download script is run. `python run_all.py --quick` uses fewer bootstrap draws and is only for smoke testing. On machines that limit how long a single command may run, the same pipeline can be run in parts with identical results:

```
python run_all.py --part core
python run_all.py --part sensitivity --specs 0-8
python run_all.py --part sensitivity --specs 9-17
python run_all.py --part finish
```

`run_all.py` stops if any input hash differs from `revision_v2/verification.json`, or if the legacy benchmarks (162/38/28/96 and 425/63/125/237, the medians, the censoring shares and both OLS coefficients) are not reproduced exactly.

## Environments used

* Cloud workspace: Python 3.11.15, numpy 2.4.4, pandas 3.0.2, matplotlib 3.10.9. pyarrow could not be installed (no package access), so the fallback reader with libsnappy was used.
* Second machine (Linux VM): Python 3.10.12, numpy 2.2.6, pandas 2.3.3, matplotlib 3.10.9, no pyarrow. The full pipeline was rerun there, and `outputs/cross_environment_check.json` compares the numbers.

The fallback reader is validated three ways. It reproduces the legacy benchmark tables exactly. It matches the CSV reconstruction written earlier by `revision_v2/verify_tables.py`, which used pyarrow. Its pure-Python snappy decoder is tested against libsnappy.

## Outputs

| File | Contents |
|---|---|
| `outputs/input_verification.json` | input SHA-256 checks |
| `outputs/legacy/legacy_benchmark_check.json`, `legacy_rebuilt_*.csv` | legacy reproduction |
| `outputs/audit/audit.json`, `zero_runs_ge12h.csv` | provenance, identifiers, dropped rows, missingness |
| `outputs/corrected/events_primary.csv` | every corrected onset with all measures, flags and exclusion reasons |
| `outputs/corrected/event_count_waterfall.csv` | how each correction changes event counts |
| `outputs/corrected/membership_legacy_vs_corrected.csv`, `membership_summary.csv`, `class_transitions.csv` | membership changes and reasons |
| `outputs/results/primary_effects.json` | E1 to E6 with CIs, cluster counts, post-hoc size diagnostics |
| `outputs/results/legacy_definitions_clustered_effects.json` | legacy definitions evaluated with the same inference |
| `outputs/results/clustering_sensitivity.csv`, `sensitivity_grid.csv` | S7 and S1 to S13 |
| `outputs/results/fig_*.png` | figures used in the paper |
| `outputs/TABLES.md` | all legacy-versus-corrected tables in one document |
| `outputs/test_report.txt` | test results |
| `outputs/MANIFEST.json` | hashes of inputs, code, protocol and every output; environment; draws; seed |

## Note on figure hashes

Copying files to your computer re-encoded the PNG containers, so their byte-level SHA-256 differs from `MANIFEST.json` and `DELIVERY_MANIFEST.json`. Their pixel content was checked and is identical. `DELIVERY_MANIFEST.json` also lists a pixel hash for each PNG: SHA-256 of the RGBA array. Every non-image file matches byte for byte.

## Data limitations the local files cannot resolve

See `DATA_LIMITATIONS.md`.
