# H2 / H3 results — Hyperliquid liquidation-triggered events

Total events: **162**  (deleverage=38, churn=28, middle=96).  Window: 2025-08-10 03:25:00+00:00 .. 2025-12-31 16:25:00+00:00.

## Group summary

| klass      |   n |   median_peak |   median_transitory |   median_ttr_min |   pct_censored |
|:-----------|----:|--------------:|--------------------:|-----------------:|---------------:|
| deleverage |  38 |       -0.0210 |              0.3480 |         505.0000 |         0.4211 |
| churn      |  28 |       -0.0126 |              0.8118 |         140.0000 |         0.1786 |
| middle     |  96 |       -0.0166 |              0.4987 |         192.5000 |         0.3229 |

## H2 — dislocation & transitory share (deleverage vs churn)

- **Peak dislocation** (|log-return|): median deleverage−churn diff = 0.0084, permutation p = 0.0108  (n_deleverage=38, n_churn=28). Positive ⇒ deleverage dislocations are larger.
- **Transitory share**: median deleverage−churn diff = -0.4638, permutation p = 0.0367. Positive ⇒ deleverage more transitory.

## H3 — recovery speed (Kaplan–Meier + log-rank)

- Log-rank χ² = 5.733, p = 0.0166 (deleverage vs churn first-passage curves).
- KM figure: figures/km_recovery_by_class.png

## Reading guide / caveats

- Permutation tests are two-sided over 20,000 label shuffles; reported p is exact-style with the +1 correction.
- Small-N pilot: classes are modest, so treat p-values as indicative and lean on effect sizes + the KM curves. A clustered regression / Cox model (spec §6) is the next step once the sample is extended.
- 'Equal magnitude' (spec H2) is NOT yet matched on liquidation notional — a magnitude control is a planned refinement.
- Single venue (Hyperliquid); claims scoped accordingly.