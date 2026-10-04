# Reanalysis tables: legacy versus corrected

Generated from `run_all.py` outputs. Protocol SHA-256 `37fb3f285fbaaa79a20c8bac2ca93e0ba3f08a6df01154cd7492d05ae08377c8`. Bootstrap draws: 4,999 (episode) and 9,999 (wild cluster), seed 20260911. Tests: 26 passed, 0 failed. Environment: {'python': '3.11.15', 'platform': 'Linux-6.18.44-fc-v24-x86_64-with-glibc2.39', 'numpy': '2.4.4', 'pandas': '3.0.2', 'parquet_engine': 'fallback reader (libsnappy via ctypes)'}.

## 0 Legacy baseline reproduction

All legacy benchmarks reproduced: **True** (stored-table columns equal: True; OLS coefficients 0.005132523540804 and 0.005453804556877).

## 1 Provenance and missing-data audit

| Asset | Liquidation rows | Sell rows | Identifier columns retained | Rows dropped by legacy full-row dedup (at least) | Share of 5-min bins with no liquidation rows | Zero runs >= 12 h | Longest zero run (h) | OI 1-min grid points missing | OI off-grid rows | Price bars missing |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | 479170 | 349993 | none | 31,253 (6.1%) | 88.4% | 14 | 24.80 | 116 | 65 | 5 |
| ETH | 279455 | 213774 | none | 24,500 (8.1%) | 89.9% | 22 | 25.20 | 116 | 65 | 5 |

Every sell row closes a long position (`Close Long`, `Liquidated Cross Long`, `Liquidated Isolated Long`), and no sell row has a buy row with the same timestamp, price and size, so the partition does not contain both sides of the same fill. The retained index shows the legacy normaliser's `drop_duplicates()` removed rows that were identical on every retained field. Whether they were true duplicates or distinct fills cannot be determined without trade identifiers from the raw archive.

## 2 Event-count waterfall (0.99 trigger)

| stage | BTC_triggers | BTC_onsets | ETH_triggers | ETH_onsets | total_onsets |
|---|---:|---:|---:|---:|---:|
| 0 legacy (left-labelled bins, current-inclusive threshold, 7-day minimum) | 423 | 80 | 388 | 82 | 162 |
| 1 right-labelled completed bins | 423 | 80 | 388 | 82 | 162 |
| 2 + threshold from prior decision times only | 424 | 81 | 388 | 82 | 163 |
| 3 + full 30-day baseline (primary trigger rule) | 358 | 69 | 288 | 65 | 134 |
| 4 + measurement requirements (reference, window bars, OI coverage) |  | 69 |  | 65 | 134 |

Stage 0 reproduces legacy `detect_events` exactly for both assets. Stage 3 triggers equal the corrected module's triggers (independent implementation check in `corrected/waterfall_implementation_checks.json`).

## 3 Membership changes

| status | churn | deleverage | middle | (not in legacy) |
|---|---:|---:|---:|---:|
| dropped | 1 | 16 | 12 | 0 |
| new in corrected | 0 | 0 | 0 | 1 |
| same onset bin | 27 | 22 | 84 | 0 |

Reasons:

| status | exclusion | n |
|---|---:|---:|
| dropped | before full 30-day warm-up | 29 |
| new in corrected |  | 1 |
| same onset bin |  | 133 |

Class transitions for onsets present in both (rows legacy, columns corrected):

| legacy class | contraction | intermediate | limited |
|---|---:|---:|---:|
| churn | 0 | 3 | 24 |
| deleverage | 21 | 1 | 0 |
| middle | 9 | 73 | 2 |

## 4 Descriptive statistics by class: legacy and corrected

| Sample | Class | n | Median displacement x100 | Median 6-h change x100 | Median reversion | Recovery measure | Recovery value | Unrecovered / censored % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Legacy, all 162 | contraction | 38 | -2.10 | -1.37 | 0.35 | legacy recorded minutes (median) | 505.00 | 42.11 |
| Legacy, all 162 | limited | 28 | -1.26 | -0.25 | 0.81 | legacy recorded minutes (median) | 140.00 | 17.86 |
| Legacy, all 162 | intermediate | 96 | -1.66 | -0.70 | 0.50 | legacy recorded minutes (median) | 192.50 | 32.29 |
| Legacy, 133 onsets retained | contraction | 22 | -2.12 | -1.65 | 0.32 | legacy recorded minutes (median) | 657.50 | 45.45 |
| Legacy, 133 onsets retained | limited | 27 | -1.25 | -0.22 | 0.84 | legacy recorded minutes (median) | 135.00 | 18.52 |
| Legacy, 133 onsets retained | intermediate | 84 | -1.75 | -0.75 | 0.51 | legacy recorded minutes (median) | 170.00 | 33.33 |
| Corrected primary | contraction | 30 | -2.28 | -1.62 | 0.25 | post-window RMST to 22 h (min) | 821.50 | 53.33 |
| Corrected primary | limited | 27 | -1.25 | -0.45 | 0.73 | post-window RMST to 22 h (min) | 448.33 | 22.22 |
| Corrected primary | intermediate | 77 | -1.96 | -0.82 | 0.45 | post-window RMST to 22 h (min) | 580.19 | 35.06 |

Displacement and reversion definitions differ between legacy and corrected columns (Section 3 of the protocol). The recovery columns are different estimands and are not directly comparable.

## 5 Primary effects (corrected, contraction minus limited)

Contrast events: 30 contraction, 27 limited. 6-h episodes: G = 43 (mixed 4, largest 4); 24-h episodes: G = 26 (mixed 9, largest 6).

| Effect | Estimate | 95% CI | Rule-based reading | Details |
|---|---:|---:|---:|---:|
| E1 Displacement over event window: median difference (log pts x 100) | -1.04 | [-1.44, -0.46] | Supported (exploratory) | n = 30 vs 27; G = 43 |
| E2 Conditional |displacement|: OLS coefficient on contraction (x 100) | 0.95 | [0.21, 1.74] | Supported (exploratory) | WCR p = 0.010; CR1 95% CI [0.19, 1.71], p = 0.016; G = 43, G* = 21.6 |
| E3 6-h price change: median difference (log pts x 100) | -1.17 | [-2.02, -0.30] | Supported (exploratory) | n = 30 vs 27; G = 43 |
| E4 24-h price change: median difference (log pts x 100) | -1.09 | [-2.32, 0.59] | Directionally consistent, imprecise | n = 30 vs 27; G = 26 |
| E5 Reversion index (clipped): median difference | -0.47 | [-0.78, -0.02] | Supported (exploratory) | n = 30 vs 27; G = 43 |
| E6 Post-window recovery: RMST difference to 22 h (minutes) | 373.17 | [86.87, 673.59] | Supported (exploratory) | RMST 822 vs 448 min; KM unrecovered at tau 53% vs 22%; cluster-robust log-rank p = 0.017 (ordinary p = 0.012) |

## 6 Legacy definitions with the same dependence-aware inference (comparison)

Legacy 162-event table; contrast 38 vs 28; 6-h episodes G = 48. Legacy recovery is the post-trough intrabar crossing from t0 (RMST to 1,440 min).

| Effect | Estimate | 95% CI | Rule-based reading | Details |
|---|---:|---:|---:|---:|
| E1 Displacement over event window: median difference (log pts x 100) | -0.84 | [-1.51, -0.27] | Supported (exploratory) | n = 38 vs 28; G = 48 |
| E2 Conditional |displacement|: OLS coefficient on contraction (x 100) | 0.51 | [-0.15, 1.18] | Directionally consistent, imprecise | WCR p = 0.122; CR1 95% CI [-0.13, 1.16], p = 0.115; G = 48, G* = 22.2 |
| E3 6-h price change: median difference (log pts x 100) | -1.12 | [-1.97, -0.03] | Supported (exploratory) | n = 38 vs 28; G = 48 |
| E4 24-h price change: median difference (log pts x 100) | -1.01 | [-2.14, 1.14] | Directionally consistent, imprecise | n = 38 vs 28; G = 28 |
| E5 Reversion index (clipped): median difference | -0.46 | [-0.75, 0.15] | Directionally consistent, imprecise | n = 38 vs 28; G = 48 |
| E6 Post-window recovery: RMST difference to 22 h (minutes) | 340.92 | [43.11, 683.60] | Supported (exploratory) | RMST 766 vs 425 min; KM unrecovered at tau 42% vs 18%; cluster-robust log-rank p = 0.022 (ordinary p = 0.017) |

Legacy reported (historical, not revalidated): permutation p = 0.0108 (displacement), 0.0367 (reversion); log-rank p = 0.0166; regression dummy-shuffle p = 0.0533 (headline) and 0.0001 (0.95-trigger extension only).

## 7 Clustering sensitivity (S7): same estimates, different independent units

| clustering | G_short | G_short_mixed | G_long | E1_disp_diff_lo | E1_disp_diff_hi | E2_lo_wcr | E2_hi_wcr | E2_p_wcr | E2_Gstar | E3_p6h_diff_lo | E3_p6h_diff_hi | E5_rev_diff_lo | E5_rev_diff_hi | E6_lo | E6_hi | E6_p_logrank_robust |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| primary (6 h / 24 h episodes) | 43 | 4 | 26 | -1.44 | -0.46 | 0.21 | 1.74 | 0.01 | 21.60 | -2.02 | -0.30 | -0.78 | -0.02 | 86.87 | 673.59 | 0.02 |
| 24 h episodes for all | 26 | 9 | 26 | -1.63 | -0.54 | 0.24 | 1.80 | 0.00 | 13.19 | -1.91 | -0.43 | -0.78 | -0.11 | 86.87 | 673.59 | 0.02 |
| 6 h episodes for all | 43 | 4 | 43 | -1.44 | -0.46 | 0.21 | 1.74 | 0.01 | 21.60 | -2.02 | -0.30 | -0.78 | -0.02 | 35.67 | 683.71 | 0.03 |
| UTC calendar day | 41 | 5 | 41 | -1.48 | -0.46 | 0.22 | 1.75 | 0.01 | 22.84 | -2.04 | -0.30 | -0.78 | -0.03 | 14.01 | 706.11 | 0.03 |
| ISO calendar week | 16 | 9 | 16 | -1.67 | -0.54 | 0.28 | 1.82 | 0.00 | 8.58 | -1.91 | -0.43 | -0.77 | -0.13 | 131.21 | 656.57 | 0.01 |
| none: asset-event (reference only) | 57 | 0 | 57 | -1.75 | -0.49 | 0.25 | 1.66 | 0.01 | 43.39 | -2.03 | -0.31 | -0.78 | 0.01 | 66.48 | 650.99 | 0.01 |

## 8 All declared sensitivity analyses (S1-S13)

| spec | n (c/l) | G6 (mixed) | E1 | E2 (WCR CI; p) | E3 | E4 | E5 | E6 RMST |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Primary | 30/27 | 43 (4) | -1.04 [-1.44, -0.46] | 0.95 [0.21, 1.74]; p=0.010 | -1.17 [-2.02, -0.30] | -1.09 [-2.32, 0.59] | -0.47 [-0.78, -0.02] | 373 [87, 674] |
| S1 7-day minimum warm-up | 38/28 | 50 (3) | -0.96 [-1.63, -0.42] | 0.80 [0.16, 1.45]; p=0.014 | -0.95 [-1.97, -0.09] | -0.88 [-2.15, 0.78] | -0.37 [-0.73, 0.12] | 348 [92, 655] |
| S2 trigger quantile 0.95 | 59/105 | 94 (20) | -1.23 [-1.44, -0.75] | 0.98 [0.61, 1.33]; p=0.000 | -1.23 [-2.06, -0.70] | -1.28 [-1.95, -0.29] | -0.46 [-0.74, -0.22] | 359 [204, 523] |
| S3 legacy-aligned reference | 30/27 | 43 (4) | -0.99 [-1.44, -0.47] | 0.95 [0.23, 1.71]; p=0.007 | -1.21 [-1.93, -0.36] | -1.08 [-2.22, 0.57] | -0.50 [-0.78, -0.04] | 291 [-24, 639] |
| S4 fixed-cut classification | 58/27 | 55 (6) | -1.04 [-1.38, -0.50] | 1.13 [0.49, 1.78]; p=0.001 | -1.03 [-1.87, -0.17] | -0.95 [-2.01, 0.88] | -0.37 [-0.73, 0.08] | 300 [67, 544] |
| S5a intensity = total sell notional in W | 30/27 | 43 (4) | -1.04 [-1.44, -0.46] | 0.15 [-0.37, 0.70]; p=0.547 | -1.17 [-2.02, -0.30] | -1.09 [-2.32, 0.59] | -0.47 [-0.78, -0.02] | 373 [87, 674] |
| S5b no intensity control | 30/27 | 43 (4) | -1.04 [-1.44, -0.46] | 1.07 [0.42, 1.70]; p=0.002 | -1.17 [-2.02, -0.30] | -1.09 [-2.32, 0.59] | -0.47 [-0.78, -0.02] | 373 [87, 674] |
| S13a quiet period 60 min | 31/29 | 43 (5) | -1.04 [-2.17, -0.52] | 1.27 [0.12, 2.70]; p=0.026 | -1.30 [-2.09, -0.50] | -1.56 [-2.37, 0.53] | -0.46 [-0.77, -0.04] | 378 [74, 648] |
| S13b quiet period 180 min | 30/26 | 42 (4) | -1.05 [-1.70, -0.55] | 1.09 [0.29, 1.92]; p=0.006 | -1.43 [-2.17, -0.44] | -1.10 [-2.44, 0.58] | -0.52 [-0.85, -0.07] | 400 [121, 695] |
| S13c event window 1 h | 24/32 | 44 (3) | -1.09 [-1.52, -0.57] | 0.75 [0.14, 1.37]; p=0.016 | -0.89 [-1.93, -0.07] | -0.50 [-2.14, 0.72] | -0.31 [-0.78, 0.20] | 358 [86, 644] |
| S13d event window 3 h | 30/23 | 39 (5) | -1.37 [-1.84, -0.41] | 1.52 [0.11, 3.29]; p=0.028 | -1.34 [-2.04, -0.39] | -0.90 [-2.22, 0.92] | -0.37 [-0.71, 0.04] | 297 [9, 591] |
| S6a recovery: close-based after trough bar (from onset) | 30/27 | 43 (4) | -1.04 [-1.44, -0.46] | 0.95 [0.21, 1.74]; p=0.010 | -1.17 [-2.02, -0.30] | -1.09 [-2.32, 0.59] | -0.47 [-0.78, -0.02] | 407 [110, 730] |
| S6b recovery: next-bar high crossing after trough (from onset) | 30/27 | 43 (4) | -1.04 [-1.44, -0.46] | 0.95 [0.21, 1.74]; p=0.010 | -1.17 [-2.02, -0.30] | -1.09 [-2.32, 0.59] | -0.47 [-0.78, -0.02] | 411 [86, 756] |
| S8 zero runs >= 12 h treated as missing | 29/22 | 37 (4) | -0.99 [-1.54, -0.46] | 0.85 [0.10, 1.62]; p=0.026 | -0.99 [-2.01, -0.28] | -1.05 [-2.37, 1.04] | -0.48 [-0.78, 0.08] | 427 [124, 718] |
| S9 reinstated legacy-dropped rows (adjacent-row assumption) | 29/25 | 39 (4) | -0.89 [-1.40, -0.41] | 0.89 [0.15, 1.68]; p=0.014 | -1.30 [-2.11, -0.35] | -0.54 [-2.12, 1.30] | -0.46 [-0.78, 0.04] | 381 [85, 690] |
| S10 exclude 10-17 Oct 2025 | 24/24 | 37 (3) | -0.98 [-1.54, -0.45] | 0.74 [0.20, 1.28]; p=0.008 | -1.03 [-1.96, -0.26] | -1.24 [-2.38, 0.67] | -0.48 [-0.83, -0.01] | 399 [90, 728] |
| S11 BTC only | 17/15 | 30 (1) | -1.20 [-1.54, -0.48] | 0.81 [0.23, 1.41]; p=0.008 | -1.57 [-2.29, -0.48] | -0.96 [-2.24, 1.24] | -0.58 [-1.00, -0.10] | 440 [132, 766] |
| S11 ETH only | 13/12 | 23 (0) | -1.67 [-2.62, 0.49] | 1.11 [-0.68, 3.08]; p=0.248 | -0.72 [-2.58, 1.38] | -1.05 [-5.30, 1.82] | -0.22 [-0.62, 0.61] | 282 [-176, 846] |
| S12 continuous OI destroyed (all analysable events; E2 only) | 30/27 | 43 (4) | -1.04 [-1.44, -0.46] | 0.15 [0.08, 0.23]; p=0.000 | -1.17 [-2.02, -0.30] | -1.09 [-2.32, 0.59] | -0.47 [-0.78, -0.02] | 373 [87, 674] |

S12 row: E2 is the coefficient on OI destroyed in percentage points (all analysable events), not the class dummy. S6 rows change only the recovery estimand (durations from onset; tau = 1,440 min).

## 9 Post-hoc size diagnostic (added after seeing S5a; not used for specification choice)

Spearman correlation of OI destroyed with log onset intensity R(E0): 0.30; with log total sell notional in W: 0.42. Median total sell notional in W: contraction 62.7m USD vs limited 15.8m USD; median onset R(E0): 11.2m vs 9.3m USD.

Post-hoc regression (all analysable events, 6-h episodes): |displacement| x 100 on OI destroyed (pp), log total sell notional in W and ETH: OI coefficient 0.050 per pp, WCR 95% CI [-0.026, 0.124], p = 0.180. Reported for interpretation only.
