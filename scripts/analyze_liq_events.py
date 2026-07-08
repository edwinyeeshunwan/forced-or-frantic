"""H2 / H3 analysis on the liquidation-triggered event table (Hyperliquid).

Tests, using the methods named in 00_Design_Spec.md §5-§6:
  H2  deleverage events show LARGER peak dislocation AND LARGER transitory share
      than churn events                       -> group medians + permutation tests
  H3  deleverage vs churn differ in recovery speed
      -> Kaplan-Meier first-passage curves (censored at 24h) + log-rank test

Classes (spec §3c): deleverage = ΔOI <= trailing 10th pctile; churn = ΔOI > -0.5%.
The middle band is reported for context but excluded from the headline contrast.

Small-N honesty: this is a borderline-powered pilot. We use nonparametric
permutation tests and KM/log-rank (not large-sample regression) precisely because
the deleverage/churn groups are modest. A clustered regression / Cox model is the
natural next step once the sample is extended (node-fills upgrade).

Inputs : data/event_table_liq.{parquet|csv.gz}  (build_event_table_liq.py)
Outputs: paper/H2_H3_results.md   and   paper/figures/km_recovery_by_class.png

Run:  python analyze_liq_events.py
"""
import math
import os

import numpy as np
import pandas as pd

from config import load_df


def _chi2_sf_1df(x: float) -> float:
    """Survival fn of chi-square with 1 dof, exact: P(X>x)=erfc(sqrt(x/2)).
    Avoids a scipy dependency."""
    if x is None or (isinstance(x, float) and math.isnan(x)) or x <= 0:
        return float("nan")
    return math.erfc(math.sqrt(x / 2.0))

PAPER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIGDIR = os.path.join(PAPER, "figures")
CENSOR_MIN = 24 * 60
N_PERM = 20000
SEED = 0


# ---------- statistics ----------
def perm_test(a, b, stat=np.median, n=N_PERM, seed=SEED):
    """Two-sided permutation p-value for stat(a) - stat(b)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 3 or len(b) < 3:
        return np.nan, np.nan, len(a), len(b)
    obs = stat(a) - stat(b)
    pool = np.concatenate([a, b])
    na = len(a)
    rng = np.random.default_rng(seed)
    diffs = np.empty(n)
    for i in range(n):
        rng.shuffle(pool)
        diffs[i] = stat(pool[:na]) - stat(pool[na:])
    p = (np.sum(np.abs(diffs) >= abs(obs)) + 1) / (n + 1)
    return obs, p, len(a), len(b)


def km_curve(durations, observed):
    """Kaplan-Meier survival S(t) = P(not yet recovered). Returns (times, S)."""
    d = np.asarray(durations, float)
    e = np.asarray(observed, bool)
    times, surv, S, at_risk = [], [], 1.0, len(d)
    for t in np.unique(d):
        at_t = d == t
        deaths = e[at_t].sum()
        if at_risk > 0 and deaths > 0:
            S *= 1 - deaths / at_risk
        times.append(t)
        surv.append(S)
        at_risk -= at_t.sum()
    return np.array([0.0] + times), np.array([1.0] + surv)


def logrank(d1, e1, d2, e2):
    """Standard two-group log-rank test. Returns (chi2, p)."""
    d = np.concatenate([d1, d2]).astype(float)
    e = np.concatenate([e1, e2]).astype(bool)
    g0 = np.concatenate([np.ones(len(d1)), np.zeros(len(d2))]).astype(bool)
    O1 = E1 = V = 0.0
    for t in np.unique(d[e]):
        at_risk = d >= t
        n = at_risk.sum()
        n1 = (g0 & at_risk).sum()
        died = (d == t) & e
        dd = died.sum()
        if n > 1:
            E1 += dd * n1 / n
            V += dd * (n1 / n) * (1 - n1 / n) * (n - dd) / (n - 1)
        O1 += (g0 & died).sum()
    if V <= 0:
        return np.nan, np.nan
    z2 = (O1 - E1) ** 2 / V
    return z2, _chi2_sf_1df(z2)


# ---------- reporting ----------
def group_summary(df):
    rows = []
    for k in ["deleverage", "churn", "middle"]:
        g = df[df["klass"] == k]
        if not len(g):
            continue
        rows.append(dict(
            klass=k, n=len(g),
            median_peak=g["peak_disloc"].median(),
            median_transitory=g["transitory_share"].median(),
            median_ttr_min=g["ttr_min"].median(),
            pct_censored=g["censored"].mean()))
    return pd.DataFrame(rows)


def main():
    df = load_df("event_table_liq")
    df = df.dropna(subset=["peak_disloc"]).copy()
    dele = df[df["klass"] == "deleverage"]
    churn = df[df["klass"] == "churn"]

    summ = group_summary(df)

    # H2a: peak dislocation (more negative = larger). Use |peak| so "bigger".
    peak_obs, peak_p, n_d, n_c = perm_test(dele["peak_disloc"].abs(),
                                           churn["peak_disloc"].abs())
    # H2b: transitory share (deleverage expected higher)
    tr_obs, tr_p, _, _ = perm_test(dele["transitory_share"], churn["transitory_share"])

    # H3: recovery speed — KM + log-rank (event = recovered = ~censored)
    lr_chi, lr_p = logrank(dele["ttr_min"].values, (~dele["censored"]).values,
                           churn["ttr_min"].values, (~churn["censored"]).values)

    # ---- figure ----
    fig_ok = True
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        os.makedirs(FIGDIR, exist_ok=True)
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for k, color in [("deleverage", "#c0392b"), ("churn", "#2980b9")]:
            g = df[df["klass"] == k]
            t, s = km_curve(g["ttr_min"].values, (~g["censored"]).values)
            ax.step(t / 60, s, where="post", color=color,
                    label=f"{k} (n={len(g)})", lw=2)
        ax.set_xlabel("hours since event")
        ax.set_ylabel("share still dislocated  (KM survival)")
        ax.set_title("Time-to-recovery by class — Hyperliquid liquidation events")
        ax.set_xlim(0, 24)
        ax.set_ylim(0, 1)
        ax.legend()
        ax.grid(alpha=0.3)
        figpath = os.path.join(FIGDIR, "km_recovery_by_class.png")
        fig.tight_layout()
        fig.savefig(figpath, dpi=150)
        plt.close(fig)
    except Exception as e:  # noqa: BLE001
        fig_ok = False
        figpath = f"(figure skipped: {e})"

    # ---- write results ----
    def fnum(x, d=4):
        return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"

    lines = [
        "# H2 / H3 results — Hyperliquid liquidation-triggered events",
        "",
        f"Total events: **{len(df)}**  (deleverage={len(dele)}, churn={len(churn)}, "
        f"middle={len(df[df['klass']=='middle'])}).  Window: "
        f"{df['t0'].min()} .. {df['t0'].max()}.",
        "",
        "## Group summary",
        "",
        summ.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## H2 — dislocation & transitory share (deleverage vs churn)",
        "",
        f"- **Peak dislocation** (|log-return|): median deleverage−churn diff = "
        f"{fnum(peak_obs)}, permutation p = {fnum(peak_p,4)}  "
        f"(n_deleverage={n_d}, n_churn={n_c}). "
        f"Positive ⇒ deleverage dislocations are larger.",
        f"- **Transitory share**: median deleverage−churn diff = {fnum(tr_obs)}, "
        f"permutation p = {fnum(tr_p,4)}. Positive ⇒ deleverage more transitory.",
        "",
        "## H3 — recovery speed (Kaplan–Meier + log-rank)",
        "",
        f"- Log-rank χ² = {fnum(lr_chi,3)}, p = {fnum(lr_p,4)} "
        "(deleverage vs churn first-passage curves).",
        f"- KM figure: {figpath if fig_ok else figpath}",
        "",
        "## Reading guide / caveats",
        "",
        "- Permutation tests are two-sided over 20,000 label shuffles; reported p "
        "is exact-style with the +1 correction.",
        "- Small-N pilot: classes are modest, so treat p-values as indicative and "
        "lean on effect sizes + the KM curves. A clustered regression / Cox model "
        "(spec §6) is the next step once the sample is extended.",
        "- 'Equal magnitude' (spec H2) is NOT yet matched on liquidation notional — "
        "a magnitude control is a planned refinement.",
        "- Single venue (Hyperliquid); claims scoped accordingly.",
    ]
    out = os.path.join(PAPER, "H2_H3_results.md")
    with open(out, "w") as f:
        f.write("\n".join(lines))

    # ---- console ----
    print(summ.to_string(index=False))
    print()
    print(f"H2a peak dislocation: deleverage−churn |peak| median diff={fnum(peak_obs)}, "
          f"perm p={fnum(peak_p,4)}")
    print(f"H2b transitory share: diff={fnum(tr_obs)}, perm p={fnum(tr_p,4)}")
    print(f"H3  recovery log-rank: chi2={fnum(lr_chi,3)}, p={fnum(lr_p,4)}")
    print(f"\nwrote {out}")
    if fig_ok:
        print(f"wrote {figpath}")


if __name__ == "__main__":
    main()
