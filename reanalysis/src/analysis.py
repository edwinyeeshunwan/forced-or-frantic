"""Effect estimation, descriptive tables and legacy-versus-corrected comparisons."""
from __future__ import annotations

import numpy as np
import pandas as pd

import episodes as EP
import inference as INF
from events import Params

GROUPS = ("contraction", "limited")


def contrast(ev: pd.DataFrame) -> pd.DataFrame:
    return ev[ev["analysable"] & ev["klass"].isin(GROUPS)].copy()


def descriptive(ev: pd.DataFrame, rec_col="rec", tau=1320) -> pd.DataFrame:
    rows = []
    a = ev[ev["analysable"]]
    for k in ("contraction", "limited", "intermediate"):
        g = a[a["klass"] == k]
        if not len(g):
            continue
        d, e = g[f"{rec_col}_min"].to_numpy(float), g[f"{rec_col}_event"].astype(bool).to_numpy()
        rows.append({"class": k, "n": len(g), "BTC": int((g.symbol == "BTC").sum()), "ETH": int((g.symbol == "ETH").sum()),
                     "median_doi_pct": 100 * g["doi"].median(),
                     "median_disp_x100": 100 * g["disp"].median(),
                     "median_p6h_x100": 100 * g["p6h"].median(),
                     "median_p24h_x100": 100 * g["p24h"].median(),
                     "n_p24h": int(g["p24h"].notna().sum()),
                     "median_reversion": g["reversion"].median(),
                     "km_share_unrecovered_at_tau": INF.km_at(d, e, tau),
                     "rmst_min": INF.rmst(d, e, tau),
                     "share_recovered_observed": float(e.mean()),
                     "share_censored_incomplete_followup": float((~e & ~g[f"{rec_col}_complete"].astype(bool)).mean()),
                     "median_R_onset_musd": float(g["R_onset"].median() / 1e6),
                     "median_notional_W_musd": float(g["notional_W"].median() / 1e6) if "notional_W" in g else np.nan,
                     "median_chain_span_min": float(g["chain_span_min"].median()) if "chain_span_min" in g else np.nan})
    return pd.DataFrame(rows)


def effects(ev: pd.DataFrame, p: Params, short="ep6", long="ep24", B=4999, B_wcr=9999, seed=20260911,
            rec_col="rec", tau=None, continuous=False, with_ci=True) -> dict:
    c = contrast(ev)
    g = (c["klass"] == "contraction").to_numpy()
    out = {"n_contraction": int(g.sum()), "n_limited": int((~g).sum()), "n_all_analysable": int(ev["analysable"].sum())}
    out["clusters_short"] = EP.cluster_summary(c, short)
    out["clusters_long"] = EP.cluster_summary(c, long)
    if g.sum() < 3 or (~g).sum() < 3:
        return out
    out["E1_disp"] = INF.median_diff(100 * c["disp"], g, c[short], B, seed)
    out["E3_p6h"] = INF.median_diff(100 * c["p6h"], g, c[short], B, seed)
    out["E4_p24h"] = INF.median_diff(100 * c["p24h"], g, c[long], B, seed)
    out["E5_reversion"] = INF.median_diff(c["reversion"], g, c[short], B, seed)
    # E2 regression
    if continuous:
        a = ev[ev["analysable"]].copy()
        y = 100 * a["disp"].abs().to_numpy()
        cols = [np.ones(len(a)), -100 * a["doi"].to_numpy()]     # per percentage point of OI destroyed
        if p.intensity != "none":
            cols.append(np.log(a["intensity"].to_numpy()))
        if a["symbol"].nunique() > 1:
            cols.append((a["symbol"] == "ETH").astype(float).to_numpy())
        X = np.column_stack(cols)
        out["E2_reg"] = INF.regression(y, X, a[short].to_numpy(), k=1, B=B_wcr, seed=seed)
        out["E2_reg"]["regressor"] = "OI destroyed (-dOI, percentage points), all analysable events"
    else:
        y = 100 * c["disp"].abs().to_numpy()
        cols = [np.ones(len(c)), g.astype(float)]
        if p.intensity != "none":
            cols.append(np.log(c["intensity"].to_numpy()))
        if c["symbol"].nunique() > 1:
            cols.append((c["symbol"] == "ETH").astype(float).to_numpy())
        X = np.column_stack(cols)
        out["E2_reg"] = INF.regression(y, X, c[short].to_numpy(), k=1, B=B_wcr, seed=seed)
        out["E2_reg"]["regressor"] = "contraction dummy, contrast events"
    # E6 recovery
    if tau is None:
        tau = p.horizon_h * 60 - p.win_post_min if rec_col == "rec" else p.horizon_h * 60
    d = c[f"{rec_col}_min"].to_numpy(float)
    e = c[f"{rec_col}_event"].astype(bool).to_numpy()
    out["E6_rmst"] = INF.rmst_diff(d, e, g, c[long], tau, B, seed)
    out["E6_rmst"]["tau_min"] = tau
    lr = INF.logrank(d, e, g, c[long].to_numpy())
    out["E6_logrank"] = lr
    return out


def flat(eff: dict) -> dict:
    """One-row summary for sensitivity grids."""
    r = {"n_contraction": eff.get("n_contraction"), "n_limited": eff.get("n_limited"),
         "n_analysable": eff.get("n_all_analysable"),
         "G_short": eff.get("clusters_short", {}).get("G"), "G_short_mixed": eff.get("clusters_short", {}).get("G_mixed"),
         "G_long": eff.get("clusters_long", {}).get("G")}
    for key, lab in (("E1_disp", "E1_disp_diff"), ("E3_p6h", "E3_p6h_diff"), ("E4_p24h", "E4_p24h_diff"),
                     ("E5_reversion", "E5_rev_diff")):
        if key in eff:
            r[lab], r[lab + "_lo"], r[lab + "_hi"] = eff[key]["est"], eff[key]["lo"], eff[key]["hi"]
    if "E2_reg" in eff:
        e2 = eff["E2_reg"]
        r.update({"E2_coef": e2["coef"], "E2_lo_wcr": e2["lo_wcr"], "E2_hi_wcr": e2["hi_wcr"],
                  "E2_p_wcr": e2["p_wcr"], "E2_p_cr1": e2["p_cr1"], "E2_G": e2["G"], "E2_Gstar": e2["G_star"]})
    if "E6_rmst" in eff:
        e6 = eff["E6_rmst"]
        r.update({"E6_rmst_diff_min": e6["est"], "E6_lo": e6["lo"], "E6_hi": e6["hi"],
                  "E6_p_logrank_robust": eff["E6_logrank"].get("p_robust")})
    return r


# --------------------------------------------------------------------------- membership
def match_legacy(leg: pd.DataFrame, cor: pd.DataFrame, tts: dict, p: Params) -> pd.DataFrame:
    """Match each legacy event to corrected onsets of the same asset.
    legacy t0 is the LEFT label of its trigger bin, so the same bin corresponds to
    corrected E0 = t0 + 5 min."""
    rows = []
    width = pd.Timedelta(minutes=5)
    for r in leg.itertuples():
        c = cor[cor.symbol == r.symbol]
        tt = tts[r.symbol]
        same = c[c.E0 == r.t0 + width]
        span_end = r.chain_end + width
        near = c[(c.E0 >= r.t0 - pd.Timedelta(minutes=p.quiet_min)) & (c.E0 <= span_end + pd.Timedelta(minutes=5))]
        rec = {"symbol": r.symbol, "legacy_t0": r.t0, "legacy_class": r.klass}
        if len(same):
            m = same.iloc[0]
            rec.update(status="same onset bin", E0=m.E0, corrected_class=m.klass, analysable=bool(m.analysable),
                       exclusion=m.reason)
        elif len(near):
            m = near.iloc[0]
            rec.update(status="onset shifted", E0=m.E0, corrected_class=m.klass, analysable=bool(m.analysable),
                       exclusion=m.reason, shift_min=(m.E0 - (r.t0 + width)).total_seconds() / 60)
        else:
            win = tt.loc[r.t0 + width: span_end]
            elig = bool(win["eligible"].any())
            if not elig:
                why = "before full 30-day warm-up"
            elif not win["trigger"].any():
                why = "no bin exceeds prior-only threshold"
            else:
                why = "absorbed into an earlier corrected chain"
            rec.update(status="dropped", E0=pd.NaT, corrected_class=None, analysable=False, exclusion=why)
        rows.append(rec)
    m = pd.DataFrame(rows)
    matched = set(m["E0"].dropna().astype("int64")) if len(m) else set()
    new = cor[~cor["E0"].astype("int64").isin(matched)]
    for r in new.itertuples():
        tt = tts[r.symbol]
        rows.append({"symbol": r.symbol, "legacy_t0": pd.NaT, "legacy_class": None, "status": "new in corrected",
                     "E0": r.E0, "corrected_class": r.klass, "analysable": bool(r.analysable), "exclusion": r.reason})
    return pd.DataFrame(rows)


def size_diagnostics(ev: pd.DataFrame) -> dict:
    """Post-hoc diagnostic (added after the S5a result was seen; see DEVIATIONS.md):
    how strongly the OI response co-moves with liquidation size measures."""
    a = ev[ev["analysable"]]
    out = {}
    for col in ("R_onset", "notional_W"):
        x = (-a["doi"]).rank()
        y = np.log(a[col]).rank()
        out[f"spearman_OI_destroyed_vs_log_{col}"] = float(np.corrcoef(x, y)[0, 1])
    c = contrast(ev)
    for k in GROUPS:
        g = c[c.klass == k]
        out[f"median_notional_W_musd_{k}"] = float(g["notional_W"].median() / 1e6)
        out[f"median_R_onset_musd_{k}"] = float(g["R_onset"].median() / 1e6)
    if "ep6" in a:
        # continuous OI destroyed with the window-total size control (post hoc; not a declared sensitivity)
        X = np.column_stack([np.ones(len(a)), -100 * a["doi"], np.log(a["notional_W"]), (a["symbol"] == "ETH").astype(float)])
        out["posthoc_continuous_OI_with_window_notional"] = INF.regression(100 * a["disp"].abs().to_numpy(), X,
                                                                           a["ep6"].to_numpy(), k=1, B=B_WCR_DIAG)
        X2 = np.column_stack([np.ones(len(a)), np.log(a["notional_W"]), (a["symbol"] == "ETH").astype(float)])
        out["posthoc_window_notional_only_coef_per_log_unit"] = float(np.linalg.lstsq(X2, 100 * a["disp"].abs().to_numpy(), rcond=None)[0][1])
    return out


B_WCR_DIAG = 9999
