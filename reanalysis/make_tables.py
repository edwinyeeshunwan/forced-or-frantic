"""Build outputs/TABLES.md (legacy-versus-corrected tables) and outputs/results/key_numbers.json
from the files written by run_all.py. Pure formatting: no estimation happens here."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from common import OUT, environment, sha256  # noqa: E402

LEGACY_SIGN = {"E1_disp": -1, "E2_reg": +1, "E3_p6h": -1, "E4_p24h": -1, "E5_reversion": -1, "E6_rmst": +1}
LABEL = {"E1_disp": "E1 Displacement over event window: median difference (log pts x 100)",
         "E2_reg": "E2 Conditional |displacement|: OLS coefficient on contraction (x 100)",
         "E3_p6h": "E3 6-h price change: median difference (log pts x 100)",
         "E4_p24h": "E4 24-h price change: median difference (log pts x 100)",
         "E5_reversion": "E5 Reversion index (clipped): median difference",
         "E6_rmst": "E6 Post-window recovery: RMST difference to 22 h (minutes)"}


def verdict(key, est, lo, hi):
    s = LEGACY_SIGN[key]
    if not np.isfinite(est):
        return "n/a"
    if np.sign(est) != s:
        return "Not supported (opposite sign)"
    if (lo > 0 and s > 0) or (hi < 0 and s < 0):
        return "Supported (exploratory)"
    return "Directionally consistent, imprecise"


def f(x, d=2):
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{d}f}"


def md(df, floatfmt=2):
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" if i == 0 else "---:" for i in range(len(cols))) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(f(v, floatfmt) if isinstance(v, (float, np.floating)) else str(v) for v in r) + " |")
    return "\n".join(out)


def effect_rows(eff):
    rows = []
    for k in ("E1_disp", "E2_reg", "E3_p6h", "E4_p24h", "E5_reversion", "E6_rmst"):
        e = eff.get(k)
        if e is None:
            continue
        if k == "E2_reg":
            est, lo, hi = e["coef"], e["lo_wcr"], e["hi_wcr"]
            extra = f"WCR p = {e['p_wcr']:.3f}; CR1 95% CI [{e['lo_cr1']:.2f}, {e['hi_cr1']:.2f}], p = {e['p_cr1']:.3f}; G = {e['G']}, G* = {e['G_star']:.1f}"
        elif k == "E6_rmst":
            est, lo, hi = e["est"], e["lo"], e["hi"]
            lr = eff["E6_logrank"]
            extra = (f"RMST {e['rmst1']:.0f} vs {e['rmst0']:.0f} min; KM unrecovered at tau {100*e['S1_tau']:.0f}% vs "
                     f"{100*e['S0_tau']:.0f}%; cluster-robust log-rank p = {lr['p_robust']:.3f} (ordinary p = {lr['p']:.3f})")
        else:
            est, lo, hi = e["est"], e["lo"], e["hi"]
            extra = f"n = {e['n1']} vs {e['n0']}; G = {e['G']}"
        rows.append({"Effect": LABEL[k], "Estimate": est, "95% CI": f"[{lo:.2f}, {hi:.2f}]",
                     "Rule-based reading": verdict(k, est, lo, hi), "Details": extra})
    return pd.DataFrame(rows)


def main():
    R = OUT / "results"
    C = OUT / "corrected"
    aud = json.loads((OUT / "audit" / "audit.json").read_text())
    eff = json.loads((R / "primary_effects.json").read_text())
    effL = json.loads((R / "legacy_definitions_clustered_effects.json").read_text())
    grid = pd.read_csv(R / "sensitivity_grid.csv")
    clus = pd.read_csv(R / "clustering_sensitivity.csv")
    wf = pd.read_csv(C / "event_count_waterfall.csv")
    for col in wf.columns[1:]:
        wf[col] = wf[col].astype("Int64").astype(str).replace("<NA>", "")
    mem = pd.read_csv(C / "membership_legacy_vs_corrected.csv")
    trans = pd.read_csv(C / "class_transitions.csv", index_col=0)
    desc = pd.read_csv(R / "descriptive_primary.csv")
    leg = pd.read_csv(OUT / "legacy" / "legacy_rebuilt_99.csv", parse_dates=["t0"])
    chk = json.loads((OUT / "legacy" / "legacy_benchmark_check.json").read_text())
    rep = (OUT / "test_report.txt").read_text().strip().splitlines()[-1] if (OUT / "test_report.txt").exists() else "tests not run"
    prot = sha256(HERE / "protocol" / "CORRECTION_PROTOCOL.md")

    L = []
    L += ["# Reanalysis tables: legacy versus corrected", "",
          f"Generated from `run_all.py` outputs. Protocol SHA-256 `{prot}`. Bootstrap draws: 4,999 (episode) and 9,999 (wild cluster), "
          f"seed 20260911. Tests: {rep}. Environment: {environment()}.", ""]
    L += ["## 0 Legacy baseline reproduction", "",
          f"All legacy benchmarks reproduced: **{chk['all_benchmarks_reproduced']}** "
          f"(stored-table columns equal: {all(chk['stored_table_column_equality'].values())}; "
          f"OLS coefficients {chk['ols_coefficients']['0.99']['coef']:.15f} and {chk['ols_coefficients']['0.95']['coef']:.15f}).", ""]
    # T1 provenance
    rows = []
    for c, a in aud.items():
        rows.append({"Asset": c, "Liquidation rows": a["rows"], "Sell rows": a["sell_rows"],
                     "Identifier columns retained": ", ".join(a["identifier_columns_retained"]) or "none",
                     "Rows dropped by legacy full-row dedup (at least)": f"{a['rows_dropped_by_legacy_dedup_at_least']:,} ({100*a['dropped_share_at_least']:.1f}%)",
                     "Share of 5-min bins with no liquidation rows": f"{100*a['share_5min_bins_without_any_liquidation']:.1f}%",
                     "Zero runs >= 12 h": a["zero_runs_ge_12h"], "Longest zero run (h)": round(a["longest_zero_run_h"], 1),
                     "OI 1-min grid points missing": a["oi_grid_points_missing"], "OI off-grid rows": a["oi_offgrid_rows"],
                     "Price bars missing": a["klines_grid_points_missing"]})
    L += ["## 1 Provenance and missing-data audit", "", md(pd.DataFrame(rows)), "",
          "Every sell row closes a long position (`Close Long`, `Liquidated Cross Long`, `Liquidated Isolated Long`), and no sell row "
          "has a buy row with the same timestamp, price and size, so the partition does not contain both sides of the same fill. "
          "The retained index shows the legacy normaliser's `drop_duplicates()` removed rows that were identical on every retained field. Whether they were "
          "true duplicates or distinct fills cannot be determined without trade identifiers from the raw archive.", ""]
    # T2 waterfall
    L += ["## 2 Event-count waterfall (0.99 trigger)", "", md(wf.fillna("")), "",
          "Stage 0 reproduces legacy `detect_events` exactly for both assets. Stage 3 triggers equal the corrected module's triggers "
          "(independent implementation check in `corrected/waterfall_implementation_checks.json`).", ""]
    # T3 membership
    ms = mem.groupby(["status", "legacy_class"], dropna=False).size().unstack(fill_value=0)
    ms.columns = ["(not in legacy)" if str(c) == "nan" else str(c) for c in ms.columns]
    ms = ms.reset_index().rename(columns={"legacy_class": "legacy class"})
    ex = mem.groupby(["status", "exclusion"], dropna=False).size().reset_index(name="n").fillna("")
    L += ["## 3 Membership changes", "", md(ms), "", "Reasons:", "", md(ex), "",
          "Class transitions for onsets present in both (rows legacy, columns corrected):", "",
          md(trans.reset_index().rename(columns={"legacy_class": "legacy class"})), ""]
    # T4 descriptive comparison
    def legacy_desc(d, name):
        out = []
        for k, lab in (("deleverage", "contraction"), ("churn", "limited"), ("middle", "intermediate")):
            g = d[d.klass == k]
            out.append({"Sample": name, "Class": lab, "n": len(g), "Median displacement x100": 100 * g.peak_disloc.median(),
                        "Median 6-h change x100": 100 * g.perm_6h.median(), "Median reversion": g.transitory_share.median(),
                        "Recovery measure": "legacy recorded minutes (median)", "Recovery value": g.ttr_min.median(),
                        "Unrecovered / censored %": 100 * g.censored.mean()})
        return out
    matched = mem[mem.status == "same onset bin"]
    legm = leg.merge(matched[["symbol", "legacy_t0"]].assign(legacy_t0=pd.to_datetime(matched["legacy_t0"], utc=True)),
                     left_on=["symbol", "t0"], right_on=["symbol", "legacy_t0"])
    rows = legacy_desc(leg, "Legacy, all 162") + legacy_desc(legm, f"Legacy, {len(legm)} onsets retained")
    for _, r in desc.iterrows():
        rows.append({"Sample": "Corrected primary", "Class": r["class"], "n": int(r["n"]),
                     "Median displacement x100": r["median_disp_x100"], "Median 6-h change x100": r["median_p6h_x100"],
                     "Median reversion": r["median_reversion"], "Recovery measure": "post-window RMST to 22 h (min)",
                     "Recovery value": r["rmst_min"], "Unrecovered / censored %": 100 * r["km_share_unrecovered_at_tau"]})
    L += ["## 4 Descriptive statistics by class: legacy and corrected", "", md(pd.DataFrame(rows)), "",
          "Displacement and reversion definitions differ between legacy and corrected columns (Section 3 of the protocol). "
          "The recovery columns are different estimands and are not directly comparable.", ""]
    # T5 primary effects
    L += ["## 5 Primary effects (corrected, contraction minus limited)", "",
          f"Contrast events: {eff['n_contraction']} contraction, {eff['n_limited']} limited. "
          f"6-h episodes: G = {eff['clusters_short']['G']} (mixed {eff['clusters_short']['G_mixed']}, largest {eff['clusters_short']['max_size']}); "
          f"24-h episodes: G = {eff['clusters_long']['G']} (mixed {eff['clusters_long']['G_mixed']}, largest {eff['clusters_long']['max_size']}).", "",
          md(effect_rows(eff)), ""]
    L += ["## 6 Legacy definitions with the same dependence-aware inference (comparison)", "",
          f"Legacy 162-event table; contrast {effL['n_contraction']} vs {effL['n_limited']}; 6-h episodes G = {effL['clusters_short']['G']}. "
          "Legacy recovery is the post-trough intrabar crossing from t0 (RMST to 1,440 min).", "",
          md(effect_rows(effL)), "",
          "Legacy reported (historical, not revalidated): permutation p = 0.0108 (displacement), 0.0367 (reversion); log-rank p = 0.0166; "
          "regression dummy-shuffle p = 0.0533 (headline) and 0.0001 (0.95-trigger extension only).", ""]
    # T7 clustering
    cc = clus[["clustering", "G_short", "G_short_mixed", "G_long", "E1_disp_diff_lo", "E1_disp_diff_hi", "E2_lo_wcr", "E2_hi_wcr",
               "E2_p_wcr", "E2_Gstar", "E3_p6h_diff_lo", "E3_p6h_diff_hi", "E5_rev_diff_lo", "E5_rev_diff_hi", "E6_lo", "E6_hi",
               "E6_p_logrank_robust"]].copy()
    L += ["## 7 Clustering sensitivity (S7): same estimates, different independent units", "", md(cc), ""]
    # T8 grid
    gg = grid.copy()
    for k, cols in (("E1", ("E1_disp_diff", "E1_disp_diff_lo", "E1_disp_diff_hi")),
                    ("E3", ("E3_p6h_diff", "E3_p6h_diff_lo", "E3_p6h_diff_hi")),
                    ("E4", ("E4_p24h_diff", "E4_p24h_diff_lo", "E4_p24h_diff_hi")),
                    ("E5", ("E5_rev_diff", "E5_rev_diff_lo", "E5_rev_diff_hi")),
                    ("E6 RMST", ("E6_rmst_diff_min", "E6_lo", "E6_hi"))):
        d = 0 if k == "E6 RMST" else 2
        gg[k] = [f"{a:.{d}f} [{b:.{d}f}, {c:.{d}f}]" if np.isfinite(a) else "n/a" for a, b, c in zip(gg[cols[0]], gg[cols[1]], gg[cols[2]])]
    gg["E2 (WCR CI; p)"] = [f"{a:.2f} [{b:.2f}, {c:.2f}]; p={p:.3f}" for a, b, c, p in zip(gg.E2_coef, gg.E2_lo_wcr, gg.E2_hi_wcr, gg.E2_p_wcr)]
    gg["n (c/l)"] = [f"{int(a)}/{int(b)}" for a, b in zip(gg.n_contraction, gg.n_limited)]
    gg["G6 (mixed)"] = [f"{int(a)} ({int(b)})" for a, b in zip(gg.G_short, gg.G_short_mixed)]
    L += ["## 8 All declared sensitivity analyses (S1-S13)", "",
          md(gg[["spec", "n (c/l)", "G6 (mixed)", "E1", "E2 (WCR CI; p)", "E3", "E4", "E5", "E6 RMST"]]), "",
          "S12 row: E2 is the coefficient on OI destroyed in percentage points (all analysable events), not the class dummy. "
          "S6 rows change only the recovery estimand (durations from onset; tau = 1,440 min).", ""]
    sd = eff["size_diagnostics_posthoc"]
    L += ["## 9 Post-hoc size diagnostic (added after seeing S5a; not used for specification choice)", "",
          f"Spearman correlation of OI destroyed with log onset intensity R(E0): {sd['spearman_OI_destroyed_vs_log_R_onset']:.2f}; "
          f"with log total sell notional in W: {sd['spearman_OI_destroyed_vs_log_notional_W']:.2f}. "
          f"Median total sell notional in W: contraction {sd['median_notional_W_musd_contraction']:.1f}m USD vs limited "
          f"{sd['median_notional_W_musd_limited']:.1f}m USD; median onset R(E0): {sd['median_R_onset_musd_contraction']:.1f}m vs "
          f"{sd['median_R_onset_musd_limited']:.1f}m USD.", "",
          "Post-hoc regression (all analysable events, 6-h episodes): |displacement| x 100 on OI destroyed (pp), log total sell "
          f"notional in W and ETH: OI coefficient {sd['posthoc_continuous_OI_with_window_notional']['coef']:.3f} per pp, WCR 95% CI "
          f"[{sd['posthoc_continuous_OI_with_window_notional']['lo_wcr']:.3f}, {sd['posthoc_continuous_OI_with_window_notional']['hi_wcr']:.3f}], "
          f"p = {sd['posthoc_continuous_OI_with_window_notional']['p_wcr']:.3f}. Reported for interpretation only.", ""]
    (OUT / "TABLES.md").write_text("\n".join(L))
    key = {"primary": eff, "legacy_clustered": effL, "grid": grid.to_dict("records"), "clustering": clus.to_dict("records"),
           "waterfall": wf.to_dict("records"), "descriptive": desc.to_dict("records"),
           "verdicts": {k: verdict(k, *( (eff[k]["coef"], eff[k]["lo_wcr"], eff[k]["hi_wcr"]) if k == "E2_reg" else (eff[k]["est"], eff[k]["lo"], eff[k]["hi"])))
                        for k in LEGACY_SIGN}}
    (R / "key_numbers.json").write_text(json.dumps(key, indent=2, default=str))
    print("wrote", OUT / "TABLES.md")


if __name__ == "__main__":
    main()
