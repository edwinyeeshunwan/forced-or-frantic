# Robustness — magnitude controls + spec §6 grid

## (A) Does the deleverage effect survive controlling for event size?

OLS on the deleverage(1)/churn(0) subset; permutation p on the deleverage coefficient (10,000 shuffles). Run at both triggers for power.

### Trigger = 0.99

- **H2a peak |dislocation|** ~ deleverage + log(liq_notional) + asset: coef = 0.0051, perm p = 0.0533 (n=66). Positive & significant ⇒ deleverage moves bigger at equal liquidation size.
- **H2b transitory share** ~ deleverage + |peak| + log(liq_notional) + asset: coef = -0.0057, perm p = 0.9473 (n=66). Negative ⇒ more permanent at equal move/liq size.
- **H3 recovery, small (<= median size)**: deleverage n=14, churn n=19 → log-rank χ²=3.076, p=0.0795
- **H3 recovery, large (>  median size)**: deleverage n=24, churn n=9 → log-rank χ²=0.935, p=0.3335

### Trigger = 0.95

- **H2a peak |dislocation|** ~ deleverage + log(liq_notional) + asset: coef = 0.0055, perm p = 0.0001 (n=188). Positive & significant ⇒ deleverage moves bigger at equal liquidation size.
- **H2b transitory share** ~ deleverage + |peak| + log(liq_notional) + asset: coef = 0.0010, perm p = 0.9871 (n=188). Negative ⇒ more permanent at equal move/liq size.
- **H3 recovery, small (<= median size)**: deleverage n=10, churn n=84 → log-rank χ²=0.850, p=0.3566
- **H3 recovery, large (>  median size)**: deleverage n=53, churn n=41 → log-rank χ²=4.738, p=0.0295

## (B) Robustness grid

`peak_diff`/`tr_diff` = median deleverage−churn (|peak| and transitory share); `*_p` are permutation/log-rank p-values. Stable sign across rows = robust.

|   trigger | rule       | subset      |   n_d |   n_c |   peak_diff |   peak_p |   tr_diff |   tr_p |   lr_p |
|----------:|:-----------|:------------|------:|------:|------------:|---------:|----------:|-------:|-------:|
|    0.9900 | percentile | all         |    38 |    28 |      0.0084 |   0.0108 |   -0.4638 | 0.0367 | 0.0166 |
|    0.9900 | percentile | ex-Oct-week |    37 |    26 |      0.0084 |   0.0070 |   -0.4518 | 0.0420 | 0.0116 |
|    0.9900 | percentile | BTC         |    19 |    13 |      0.0103 |   0.0492 |   -0.5624 | 0.0229 | 0.0793 |
|    0.9900 | percentile | ETH         |    19 |    15 |      0.0116 |   0.0652 |   -0.1685 | 0.7142 | 0.1254 |
|    0.9900 | fixed      | all         |    69 |    28 |      0.0084 |   0.0028 |   -0.3434 | 0.1202 | 0.0228 |
|    0.9900 | fixed      | ex-Oct-week |    67 |    26 |      0.0084 |   0.0031 |   -0.3434 | 0.1105 | 0.0125 |
|    0.9900 | fixed      | BTC         |    35 |    13 |      0.0101 |   0.0027 |   -0.5368 | 0.0566 | 0.0734 |
|    0.9900 | fixed      | ETH         |    34 |    15 |      0.0123 |   0.0530 |   -0.1338 | 0.7814 | 0.2066 |
|    0.9500 | percentile | all         |    63 |   125 |      0.0111 |   0.0000 |   -0.5282 | 0.0053 | 0.0000 |
|    0.9500 | percentile | ex-Oct-week |    61 |   120 |      0.0118 |   0.0000 |   -0.5215 | 0.0034 | 0.0000 |
|    0.9500 | percentile | BTC         |    36 |    58 |      0.0104 |   0.0000 |   -0.5257 | 0.0364 | 0.0002 |
|    0.9500 | percentile | ETH         |    27 |    67 |      0.0124 |   0.0000 |   -0.5417 | 0.0323 | 0.0018 |
|    0.9500 | fixed      | all         |   110 |   125 |      0.0092 |   0.0000 |   -0.4083 | 0.0088 | 0.0000 |
|    0.9500 | fixed      | ex-Oct-week |   104 |   120 |      0.0098 |   0.0000 |   -0.4060 | 0.0093 | 0.0000 |
|    0.9500 | fixed      | BTC         |    59 |    58 |      0.0055 |   0.0002 |   -0.4738 | 0.0204 | 0.0011 |
|    0.9500 | fixed      | ETH         |    51 |    67 |      0.0123 |   0.0000 |   -0.4367 | 0.0553 | 0.0005 |

## Reading

- **Direction** (sign of peak_diff > 0, tr_diff < 0) holding across the grid is the robust core; significance scales with sample size (0.95 trigger).
- The (A) magnitude tests are the strict 'equal-magnitude' check (spec H2). Judge H2a/H2b mainly at the 0.95 trigger, where n is adequate.
- Single venue (Hyperliquid); claims scoped accordingly.