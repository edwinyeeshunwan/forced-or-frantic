"""Dependence-aware inference utilities (numpy only; no SciPy dependency).

* episode (cluster) bootstrap for differences in medians and RMST
* OLS with CR1 cluster-robust SE, t(G-1) reference
* wild cluster restricted (WCR) bootstrap with Webb six-point weights, CI by test inversion
  (Cameron, Gelbach & Miller 2008; MacKinnon & Webb 2017; Webb 2023; Roodman et al. 2019)
* Carter-Schnepel-Steigerwald (2017) effective number of clusters G* (rho = 1)
* Kaplan-Meier, restricted mean survival time, log-rank with cluster-robust (Lin-Wei) variance
"""
from __future__ import annotations

import math

import numpy as np


# --------------------------------------------------------------------------- distributions
def _betacf(a, b, x, itmax=400, eps=3e-16):
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1.0 + aa / c
        c = c if abs(c) > 1e-300 else 1e-300
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1.0 + aa / c
        c = c if abs(c) > 1e-300 else 1e-300
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            break
    return h


def betainc(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1 - x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1 - x) / b


def t_sf2(t, df):
    """Two-sided p value for Student t."""
    if not np.isfinite(t):
        return float("nan")
    return betainc(df / 2.0, 0.5, df / (df + t * t))


def t_ppf(q, df):
    """Quantile of Student t via bisection on the two-sided tail."""
    target = 2 * (1 - q)
    lo, hi = 0.0, 1e3
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_sf2(mid, df) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def chi2_1_sf(x):
    return math.erfc(math.sqrt(x / 2.0)) if (x is not None and np.isfinite(x) and x > 0) else float("nan")


# --------------------------------------------------------------------------- cluster bootstrap
def _cluster_index(cl):
    codes, uniq = _factor(cl)
    members = [np.flatnonzero(codes == g) for g in range(len(uniq))]
    return codes, members


def _factor(cl):
    uniq, codes = np.unique(np.asarray(cl), return_inverse=True)
    return codes, uniq


def cluster_bootstrap(stat, n, cl, B=4999, seed=20260911):
    """stat(idx) -> float (or nan to discard). Resample clusters with replacement."""
    rng = np.random.default_rng(seed)
    codes, members = _cluster_index(cl)
    G = len(members)
    out = np.empty(B)
    for b in range(B):
        draw = rng.integers(0, G, G)
        idx = np.concatenate([members[g] for g in draw])
        out[b] = stat(idx)
    return out


def median_diff(y, grp, cl, B=4999, seed=20260911):
    """median(y | grp) - median(y | ~grp) with cluster-bootstrap percentile CI."""
    y = np.asarray(y, float)
    grp = np.asarray(grp, bool)
    ok = np.isfinite(y)
    y, grp, cl = y[ok], grp[ok], np.asarray(cl)[ok]
    if grp.sum() < 3 or (~grp).sum() < 3:
        return dict(est=np.nan, lo=np.nan, hi=np.nan, n1=int(grp.sum()), n0=int((~grp).sum()), discarded=0)
    est = np.median(y[grp]) - np.median(y[~grp])

    def stat(idx):
        g = grp[idx]
        if g.sum() == 0 or (~g).sum() == 0:
            return np.nan
        v = y[idx]
        return np.median(v[g]) - np.median(v[~g])
    dist = cluster_bootstrap(stat, len(y), cl, B, seed)
    good = dist[np.isfinite(dist)]
    lo, hi = np.percentile(good, [2.5, 97.5])
    return dict(est=float(est), lo=float(lo), hi=float(hi), n1=int(grp.sum()), n0=int((~grp).sum()),
                discarded=int(B - len(good)), G=int(len(np.unique(cl))))


# --------------------------------------------------------------------------- OLS + clustering
def ols(y, X):
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    return beta, XtX_inv


def cr1(y, X, cl, k):
    beta, XtX_inv = ols(y, X)
    u = y - X @ beta
    codes, _ = _factor(cl)
    G = codes.max() + 1
    N, K = X.shape
    w = (X @ XtX_inv)[:, k]
    s = np.bincount(codes, weights=w * u, minlength=G)
    c = G / (G - 1) * (N - 1) / (N - K)
    se = math.sqrt(c * np.sum(s ** 2))
    return beta[k], se, G


def webb_weights(G, B, rng):
    vals = np.array([-math.sqrt(1.5), -1.0, -math.sqrt(0.5), math.sqrt(0.5), 1.0, math.sqrt(1.5)])
    return vals[rng.integers(0, 6, size=(G, B))]


def wcr(y, X, cl, k, B=9999, seed=20260911, alpha=0.05):
    """WCR bootstrap-t p value for H0: beta_k = 0 and a (1-alpha) CI by test inversion."""
    y = np.asarray(y, float)
    codes, _ = _factor(cl)
    G = codes.max() + 1
    N, K = X.shape
    rng = np.random.default_rng(seed)
    V = webb_weights(G, B, rng)
    Vn = V[codes]                                   # N x B
    beta, XtX_inv = ols(y, X)
    M = XtX_inv @ X.T                               # K x N
    mk = M[k]
    c = G / (G - 1) * (N - 1) / (N - K)
    Xr = np.delete(X, k, axis=1)
    Mr = np.linalg.inv(Xr.T @ Xr) @ Xr.T
    C = np.zeros((G, N))
    C[codes, np.arange(N)] = 1.0
    b_hat, se_hat, _ = cr1(y, X, cl, k)

    def pval(b0):
        yt = y - b0 * X[:, k]
        br = Mr @ yt
        fit = Xr @ br + b0 * X[:, k]
        ur = yt - Xr @ br
        Ys = fit[:, None] + ur[:, None] * Vn
        Bs = M @ Ys
        Us = Ys - X @ Bs
        S = C @ (mk[:, None] * Us)
        se = np.sqrt(c * np.sum(S ** 2, axis=0))
        ts = (Bs[k] - b0) / se
        t0 = (b_hat - b0) / se_hat
        return float(np.mean(np.abs(ts) >= abs(t0)))

    p0 = pval(0.0)

    def bound(direction):
        step = se_hat
        inner = b_hat
        outer = b_hat + direction * step
        n = 0
        while pval(outer) > alpha and n < 60:
            inner = outer
            outer = b_hat + direction * step * (2 ** (n + 1))
            n += 1
        for _ in range(40):
            mid = (inner + outer) / 2
            if pval(mid) > alpha:
                inner = mid
            else:
                outer = mid
        return (inner + outer) / 2
    lo, hi = bound(-1), bound(+1)
    return dict(p=p0, lo=float(lo), hi=float(hi), B=B)


def effective_clusters(X, cl, k):
    """Carter, Schnepel & Steigerwald (2017) G* with rho = 1."""
    codes, _ = _factor(cl)
    G = codes.max() + 1
    XtX_inv = np.linalg.inv(X.T @ X)
    w = (X @ XtX_inv)[:, k]
    gam = np.bincount(codes, weights=w, minlength=G) ** 2
    Gam = np.mean((gam - gam.mean()) ** 2) / gam.mean() ** 2
    return float(G / (1 + Gam))


def regression(y, X, cl, k=1, B=9999, seed=20260911):
    b, se, G = cr1(y, X, cl, k)
    tcrit = t_ppf(0.975, G - 1)
    w = wcr(y, X, cl, k, B=B, seed=seed)
    return dict(coef=float(b), se_cr1=float(se), G=int(G), df=int(G - 1),
                p_cr1=float(t_sf2(b / se, G - 1)), lo_cr1=float(b - tcrit * se), hi_cr1=float(b + tcrit * se),
                p_wcr=w["p"], lo_wcr=w["lo"], hi_wcr=w["hi"], G_star=effective_clusters(X, cl, k), N=int(len(y)))


# --------------------------------------------------------------------------- survival
def km(d, e):
    d = np.asarray(d, float)
    e = np.asarray(e, bool)
    times = np.unique(d[e])
    S, s = [], 1.0
    for t in times:
        n = np.sum(d >= t)
        k = np.sum((d == t) & e)
        s *= 1 - k / n
        S.append(s)
    return times, np.array(S)


def km_at(d, e, tau):
    t, S = km(d, e)
    m = t <= tau
    return float(S[m][-1]) if m.any() else 1.0


def rmst(d, e, tau):
    t, S = km(d, e)
    area, prev_t, prev_s = 0.0, 0.0, 1.0
    for ti, si in zip(t, S):
        if ti > tau:
            break
        area += prev_s * (ti - prev_t)
        prev_t, prev_s = ti, si
    area += prev_s * (tau - prev_t)
    return area


def rmst_diff(d, e, grp, cl, tau, B=4999, seed=20260911):
    d, e, grp = np.asarray(d, float), np.asarray(e, bool), np.asarray(grp, bool)
    ok = np.isfinite(d)
    d, e, grp, cl = d[ok], e[ok], grp[ok], np.asarray(cl)[ok]
    est = rmst(d[grp], e[grp], tau) - rmst(d[~grp], e[~grp], tau)

    def stat(idx):
        g = grp[idx]
        if g.sum() == 0 or (~g).sum() == 0:
            return np.nan
        return rmst(d[idx][g], e[idx][g], tau) - rmst(d[idx][~g], e[idx][~g], tau)
    dist = cluster_bootstrap(stat, len(d), cl, B, seed)
    good = dist[np.isfinite(dist)]
    lo, hi = np.percentile(good, [2.5, 97.5])
    return dict(est=float(est), lo=float(lo), hi=float(hi),
                rmst1=float(rmst(d[grp], e[grp], tau)), rmst0=float(rmst(d[~grp], e[~grp], tau)),
                S1_tau=km_at(d[grp], e[grp], tau), S0_tau=km_at(d[~grp], e[~grp], tau),
                n1=int(grp.sum()), n0=int((~grp).sum()), discarded=int(B - len(good)))


def logrank(d, e, grp, cl=None):
    """Log-rank (Cox score at beta=0, Breslow ties). Returns ordinary and, if cl is
    given, cluster-robust (Lin-Wei sandwich) chi-square statistics and p values."""
    d, e, z = np.asarray(d, float), np.asarray(e, bool), np.asarray(grp, float)
    ok = np.isfinite(d)
    d, e, z = d[ok], e[ok], z[ok]
    times = np.unique(d[e])
    U, V = 0.0, 0.0
    W = e * 0.0
    W = W.astype(float)
    zbar_at = {}
    for t in times:
        risk = d >= t
        n = risk.sum()
        n1 = z[risk].sum()
        dd = np.sum((d == t) & e)
        d1 = np.sum(z[(d == t) & e])
        zb = n1 / n
        U += d1 - dd * zb
        if n > 1:
            V += dd * zb * (1 - zb) * (n - dd) / (n - 1)
        W[risk] -= (dd / n) * (z[risk] - zb)
        zbar_at[t] = zb
    for i in np.flatnonzero(e):
        W[i] += z[i] - zbar_at[d[i]]
    out = {"U": float(U), "chi2": float(U * U / V) if V > 0 else np.nan}
    out["p"] = chi2_1_sf(out["chi2"])
    if cl is not None:
        codes, _ = _factor(np.asarray(cl)[ok])
        s = np.bincount(codes, weights=W)
        Vr = float(np.sum(s ** 2))
        out["chi2_robust"] = float(U * U / Vr) if Vr > 0 else np.nan
        out["p_robust"] = chi2_1_sf(out["chi2_robust"])
        out["score_check"] = float(W.sum() - U)
    return out
