"""Run the complete reanalysis: input verification, legacy reproduction, provenance audit,
corrected primary analysis, membership comparison, all declared sensitivities, tests and
an input/output manifest.

    python run_all.py            # everything (a few minutes)
    python run_all.py --quick    # fewer bootstrap draws (for smoke tests only)

Outputs go to reanalysis/outputs/ (override with REANALYSIS_OUT_DIR)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import analysis as AN  # noqa: E402
import figures as FG  # noqa: E402
import audit as AU  # noqa: E402
import episodes as EP  # noqa: E402
import events as E  # noqa: E402
import inference as INF  # noqa: E402
import legacy as LG  # noqa: E402
from common import OUT, PAPER, environment, load, oi_series, price_bars, sha256, verify_inputs, write_json  # noqa: E402

SEED = 20260911


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def loaders(transform=None):
    def f(coin):
        liq = load(coin, "liquidations")
        if transform is not None:
            liq = transform(liq)
        return liq, price_bars(coin), oi_series(coin)
    return f


# --------------------------------------------------------------------------- waterfall
def stage_triggers(liq, q, label, include_current, min_days):
    """Transparent alternative implementation of each correction step (pandas only)."""
    s = liq[liq.side == "sell"].set_index("ts")["notional"].sort_index()
    n5 = s.resample("5min", closed="left", label=label).sum()
    roll = n5.rolling("15min").sum()
    thr = roll.rolling("30D", closed="right" if include_current else "left",
                       min_periods=int(288 * min_days)).quantile(q)
    return roll[(roll > 0) & (roll >= thr)].index


def chain_onsets(trig, quiet=120):
    if len(trig) == 0:
        return trig
    gaps = np.diff(trig.as_unit("ns").asi8) / 6e10
    return trig[np.concatenate([[True], gaps > quiet])]


def waterfall(q, tts_primary):
    rows, checks = [], {}
    stages = [("0 legacy (left-labelled bins, current-inclusive threshold, 7-day minimum)", "left", True, 7),
              ("1 right-labelled completed bins", "right", True, 7),
              ("2 + threshold from prior decision times only", "right", False, 7),
              ("3 + full 30-day baseline (primary trigger rule)", "right", False, 30)]
    for name, lab, inc, md in stages:
        r = {"stage": name}
        for coin in ("BTC", "ETH"):
            liq = load(coin, "liquidations")
            trig = stage_triggers(liq, q, lab, inc, md)
            r[f"{coin}_triggers"] = len(trig)
            r[f"{coin}_onsets"] = len(chain_onsets(trig))
            if md == 30 and not inc and lab == "right" and tts_primary is not None:
                mine = tts_primary[coin].index[tts_primary[coin]["trigger"].to_numpy()]
                checks[coin] = {"alt_impl_triggers": len(trig), "events_py_triggers": len(mine),
                                "symmetric_difference": len(trig.symmetric_difference(mine))}
            if name.startswith("0"):
                leg = LG.NS["detect_events"](liq, q)
                checks[f"{coin}_stage0_equals_legacy_detect_events"] = bool(
                    len(leg) == len(chain_onsets(trig)) and (leg["t0"].to_numpy() == chain_onsets(trig).to_numpy()).all())
        r["total_onsets"] = r["BTC_onsets"] + r["ETH_onsets"]
        rows.append(r)
    return pd.DataFrame(rows), checks


# --------------------------------------------------------------------------- helpers
def finalize(ev):
    ev = EP.assign(ev)
    return ev


def run_effects(ev, p, B, Bw, **kw):
    return AN.effects(ev, p, B=B, B_wcr=Bw, seed=SEED, **kw)


def intersects_runs(ev, runs_by_coin, p):
    bad = []
    for r in ev.itertuples():
        a0 = r.E0 - pd.Timedelta(minutes=p.win_pre_min)
        a1 = r.E0 + pd.Timedelta(minutes=p.win_post_min)
        bad.append(any((s < a1) and (e > a0) for s, e in runs_by_coin[r.symbol]))
    return np.array(bad, bool)


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--part", choices=["all", "core", "sensitivity", "finish"], default="all",
                    help="run in parts on machines with short command time limits: core, then sensitivity, then finish")
    ap.add_argument("--specs", help="with --part sensitivity: zero-based inclusive range of specifications, e.g. 0-8")
    a = ap.parse_args()
    B, Bw = (499, 999) if a.quick else (4999, 9999)
    OUT.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    if a.part in ("all", "core"):
        core(B, Bw)
    if a.part in ("all", "sensitivity"):
        which = None
        if a.specs:
            lo, hi = (int(x) for x in a.specs.split("-"))
            which = list(range(lo, hi + 1))
        sensitivity(B, Bw, which)
    if a.part in ("all", "finish"):
        finish(a, B, Bw, t_start)


def core(B, Bw):
    log("1/9 verifying input hashes")
    write_json(verify_inputs(), OUT / "input_verification.json")

    log("2/9 legacy reconstruction")
    leg = {q: LG.legacy_table(q) for q in (0.99, 0.95)}
    for q, d in leg.items():
        (OUT / "legacy").mkdir(exist_ok=True)
        d.to_csv(OUT / "legacy" / f"legacy_rebuilt_{int(q * 100)}.csv", index=False)
    chk = LG.check(leg)
    write_json(chk, OUT / "legacy" / "legacy_benchmark_check.json")
    if not chk["all_benchmarks_reproduced"]:
        raise SystemExit("legacy benchmarks NOT reproduced - stop and investigate")

    log("3/9 provenance audit")
    aud = {c: AU.coverage_audit(c) for c in ("BTC", "ETH")}
    write_json(aud, OUT / "audit" / "audit.json")
    runs12 = {c: E.zero_runs(load(c, "liquidations"), E.Params(), 12) for c in ("BTC", "ETH")}
    pd.concat([AU.gap_price_moves(c, runs12[c]) for c in runs12]).to_csv(OUT / "audit" / "zero_runs_ge12h.csv", index=False)

    log("4/9 corrected primary events")
    p = E.Params()
    ev, tts = E.build_all(p, loaders())
    ev = finalize(ev)
    (OUT / "corrected").mkdir(exist_ok=True)
    ev.to_csv(OUT / "corrected" / "events_primary.csv", index=False)
    wf, wf_checks = waterfall(0.99, tts)
    an = ev[ev.analysable]
    wf = pd.concat([wf, pd.DataFrame([{
        "stage": "4 + measurement requirements (reference, window bars, OI coverage)",
        "BTC_onsets": int((an.symbol == "BTC").sum()), "ETH_onsets": int((an.symbol == "ETH").sum()),
        "total_onsets": int(len(an))}])], ignore_index=True)
    wf.to_csv(OUT / "corrected" / "event_count_waterfall.csv", index=False)
    write_json(wf_checks, OUT / "corrected" / "waterfall_implementation_checks.json")

    log("5/9 membership comparison with legacy")
    mem = AN.match_legacy(leg[0.99], ev, tts, p)
    mem.to_csv(OUT / "corrected" / "membership_legacy_vs_corrected.csv", index=False)
    msum = mem.groupby(["status", "exclusion"], dropna=False).size().reset_index(name="n")
    msum.to_csv(OUT / "corrected" / "membership_summary.csv", index=False)
    both = mem[mem["legacy_class"].notna() & mem["corrected_class"].notna()]
    trans = pd.crosstab(both["legacy_class"], both["corrected_class"])
    trans.to_csv(OUT / "corrected" / "class_transitions.csv")

    log("6/9 primary effects")
    eff = run_effects(ev, p, B, Bw)
    (OUT / "results").mkdir(exist_ok=True)
    AN.descriptive(ev).to_csv(OUT / "results" / "descriptive_primary.csv", index=False)
    eff["size_diagnostics_posthoc"] = AN.size_diagnostics(finalize(ev.drop(columns=["ep6", "ep24", "day", "week", "none"])))
    write_json(eff, OUT / "results" / "primary_effects.json")
    FG.km_figure(ev, OUT / "results" / "fig_km_post_window_recovery.png")

    # legacy definitions evaluated with the same dependence-aware inference (comparison)
    L = leg[0.99].copy()
    L = L.rename(columns={"t0": "E0", "peak_disloc": "disp", "perm_6h": "p6h", "perm_24h": "p24h",
                          "transitory_share": "reversion", "ttr_min": "rec_min"})
    L["klass"] = L["klass"].map({"deleverage": "contraction", "churn": "limited", "middle": "intermediate"})
    L["rec_event"] = ~L["censored"].astype(bool)
    L["rec_complete"] = True
    L["analysable"] = True
    L["intensity"] = L["liq_notional"]
    L["R_onset"] = L["liq_notional"]
    L = finalize(L)
    eff_leg = run_effects(L, p, B, Bw, tau=1440)
    write_json(eff_leg, OUT / "results" / "legacy_definitions_clustered_effects.json")

    log("7/9 clustering sensitivity (S7)")
    crow = []
    for name, s, l in [("primary (6 h / 24 h episodes)", "ep6", "ep24"), ("24 h episodes for all", "ep24", "ep24"),
                       ("6 h episodes for all", "ep6", "ep6"), ("UTC calendar day", "day", "day"),
                       ("ISO calendar week", "week", "week"), ("none: asset-event (reference only)", "none", "none")]:
        r = AN.flat(run_effects(ev, p, B, Bw, short=s, long=l))
        crow.append({"clustering": name, **r})
    pd.DataFrame(crow).to_csv(OUT / "results" / "clustering_sensitivity.csv", index=False)



def spec_list(ev, p, runs12):
    """Declared sensitivity specifications (protocol section 8), as zero-argument builders."""
    def rebuild(px, transform=None):
        return lambda: (E.build_all(px, loaders(transform))[0], px, {})

    def s8():
        px = p.with_(missing_zero_run_h=12)
        evx, _ = E.build_all(px, loaders())
        evx["analysable"] &= ~intersects_runs(evx, runs12, px)
        return evx, px, {}

    base = ev.drop(columns=["ep6", "ep24", "day", "week", "none"])
    oct_mask = ev["E0"].between(pd.Timestamp("2025-10-10", tz="UTC"), pd.Timestamp("2025-10-18", tz="UTC"), inclusive="left")
    return [("S1 7-day minimum warm-up", rebuild(p.with_(warmup_days=7))),
            ("S2 trigger quantile 0.95", rebuild(p.with_(trig_q=0.95))),
            ("S3 legacy-aligned reference", rebuild(p.with_(ref_mode="legacy_aligned"))),
            ("S4 fixed-cut classification", rebuild(p.with_(classify="fixed"))),
            ("S5a intensity = total sell notional in W", rebuild(p.with_(intensity="window_total"))),
            ("S5b no intensity control", rebuild(p.with_(intensity="none"))),
            ("S13a quiet period 60 min", rebuild(p.with_(quiet_min=60))),
            ("S13b quiet period 180 min", rebuild(p.with_(quiet_min=180))),
            ("S13c event window 1 h", rebuild(p.with_(win_post_min=60))),
            ("S13d event window 3 h", rebuild(p.with_(win_post_min=180))),
            ("S6a recovery: close-based after trough bar (from onset)", lambda: (base.copy(), p, {"rec_col": "rec_trough_close"})),
            ("S6b recovery: next-bar high crossing after trough (from onset)", lambda: (base.copy(), p, {"rec_col": "rec_trough_high"})),
            ("S8 zero runs >= 12 h treated as missing", s8),
            ("S9 reinstated legacy-dropped rows (adjacent-row assumption)", rebuild(p, AU.reinstate_dropped)),
            ("S10 exclude 10-17 Oct 2025", lambda: (base[~oct_mask].copy(), p, {})),
            ("S11 BTC only", lambda: (base[base.symbol == "BTC"].copy(), p, {})),
            ("S11 ETH only", lambda: (base[base.symbol == "ETH"].copy(), p, {})),
            ("S12 continuous OI destroyed (all analysable events; E2 only)", lambda: (base.copy(), p, {"continuous": True}))]


def sensitivity(B, Bw, which=None):
    log("8/9 declared sensitivity grid (S1-S13)")
    parts = OUT / "results" / "grid_parts"
    parts.mkdir(parents=True, exist_ok=True)
    p = E.Params()
    ev, _ = E.build_all(p, loaders())
    ev = finalize(ev)
    runs12 = {c: E.zero_runs(load(c, "liquidations"), E.Params(), 12) for c in ("BTC", "ETH")}
    specs = spec_list(ev, p, runs12)
    idx = range(len(specs)) if which is None else which
    if which is None or 0 in which:
        write_json({"spec": "Primary", **AN.flat(run_effects(ev, p, B, Bw))}, parts / "00_primary.json")
    for i in idx:
        name, build = specs[i]
        evx, px, kw = build()
        evx = finalize(evx)
        write_json({"spec": name, **AN.flat(run_effects(evx, px, B, Bw, **kw))}, parts / f"{i + 1:02d}.json")
        log(f"   {name}: n={int(evx.analysable.sum())}")


def assemble_grid():
    parts = sorted((OUT / "results" / "grid_parts").glob("*.json"))
    rows = [json.loads(q.read_text()) for q in parts]
    g = pd.DataFrame(rows)
    g.to_csv(OUT / "results" / "sensitivity_grid.csv", index=False)
    FG.forest_figure(g, OUT / "results" / "fig_sensitivity_forest.png")
    return g


def finish(a, B, Bw, t_start):
    log("9/9 assemble grid, tests, manifest")
    assemble_grid()
    if not a.skip_tests:
        sys.path.insert(0, str(HERE / "tests"))
        import run_tests
        n_fail = run_tests.main(OUT / "test_report.txt")
    else:
        n_fail = None
    import make_tables
    make_tables.main()
    manifest = {"generated_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
                "environment": environment(), "bootstrap_draws": {"cluster": B, "wild_cluster": Bw}, "seed": SEED,
                "protocol": {"file": "protocol/CORRECTION_PROTOCOL.md", "sha256": sha256(HERE / "protocol" / "CORRECTION_PROTOCOL.md"),
                             "frozen_record": json.loads((HERE / "protocol" / "PROTOCOL_FREEZE.json").read_text())},
                "tests_failed": n_fail, "runtime_s_this_invocation": round(time.time() - t_start, 1),
                "inputs": {str(pth.relative_to(PAPER)): sha256(pth) for pth in sorted((PAPER / "data").glob("hyperliquid_*.parquet"))
                           } | {"data/event_table_liq.parquet": sha256(PAPER / "data" / "event_table_liq.parquet")},
                "code": {str(pth.relative_to(HERE)): sha256(pth) for pth in sorted(HERE.rglob("*.py")) if "__pycache__" not in str(pth)},
                "outputs": {str(pth.relative_to(OUT)): sha256(pth) for pth in sorted(OUT.rglob("*")) if pth.is_file() and pth.name != "MANIFEST.json"}}
    write_json(manifest, OUT / "MANIFEST.json")
    log(f"done in {time.time() - t_start:.0f}s; tests failed: {n_fail}")


if __name__ == "__main__":
    main()
