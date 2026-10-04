# Strengthening results (referee Q1–Q3 + economic significance)

## (1) Classification validation

- Median liquidation notional: deleverage = 3.67e+07, churn = 1.36e+07. Difference in log-notional (deleverage−churn) = 0.9968, permutation p = 0.0027 (n_d=38, n_c=28). Positive ⇒ deleverage-classified events carry more liquidation pressure, so the OI split is not arbitrary.
- Spearman(OI destroyed, liquidation notional) across all events = 0.315, permutation p = 0.0001 (n=162). Positive ⇒ deeper OI destruction coincides with heavier liquidation flow.

### (1b) External validation (independent of liquidation magnitude)

- **Auto-deleveraging (ADL) incidence**: deleverage events show ADL within [t, t+2h] at rate 0.000 (0/38) vs 0.000 (0/28) for churn; difference 0.000, permutation p = 1.0000. ADL is a separate forced-liquidation mechanism not used to build the classification.
- **Funding swing** (mean funding [t, t+2h] minus [t-1h, t]): median -0.000001 (deleverage) vs 0.000000 (churn), difference -0.000001, permutation p = 0.0420. A more negative deleverage swing matches the forced-long-liquidation prediction.
- **Post-event realized volatility** [t+2h, t+12h]: median 0.00186 (deleverage) vs 0.00166 (churn), difference 0.00020, permutation p = 0.6130. A price-based check external to the OI/liquidation-magnitude split.

## (2) Continuous measure (no buckets): outcomes on −ΔOI (OI destroyed)

- **H2a** |peak| ~ OI-destroyed + log(liq notional) + asset: coef = 0.0900, p = 0.0074 (n=162). Positive ⇒ more destruction, larger dislocation, at equal liquidation size.
- **H2b** transitory ~ OI-destroyed + |peak| + log(liq notional) + asset: coef = 0.4841, p = 0.6544 (n=162).
- **H3** Spearman(OI destroyed, time-to-recovery) = 0.176, p = 0.0277 (n=162).

## (3) Event-window sensitivity (headline deleverage vs churn, 0.99 trigger)

| param       |   value |   n_d |   n_c |   peak_diff |   peak_p |   tr_p |   lr_p |
|:------------|--------:|------:|------:|------------:|---------:|-------:|-------:|
| trough(h)   |       1 |    30 |    38 |      0.0085 |   0.0201 | 0.4409 | 0.2005 |
| trough(h)   |       2 |    38 |    28 |      0.0084 |   0.0108 | 0.0367 | 0.0166 |
| trough(h)   |       3 |    39 |    24 |      0.0084 |   0.0301 | 0.0181 | 0.0102 |
| recovery(h) |      12 |    38 |    28 |      0.0084 |   0.0108 | 0.0367 | 0.0289 |
| recovery(h) |      24 |    38 |    28 |      0.0084 |   0.0108 | 0.0367 | 0.0166 |
| recovery(h) |      48 |    38 |    28 |      0.0084 |   0.0108 | 0.0367 | 0.0464 |
| merge(min)  |      60 |    40 |    33 |      0.0093 |   0.0064 | 0.0324 | 0.0014 |
| merge(min)  |     120 |    38 |    28 |      0.0084 |   0.0108 | 0.0367 | 0.0166 |
| merge(min)  |     180 |    34 |    27 |      0.0094 |   0.0060 | 0.0067 | 0.0057 |

## (4) Economic significance of the ≈0.55pp size-controlled effect

- Median deleverage dislocation = 2.10%; the 0.55pp effect is 26% of it.
- BTC daily vol = 1.90%, ETH daily vol = 3.59%; the effect is ≈0.20 of a daily standard deviation.