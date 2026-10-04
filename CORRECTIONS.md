# Corrections to v1 ("Forced or Frantic?", July 2026)

Version 1 of this study was posted here in July 2026. A later audit of the code found errors in how events were constructed and measured. Version 3 (September 2026) re-estimates the study after fixing them. The original paper and documents are kept unchanged in [`legacy/`](legacy/) and in the `v1-superseded` release.

## What was wrong

**Look-ahead in the event clock**
- Five-minute bins were labelled by their left edge, so a trigger stamped at time t used liquidations up to t + 5 minutes.
- Each bin's own value was included in the percentile threshold it was compared against.
- The trigger threshold was accepted after only seven days of history, not a full 30-day baseline.

**Measurement**
- Event intensity was the maximum over chains of merged triggers that could run for up to 455 minutes, so event windows were not fixed.
- Open interest could be read from stale snapshots.
- The intrabar recovery measure was ambiguous.

**Inference**
- BTC and ETH events that overlap in time were treated as independent observations instead of as shared market episodes.
- The permutation test shuffled the class label without preserving its relationship to covariates or market episodes.
- The headline p ≈ 10⁻⁴ came from the looser 95th-percentile trigger, not from the 162-event headline design (where the size-controlled result was p ≈ 0.053).

**Interpretation**
- v1 described the two classes as "forced deleveraging" and "voluntary churn". Both groups are liquidation-triggered, and net OI change does not reveal why positions closed, so that distinction is not identified.
- v1 described its design as pre-registered. It was not. The v3 protocol is a post-hoc correction, written after the v1 results were known, and is labelled as such.

## How v3 differs

- Completed, right-labelled bins; thresholds built only from strictly earlier observations over a full 30-day baseline.
- Fixed measurement windows anchored at each onset; later triggers change nothing.
- OI read with an explicit two-minute staleness limit.
- Recovery measured from bar closes after the window and censored at the follow-up actually observed.
- Uncertainty computed over cross-asset market episodes (episode bootstrap, cluster-robust and wild cluster bootstrap inference).
- A correction protocol frozen and hashed on 11 September 2026 before any corrected outcome was computed, with all deviations recorded in `reanalysis/protocol/DEVIATIONS.md`.
- 26 automated tests covering timing, thresholds, windows, staleness, missing data and shared episodes.

## Effect on results

| | v1 | v3 |
|---|---|---|
| Events | 162 (Aug–Dec 2025) | 134 (Sep–Dec 2025); the full 30-day baseline removes August |
| Displacement contrast | larger for "deleverage" events | survives: −1.04 (−1.44 to −0.46) |
| Slower recovery | reported | survives: 53% vs 22% unrecovered at 22h |
| Size-controlled effect | ~0.55pp, p ≈ 10⁻⁴ | **not supported**: interval includes zero once liquidation volume is held fixed |
| Framing | forced vs voluntary flow | net OI response within liquidation-triggered events; descriptive only |
