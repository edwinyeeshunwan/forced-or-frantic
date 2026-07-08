# Forced or Frantic? — Phase 0 Design Specification (pre-registered)

**Status:** DRAFT v1 — decision points marked ⚠️ need Edwin's sign-off, then this file is FROZEN.
**Rule:** Everything in this file is fixed *before* estimation on the full dataset. Changes after freezing go in a "deviations" log with justification. This discipline is what makes H1's null result credible.

---

## 1. Scope

- **Assets:** BTC, ETH (USDT-margined perpetuals; native perp on Hyperliquid).
- **Venues:** Binance, Bybit, OKX, Hyperliquid.
- **Window:** 2023-06-01 → 2025-12-31 (UTC). Includes the Oct 2025 cascade.
- **Base sampling frequency:** 5-minute bars (matches Binance's free OI snapshot frequency; fine enough for event timing, coarse enough to be honest about microstructure noise).

## 2. Data layers

| Layer | Prototype (free) | Full version (Tardis) |
|---|---|---|
| Price (5m OHLCV) | exchange REST | Tardis |
| Open interest (5m) | Binance Vision metrics files; Bybit/OKX REST (depth varies — pullers report actual coverage) | Tardis |
| Funding | exchange REST (full history) | Tardis |
| Liquidations | NOT reliably free (throttled feeds) | Tardis (+ Hyperliquid on-chain as complete benchmark) |

**Consequence:** the prototype defines events from **OI + price only** (§3a). The full version defines events from **liquidation clusters** (§3b) and uses ΔOI as the conditioning variable. The prototype's job is to prove the pipeline and get a first look at H2 mechanics, not to produce final numbers.

## 3. Event definitions

### 3a. Prototype event (OI-based, free data)
A **candidate event** at venue v, asset a, time t when BOTH:
- 1-hour OI change ≤ trailing 30-day **1st percentile** of 1-hour OI changes, AND
- 1-hour return ≤ trailing 30-day **5th percentile** of 1-hour returns (downside events only in v1).

Events within the **merge window** of each other merge into one (event time = first trigger; magnitude = worst values in merged span).

**Merge window — calibrated outcome-blind in Phase 1:** plot the distribution of gaps between consecutive raw triggers (expected bimodal: within-cascade legs vs separate events) and set the window at the antimode, BEFORE computing any outcome metric. Working prior ≈ 120 min; the data decides. The gap histogram becomes Figure A2. Robustness: ±50% of the chosen window.

### 3b. Full event (liquidation-based, Tardis data)
A **candidate event** when rolling **15-minute long-liquidation notional** ≥ trailing 30-day **99th percentile** for that venue-asset. Merge within 120 min. ⚠️ *Decision: 99th vs 95th as headline (the other goes in robustness). Proposed: 99th headline.*

### 3c. The conditioning split (the paper's core)
For each event, compute **ΔOI** = (OI at event-window trough − OI at t−1h baseline) / OI baseline, over window [t−1h, t+2h].

- **Deleverage class:** headline rule = trailing **10th percentile** of event-window ΔOI (regime-adaptive, outcome-blind). The fixed-cut robustness value is calibrated in Phase 1 from the cross-sectional distribution of event ΔOI (look for the separation point between classes), BEFORE computing outcomes — working prior ≈ −2.5%, the data decides. Distribution plot becomes part of Figure A2.
- **Churn class:** ΔOI > −0.5% (flat or rising).
- **Middle band (−2.5%, −0.5%]:** excluded from headline, included in robustness as ordered tercile spec.

## 4. Outcome metrics (per event)

1. **Peak dislocation:** max adverse log-return from pre-event reference price P₀ (volume-weighted mid over [t−30m, t−5m]) within [t, t+2h].
2. **Time-to-recovery (first passage):** minutes until price first re-crosses P₀ × (1 − κ), κ = 10bp. Right-censored at 24h (survival treatment, not dropped).
3. **Permanent component:** log(P at t+6h / P₀) and log(P at t+24h / P₀).
4. **Transitory share:** 1 − (permanent₆ₕ / peak dislocation), bounded [0,1].

## 5. Hypotheses (fixed)

- **H1 (honest null):** Unconditional event magnitude (liquidation notional; prototype: OI-drop size) has no systematic relationship with permanent component. Expect β ≈ 0.
- **H2:** Interacting magnitude with the deleverage dummy: deleverage events show **larger peak dislocation** AND **larger transitory share** than churn events of equal magnitude.
- **H3:** Deleverage events recover faster (first-passage curves separate); effect is strongest on Hyperliquid (clean data); magnitude varies by session (Asia/EU/US by UTC bands) and funding regime (sign of funding at t).

## 6. Inference

- Event-level regressions; SEs clustered by **UTC-day × asset** (events cluster in time across venues).
- **Placebo bootstrap:** 1,000 draws of pseudo-event times matched on hour-of-day and volatility regime; null distributions for all headline stats.
- First-passage: Kaplan–Meier by class + log-rank test; Cox model with magnitude controls.
- **Robustness grid (declared now):** {95th, 99th} trigger × {percentile, fixed} ΔOI rule × {with/without middle band} × {BTC, ETH} × venue subsets × excluding Oct-2025 week.

## 7. What is explicitly OUT

- No trading-strategy claims, no P&L, no Sharpe, no entry/exit logic.
- No manipulation *detection* claims (that's the PhD's future work — Section 8 of the paper).
- No causal language beyond event-study conventions.

## 8. Known data traps (documented, not hidden)

1. **Throttled liquidation feeds** (Binance/Bybit: ≤1 event/symbol/sec since Apr 2021) → systematic undercount → Appendix A1 quantifies it by comparing against Hyperliquid's complete record during overlapping cascades.
2. **Binance free OI history** via REST is ~30 days only; full history comes from `data.binance.vision` daily metrics files (5-min snapshots) — the puller uses those.
3. **Aggregator figures (Coinglass)** are modelled on throttled feeds → cross-check only, never primary.
4. **Hyperliquid** launched its main growth phase mid-window → coverage starts later; report coverage honestly in T1.

## 9. Decision points needing sign-off ⚠️

| # | Decision | Proposed default |
|---|---|---|
| 1 | Headline liquidation trigger percentile | 99th |
| 2 | ΔOI split rule | trailing-percentile (10th); fixed-cut robustness value calibrated outcome-blind in Phase 1 (prior ≈ −2.5%) |
| 3 | Downside-only events in v1, or symmetric (short squeezes too)? | Downside-only headline (AGREED 2026-06-10); symmetric in robustness if time allows |
| 4 | Recovery threshold κ | 10bp |
| 5 | Event merge window | calibrated outcome-blind in Phase 1 from inter-trigger gap distribution (prior ≈ 120 min) |

Sign off (or amend) these five and the spec freezes.
