# Correction protocol for the liquidation-event reanalysis

**Protocol date:** 11 September 2026 (frozen before any corrected outcome was computed)
**Applies to:** `paper/reanalysis/` (corrected pipeline), comparing against the legacy pipeline in `paper/scripts/`
**Status:** post-hoc correction protocol. It is **not a preregistration.** The legacy descriptive results (162 events, 38 / 28 contrast groups, median displacements, reversion shares, recovery times, legacy p values) were known when this protocol was written. What this protocol does guarantee is narrower: every definition, exclusion rule, effect measure, clustering choice and sensitivity analysis below was written down, and this file's SHA-256 hash recorded in `protocol/PROTOCOL_FREEZE.json`, before the corrected event outcomes (displacement, persistence, recovery) were computed. Before freezing, the author inspected only legacy outputs, input coverage and timing statistics (row counts, gaps, identifier retention, duplicate structure, the number of calendar clusters implied by legacy event times). Any later change is logged in `protocol/DEVIATIONS.md` with a reason and reported alongside the frozen specification.

## 1 Research question and estimand

**Question.** Among liquidation-triggered stress onsets for BTC and ETH perpetuals on Hyperliquid (August to December 2025), do onsets accompanied by a large contemporaneous contraction in open interest (OI) differ from onsets with limited OI contraction in (a) price displacement over the event window, (b) price level relative to the pre-event reference at fixed later horizons, and (c) how long price takes to recover after the event window?

**Estimand type.** Descriptive, contemporaneous association within one venue and sample period. The OI class is only known once the event window has closed (onset + 2 h), and it is measured over the same window as displacement. It therefore cannot be an ex-ante predictor of displacement. Both groups are triggered by liquidations. A limited-contraction group is not a voluntary-trading control: new positions can offset liquidated ones in net OI. No causal or forced-versus-voluntary interpretation is identified. Only outcomes measured after the event window closes (6 h and 24 h price change, post-window recovery) begin after the classification information is available. They are still descriptive conditional comparisons, not validated predictions.

**Units.** An asset-event (BTC or ETH onset). Statistical uncertainty is assessed with *market episodes*, not asset-events, as the independent units (Section 7).

## 2 Information-time conventions (applied everywhere)

| Series | Stored timestamp means | Treated as available at |
|---|---|---|
| Liquidation fill | fill time τ (ms) | τ |
| Liquidation 5-min bin | bins are closed on the left and labelled by their **right** edge E, containing fills with τ ∈ [E − 5 min, E) | E |
| Rolling 15-min liquidation notional R(E) | fills with τ ∈ [E − 15 min, E) | E |
| OI snapshot | asset-context snapshot time s (nominally 1-min grid; some off-grid seconds) | s |
| Price bar labelled L | aggregates 1-min context-price snapshots with timestamps in [L, L + 5 min); close = last snapshot (nominally L + 4 min) | **L + 5 min** (conservative bar end) |

OI is read *as of* a time g: the most recent snapshot with s ≤ g, used only if g − s ≤ 2 min; otherwise it is missing (no forward fill beyond that age).

## 3 Classification of changes relative to legacy

### A Implementation bugs fixed (the legacy rule did not do what its own definition described)

A1 **Left-labelled liquidation bins.** Legacy `resample('5min')` labels a bin by its left edge, so a trigger stamped t0 uses fills up to t0 + 5 min. Fixed by right-labelled, left-closed bins with availability at the bin end.
A2 **Current observation inside its own threshold.** Legacy `rolling('30D').quantile` includes the current rolling value. Fixed by computing the threshold over prior decision times only: R(E′) for E′ ∈ [E − 30 d, E).
A3 **Nominal 30-day window with a 7-day minimum.** The legacy threshold was computed from as little as 7 days (2,016 bins), so the trigger definition changed during the first month. Primary: a full 30-day baseline (8,640 bins) is required. The 7-day minimum is a declared sensitivity (S1).
A4 **Intensity using information outside the event window.** Legacy `liq_notional` is the maximum rolling notional over a chained span that can exceed two hours. Primary intensity is R(E0) at onset, known at E0. A window-bounded total is a sensitivity (S5).
A5 **Stale OI.** Legacy OI is forward-filled onto the price grid with `limit=12`. Replaced by the as-of rule in Section 2 with missingness flags.
A6 **Unbounded horizon lookups and follow-up.** Legacy horizon prices use the first close at or after the horizon with no maximum delay, and legacy recovery assigns 1,440 min whenever no crossing is found, even if less than 24 h is observed. Fixed: horizon prices use as-of bar closes no older than 10 min; recovery is censored at actual observed follow-up; a price gap longer than 15 min (more than two consecutive missing bars) ends follow-up.
A7 **Side mapping by permissive tokens.** Legacy accepts `side ∈ {sell, a, ask}` with a `direction` fallback. Replaced by `side == 'sell'`, with a hard check that every sell row's `direction` closes a long position (`Close Long`, `Liquidated Cross Long`, `Liquidated Isolated Long`).

### B Changed estimands (deliberate redefinitions, named differently from legacy)

B1 **Onset and window anchoring.** Onset E0 is the right edge of the first 5-min bin at which R crosses its prior-only threshold after at least 120 min without any trigger (strictly greater than 120 min since the previous trigger, as in legacy). The onset rule is legacy's chaining rule applied to corrected triggers. All measurements use fixed windows anchored at E0. Later triggers do not change the event's windows or intensity; they are recorded only as descriptive counts (`n_triggers_in_window`, `cascade_continues`).
B2 **Reference price.** Mean close of the six bars ending at E0 − 40, …, E0 − 15 min (bars labelled E0 − 45 … E0 − 20). The reference therefore ends before the first fill that can enter the triggering 15-min window. Legacy reference bars overlapped that window. A legacy-aligned reference is sensitivity S3.
B3 **Event window W = [E0 − 15 min, E0 + 120 min).** *Displacement* D = log(min bar low over bars labelled E0 − 15 … E0 + 115 / reference). *OI response* ΔOI = (min as-of OI over grid points E0 − 10 … E0 + 120 min − baseline)/baseline, where *baseline* = mean as-of OI over grid points E0 − 75 … E0 − 15 min. Both are known at A = E0 + 120 min, the *classification time*.
B4 **Horizon persistence.** P_h = log(close of the bar ending at E0 + h, as-of with ≤ 10 min age / reference), h ∈ {6 h, 24 h}.
B5 **Recovery (primary): post-window close-based recovery.** Recovery threshold = reference × (1 − κ), κ = 10 bp. Duration = time from A to the end of the first bar labelled ≥ A whose close is at or above the threshold. Follow-up ends at E0 + 24 h (22 h after A), at the end of observed data, or at a >15-min price gap, whichever comes first; events without recovery are right-censored there. This differs from legacy post-trough intrabar crossing measured from the trigger. It uses only bars whose closes are observed after classification and has no intrabar ordering ambiguity. Two alternative recovery estimands are sensitivities (S6).
B6 **Reversion index.** Same descriptive formula as legacy (1 − P_6h/D, clipped to [0, 1]) but using corrected components. Reported as a bounded descriptive index, not a decomposition into temporary and permanent impact.

### C Unchanged legacy choices retained for comparability

Trigger quantile 0.99 (0.95 as sensitivity S2); 15-min rolling notional; 120-min quiet rule; κ = 10 bp; 24-h horizon; classification rule: contraction if ΔOI ≤ expanding 10th percentile of the same asset's prior valid event ΔOI values (fixed −2.5 % until 20 prior values exist); limited contraction if ΔOI > −0.5 %; otherwise intermediate. Prior values are those of eligible corrected events only.

## 4 Inputs, provenance and missing data

Inputs are the ten supplied Hyperliquid parquet files (liquidations, OI, klines, funding, ADL for BTC and ETH). They are verified against the SHA-256 hashes in `revision_v2/verification.json` before any computation.

* **Liquidation coverage.** Coverage is taken as every 5-min bin from 00:00 UTC on the first fill's date to 00:00 UTC after the last fill's date. Within covered days, bins without rows are treated as zero in the primary analysis. This is an **assumption**: the local files carry no feed-coverage metadata. Sensitivity S8 treats zero runs of 12 h or longer (both sides of liquidations absent) as missing rather than zero.
* **Identifiers and duplicates.** The stored normalised liquidation files retain no trade, order, hash or user identifiers. The legacy normaliser applied full-row `drop_duplicates()` on (ts, coin, side, direction, px, sz, notional, is_liquidation), so distinct fills with identical retained fields may have been removed. The retained pandas index preserves the pre-deduplication positions. The audit counts and localises removed rows. No further deduplication is performed, and timestamp duplication is never treated as duplication. Sensitivity S9 reinstates removed rows under the assumption that each is a copy of the retained row immediately preceding its index gap. This is a bound-type check, not a correction.
* **Price and OI missingness.** Reference requires at least 4 of 6 bars. W requires at least 25 of 27 bars. OI baseline requires at least 11 of 13 as-of values, and the OI trough at least 24 of 27. Events failing any requirement are excluded from the affected analyses, with the reason recorded.
* **Sample window.** Onsets are eligible if the full baseline requirement is met (primary: 30 days of covered liquidation bins) and price and OI data cover at least W. Incomplete later follow-up is censored or set missing for that horizon, not excluded.

## 5 Groups and primary contrast

Contrast = OI-contraction class (`contraction`, legacy code `deleverage`) versus limited-contraction class (`limited`, legacy `churn`). The intermediate class is reported descriptively. Classes are computed per asset in chronological order.

## 6 Effect measures (all reported with uncertainty)

| ID | Measure | Effect reported |
|---|---|---|
| E1 | Displacement D (log points × 100) | difference in medians, contraction − limited |
| E2 | Conditional displacement association: OLS of \|D\| on contraction dummy + log R(E0) + ETH dummy, contrast events only | coefficient on the dummy (× 100) |
| E3 | 6-h persistence P_6h (× 100) | difference in medians |
| E4 | 24-h persistence P_24h (× 100) | difference in medians (events with an observed 24-h price only) |
| E5 | Reversion index (clipped) | difference in medians (descriptive) |
| E6 | Post-window recovery | KM curves; restricted mean time-to-recovery over the 22-h post-window follow-up (RMST difference, minutes); KM share still unrecovered at 22 h |

Legacy-comparable descriptive medians, recorded recovery and censoring shares are also reported.

## 7 Dependence-aware inference

**Units.** BTC and ETH onsets often coincide in time, and outcome windows overlap. Primary clusters are *market episodes*: single-linkage groups of eligible events (both assets, all classes) whose outcome intervals overlap, i.e., whose onsets are within H + 45 min of each other. H is matched to the outcome horizon:
* H = 6 h for E1, E2, E3 and E5 (windows up to E0 + 6 h);
* H = 24 h for E4 and E6.
Episodes are built on the full eligible event set, so intermediate events can link contrast events. This is conservative.

**Methods.**
* E1, E3, E4, E5: difference in medians, with a percentile CI from an episode (cluster) bootstrap, B = 4,999, seed 20260911. Bootstrap draws with an empty group are discarded and counted.
* E2: OLS coefficient; CR1 cluster-robust SE with a t(G − 1) reference distribution; wild cluster restricted (WCR) bootstrap p value with Webb six-point weights, B = 9,999; 95 % CI by inverting the WCR test on a grid. Carter–Schnepel–Steigerwald effective cluster count G* (ρ = 1) is reported.
* E6: KM by class; RMST difference to 1,320 min with an episode-bootstrap CI; a cluster-robust log-rank (Cox score) test with Lin–Wei sandwich variance summed within episodes. The ordinary log-rank is shown only for legacy comparison.
* Reported for every analysis: number of asset-events, G (episodes with at least one contrast event), G_mixed (episodes containing both classes), largest episode size.

**Assumptions stated, not assumed away.** Episode resampling treats episodes as independent draws from a stable process. Volatility-regime persistence can create dependence across episodes, and 21 calendar weeks bound how much of that can be addressed. Cluster-robust and bootstrap procedures are unreliable with few, unbalanced clusters or few clusters containing both groups (Cameron, Gelbach & Miller 2008; MacKinnon & Webb 2017). The classes are not randomly assigned, so no randomisation-based test is claimed, and legacy label permutation and dummy shuffling are not used. Intervals describe sampling uncertainty under the episode-independence assumption for a descriptive contrast.

## 8 Declared sensitivity analyses (all will be reported, whatever their results)

S1 7-day minimum warm-up (legacy) instead of full 30 days
S2 trigger quantile 0.95
S3 legacy-aligned reference (bars ending E0 − 30 … E0 − 5)
S4 fixed-cut classification (contraction ΔOI ≤ −2.5 %) instead of expanding percentile
S5 intensity control = total sell notional in W; and no intensity control
S6 recovery estimands: (a) close-based recovery from the bar after the trough bar in W, duration from E0; (b) conservative next-bar high crossing, i.e. first bar strictly after the trough bar with high ≥ threshold, duration from E0 to that bar's end
S7 clustering: other linkage horizon (6 h ↔ 24 h), UTC calendar day, ISO calendar week; asset-event (no clustering) shown for reference only
S8 zero-liquidation runs ≥ 12 h treated as missing (excluded from threshold baselines; events whose window W intersects such a run excluded)
S9 reinstated legacy-dropped duplicate rows (adjacent-row assumption)
S10 exclude 10–17 October 2025
S11 BTC only; ETH only
S12 continuous ΔOI (OI destroyed = −ΔOI) in the E2 regression, all eligible events
S13 quiet period 60 and 180 min; event window 1 h and 3 h (with OI trough and displacement windows moved together)

For S1–S13 the grid reports: event counts by class, E1, E2 and E3 with primary-clustering CIs (E2: CR1 and WCR p), E5, the E6 RMST difference, and G.

## 9 Interpretation rules (fixed now)

For each legacy headline direction (larger displacement, lower reversion and slower recovery for the contraction class):
* **Supported (exploratory):** the corrected primary point estimate has the legacy sign **and** the primary 95 % interval excludes zero.
* **Directionally consistent, imprecise:** same sign, interval includes zero.
* **Not supported:** opposite sign.
Sensitivity results are described as consistent or inconsistent with the primary result. They are never used to choose a headline specification. No result is described as confirmatory; prospective validation requires new data.

## 10 Deviations policy

Coding errors discovered after freezing are fixed and logged in `DEVIATIONS.md` with before and after values if outcomes had already been computed. Definitional changes after freezing are reported as deviations, and the frozen specification's results remain in the output.

## Methodological sources consulted

Abadie, Athey, Imbens & Wooldridge (2023, QJE) on when and why to cluster; Cameron, Gelbach & Miller (2008, REStat) and Cameron & Miller (2015, JHR) on few-cluster cluster-robust inference and the wild cluster bootstrap; MacKinnon & Webb (2017, JAE) on unbalanced cluster sizes; Webb (2023, CJE) on six-point weights; Carter, Schnepel & Steigerwald (2017, REStat) on effective cluster counts; Kolari & Pynnönen (2010, RFS) on cross-sectional correlation when events share dates; Kaplan & Meier (1958, JASA); Lin & Wei (1989, JASA) on robust variance for the Cox model; Royston & Parmar (2013, BMC Medical Research Methodology) on restricted mean survival time.
