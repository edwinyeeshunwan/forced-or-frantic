"""Static figures for the paper (matplotlib; optional dependency).
Colours: validated categorical slots 1-2 (blue #2a78d6, orange #eb6834) on #fcfcfb,
with line style as secondary encoding for greyscale print."""
from __future__ import annotations

import numpy as np
import pandas as pd

import analysis as AN
import inference as INF

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#d9d8d3"
C_CON, C_LIM = "#eb6834", "#2a78d6"


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8.5, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
                         "ytick.color": INK2, "text.color": INK, "font.family": "DejaVu Sans"})
    return plt


def km_figure(ev, path, tau=1320):
    try:
        plt = _plt()
    except ImportError:
        return False
    c = AN.contrast(ev)
    fig, ax = plt.subplots(figsize=(6.3, 3.8), dpi=220, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    spec = [("contraction", C_CON, "-", "OI contraction"), ("limited", C_LIM, (0, (5, 2)), "Limited OI contraction")]
    for k, col, ls, lab in spec:
        g = c[c.klass == k]
        d, e = g["rec_min"].to_numpy(float), g["rec_event"].astype(bool).to_numpy()
        t, S = INF.km(d, e)
        tt = np.r_[0, t, tau]
        ss = np.r_[1, S, S[-1] if len(S) else 1]
        ax.step(tt / 60, ss, where="post", color=col, ls=ls, lw=2, label=f"{lab} (n={len(g)})")
        cen = d[~e]
        ax.plot(cen / 60, [INF.km_at(d, e, x) for x in cen], "|", color=col, ms=8, mew=1.5)
        ax.annotate(f"{lab}: {100 * INF.km_at(d, e, tau):.0f}% not recovered", xy=(tau / 60, ss[-1]),
                    xytext=(-4, 9 if k == "contraction" else -12), textcoords="offset points", ha="right",
                    fontsize=8, color=INK)
    ax.set_xlim(0, 22.2)
    ax.set_ylim(0, 1.03)
    ax.set_xticks(range(0, 23, 2))
    ax.set_xlabel("Hours after the event window closes (onset + 2 h)")
    ax.set_ylabel("Share not yet recovered")
    ax.grid(axis="y", color=GRID, lw=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, loc="upper right", bbox_to_anchor=(1, 0.93))
    ax.text(0.0, -0.24, "Kaplan-Meier estimates. Tick marks show censored events. Recovery is the first 5-minute close\n"
            "at or above the pre-event reference x (1 - 0.001).", transform=ax.transAxes, fontsize=7, color=INK2, va="top")
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return True


def forest_figure(grid: pd.DataFrame, path):
    """Estimates and 95% intervals for E1 and E2 across the declared specifications."""
    try:
        plt = _plt()
    except ImportError:
        return False
    g = grid[~grid["spec"].str.startswith(("S6", "S12"))].reset_index(drop=True)
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 4.8), dpi=220, sharey=True, facecolor=SURFACE)
    y = np.arange(len(g))[::-1]
    panels = [("E1_disp_diff", "E1_disp_diff_lo", "E1_disp_diff_hi",
               "E1  Median displacement gap\n(contraction minus limited, log pts x 100)"),
              ("E2_coef", "E2_lo_wcr", "E2_hi_wcr",
               "E2  Conditional |displacement| gap\n(OLS coefficient x 100)")]
    for ax, (est, lo, hi, title) in zip(axes, panels):
        ax.set_facecolor(SURFACE)
        ax.axvline(0, color=INK2, lw=0.8)
        for yi, (_, r) in zip(y, g.iterrows()):
            prim = r["spec"] == "Primary"
            col = INK if prim else INK2
            ax.plot([r[lo], r[hi]], [yi, yi], color=col, lw=2.2 if prim else 1.4, solid_capstyle="round")
            ax.plot(r[est], yi, "o", color=col, ms=6 if prim else 4.5, mec=SURFACE, mew=1)
        ax.set_title(title, fontsize=8.5, loc="left")
        ax.grid(axis="x", color=GRID, lw=0.6)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.tick_params(axis="y", length=0)
    axes[0].set_yticks(y)
    short = {"S9 reinstated legacy-dropped rows (adjacent-row assumption)": "S9 reinstated dropped rows",
             "S5a intensity = total sell notional in W": "S5a control: total notional in W",
             "S8 zero runs >= 12 h treated as missing": "S8 long zero runs as missing"}
    axes[0].set_yticklabels([short.get(s, s) for s in g["spec"]], fontsize=7.5)
    fig.text(0.01, 0.01, "Primary clustering: 6-hour cross-asset market episodes. Intervals: episode bootstrap (E1) and "
             "wild cluster restricted bootstrap (E2).", fontsize=6.8, color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    return True
