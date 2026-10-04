import numpy as np
import pandas as pd

import inference as INF
from common import DATA, REV2
from parquet_fallback import read_parquet_fallback, _snappy_py, _load_snappy


def test_km_and_rmst_by_hand():
    d = np.array([10, 20, 20, 30, 40.0])
    e = np.array([1, 1, 0, 1, 0], bool)
    t, S = INF.km(d, e)
    assert np.allclose(t, [10, 20, 30]) and np.allclose(S, [0.8, 0.6, 0.3])
    # RMST to 35 = 10*1 + 10*0.8 + 10*0.6 + 5*0.3
    assert np.isclose(INF.rmst(d, e, 35), 10 + 8 + 6 + 1.5)


def test_logrank_matches_legacy_implementation():
    import ast
    from common import SCRIPTS
    src = (SCRIPTS / "analyze_liq_events.py").read_text()
    tree = ast.parse(src)
    ns = {"np": np, "math": __import__("math"), "pd": pd}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("_chi2_sf_1df", "logrank")]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "legacy", "exec"), ns)
    rng = np.random.default_rng(0)
    d1, d2 = rng.integers(5, 300, 30).astype(float), rng.integers(5, 300, 25).astype(float)
    e1, e2 = rng.random(30) < 0.7, rng.random(25) < 0.7
    chi_leg, _ = ns["logrank"](d1, e1, d2, e2)
    out = INF.logrank(np.r_[d1, d2], np.r_[e1, e2], np.r_[np.ones(30), np.zeros(25)],
                      cl=np.arange(55))
    assert np.isclose(out["chi2"], chi_leg)
    assert abs(out["score_check"]) < 1e-9


def test_cr1_matches_explicit_sandwich():
    rng = np.random.default_rng(1)
    N, G = 60, 12
    cl = np.repeat(np.arange(G), N // G)
    X = np.column_stack([np.ones(N), rng.integers(0, 2, N), rng.normal(size=N)])
    y = X @ [1, 0.5, -0.2] + rng.normal(size=N) + rng.normal(size=G)[cl]
    b, se, _ = INF.cr1(y, X, cl, 1)
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    u = y - X @ beta
    A = np.linalg.inv(X.T @ X)
    meat = sum(np.outer(X[cl == g].T @ u[cl == g], X[cl == g].T @ u[cl == g]) for g in range(G))
    V = A @ meat @ A * G / (G - 1) * (N - 1) / (N - 3)
    assert np.isclose(se, np.sqrt(V[1, 1])) and np.isclose(b, beta[1])


def test_wcr_ci_contains_estimate_and_p_is_one_at_estimate():
    rng = np.random.default_rng(2)
    N, G = 50, 15
    cl = rng.integers(0, G, N)
    X = np.column_stack([np.ones(N), rng.integers(0, 2, N)])
    y = X @ [0, 0.3] + rng.normal(size=N)
    r = INF.regression(y, X, cl, k=1, B=999)
    assert r["lo_wcr"] < r["coef"] < r["hi_wcr"]
    assert 0 <= r["p_wcr"] <= 1 and 1 <= r["G_star"] <= G


def test_cluster_bootstrap_keeps_clusters_together():
    y = np.array([1, 1, 5, 5, 9, 9.0])
    grp = np.array([1, 0, 1, 0, 1, 0], bool)
    r = INF.median_diff(y, grp, cl=np.array([0, 0, 1, 1, 2, 2]), B=500)
    assert r["est"] == 0 and r["lo"] == 0 and r["hi"] == 0   # within-cluster pairs are identical


def test_parquet_fallback_matches_saved_csv():
    a = read_parquet_fallback(DATA / "event_table_liq.parquet")
    b = pd.read_csv(REV2 / "legacy_rebuilt_99.csv")
    a = a.sort_values(["symbol", "t0"]).reset_index(drop=True)
    b["t0"] = pd.to_datetime(b["t0"], utc=True)
    b = b.sort_values(["symbol", "t0"]).reset_index(drop=True)
    assert (a["t0"].dt.as_unit("ns") == b["t0"].dt.as_unit("ns")).all()
    for c in ("p0", "liq_notional", "doi_event", "peak_disloc", "ttr_min", "perm_6h", "perm_24h", "transitory_share"):
        assert np.allclose(a[c], b[c], equal_nan=True, rtol=1e-12), c
    assert (a["klass"] == b["klass"]).all()


def test_pure_python_snappy():
    lib = _load_snappy()
    if not lib:
        return  # nothing to compare against on this machine
    import ctypes
    rng = np.random.default_rng(3)
    raw = (b"liquidation " * 500) + rng.integers(0, 256, 3000, dtype=np.uint8).tobytes() + b"abcabcabc" * 200
    lib.snappy_max_compressed_length.restype = ctypes.c_size_t
    n = lib.snappy_max_compressed_length(len(raw))
    out = ctypes.create_string_buffer(n)
    ln = ctypes.c_size_t(n)
    lib.snappy_compress.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t)]
    assert lib.snappy_compress(raw, len(raw), out, ctypes.byref(ln)) == 0
    assert _snappy_py(out.raw[:ln.value]) == raw
