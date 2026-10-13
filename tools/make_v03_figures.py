"""v0.3 figures from recorded results only (results/runs.jsonl).

    python tools/make_v03_figures.py [--results-dir results] [--out paper/figures] [--allow-smoke]

Every number plotted is read from a recorded run summary; nothing is
simulated here. Uses the latest non-smoke entry of each v0.3 experiment.
Palette: the first three reference slots (blue, orange, aqua; validated
all-pairs, aqua below 3:1 on the surface, so every series is in the legend
and every value in results/V03_TABLES.md); shapes double-encode identity.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from make_figures import INK, INK2, SURFACE, setup  # noqa: E402

BLUE, ORANGE, AQUA, MUTED = "#2a78d6", "#eb6834", "#1baf7a", "#898781"


def latest(results: Path, allow_smoke: bool) -> dict:
    out = {}
    for line in (results / "runs.jsonl").read_text().splitlines():
        if line.strip():
            e = json.loads(line)
            c = e.get("config", {})
            smoke = c.get("smoke") or "SMOKE" in e.get("notes", "") or c.get("rehearsal")
            if e["experiment"].startswith("V03_") and (allow_smoke or not smoke):
                out[e["experiment"]] = e
    return out


def fig_operational(plt, e, path: Path) -> None:
    """Failed-job fraction vs calibrations per qubit-day: fixed schedules (the
    frontier) and warning-triggered policies, one panel per degrading scenario."""
    s, c = e["summary"], e["config"]
    scenarios = [x for x in c["scenarios"] if x != "I0"]
    fixed = [p for p in c["frontier_policies"] if p != "none"]
    # drawn in this order: CUSUM squares are larger and underneath, so a v0.3
    # circle at the same place (the two methods perform alike) leaves its corners visible
    pts = {
        "cusum+24": (ORANGE, "s", True, "CUSUM + daily", 64),
        "cusum_only": (ORANGE, "s", False, "CUSUM only", 64),
        "eng_any+24": (BLUE, "o", True, "v0.3 warnings + daily", 34),
        "eng_any_only": (BLUE, "o", False, "v0.3 warnings only", 34),
        "eng_cross+24": (BLUE, "^", True, "v0.3 crossing alerts + daily", 46),
        "oracle_only": (AQUA, "D", False, "oracle (true error > 5%)", 40),
    }
    fig, axes = plt.subplots(1, len(scenarios), figsize=(3.0 * len(scenarios), 3.5), sharey=True)
    # one y-scale for every panel, up to just above the daily schedule's worst failed fraction;
    # points above it (the 48 h schedule) are labelled at the top edge instead
    top = max(1.0, 1.1 * max(100 * s[sc]["policies"]["fixed24"]["failed"] for sc in scenarios))  # 1%: no failures
    for ax, sc in zip(axes, scenarios):
        pol = s[sc]["policies"]
        xs = [pol[p]["cal_per_qday"] for p in fixed]
        ys = [100 * pol[p]["failed"] for p in fixed]
        ax.plot(xs, ys, color=MUTED, lw=1.5, zorder=1)
        ax.scatter(xs, ys, s=16, color=MUTED, zorder=2)
        off = [f"{p.replace('fixed', '')} h schedule: {y:.0f}% (off scale)" for p, y in zip(fixed, ys) if y > top]
        if off:
            ax.text(0.98, 0.96, "\n".join(off), transform=ax.transAxes, ha="right", va="top", fontsize=7, color=INK2)
        for p, x, y in zip(fixed, xs, ys):
            if y > top:
                continue
            if p in ("fixed48", "fixed24", "fixed12", "fixed4", "fixed2"):
                ax.annotate(
                    p.replace("fixed", "") + " h",
                    (x, y),
                    textcoords="offset points",
                    xytext=(3, 4),
                    fontsize=7,
                    color=INK2,
                )
        for z, (p, (col, mk, filled, _lab, size)) in enumerate(pts.items()):
            if p not in pol:
                continue
            ax.scatter(
                [pol[p]["cal_per_qday"]],
                [100 * pol[p]["failed"]],
                s=size,
                marker=mk,
                facecolor=col if filled else SURFACE,
                edgecolor=col,
                linewidth=1.6,
                zorder=3 + z,
            )
        ax.set_xscale("log")
        ax.set_xlim(0.2, 14)
        ax.set_ylim(-0.04 * top, top)  # points at zero stay visible above the axis
        ax.set_title(
            f"{sc}: {c['scenario_specs'][sc]['drift_per_day']:g} gradual + {c['scenario_specs'][sc]['jump_per_day']:g} abrupt / qubit-day",
            fontsize=8,
        )
        ax.set_xlabel("calibrations per qubit-day")
    axes[0].set_ylabel("jobs run above 5% error (%)")
    handles = [plt.Line2D([], [], color=MUTED, marker="o", ms=4, lw=1.5, label="fixed schedules (frontier)")]
    for _p, (col, mk, filled, lab, _size) in pts.items():
        handles.append(
            plt.Line2D(
                [],
                [],
                ls="",
                marker=mk,
                ms=7,
                markerfacecolor=col if filled else SURFACE,
                markeredgecolor=col,
                mew=1.6,
                label=lab,
            )
        )
    fig.legend(handles=handles, loc="lower center", ncol=4, fontsize=8, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle(
        "Experiment I (simulation): warning-triggered recalibration vs fixed schedules", fontsize=10, color=INK, y=1.0
    )
    fig.tight_layout(rect=(0, 0.12, 1, 0.96))
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def fig_workload(plt, e, path: Path) -> None:
    s = e["summary"]
    scen = ["G0", "G1", "G2", "G3", "G4", "G5", "G6"]
    names = ["stable", "depth", "gate mix", "frequency", "shots/interval", "idle 2 us", "extra 2q"]
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    width = 0.36
    for k, (arch, col, lab) in enumerate(
        (("v02", ORANGE, "v0.2 thresholds (every context)"), ("v03", BLUE, "v0.3 thresholds (readout probes)"))
    ):
        xs = [i + (k - 0.5) * width for i in range(len(scen))]
        rates = [s[sc][arch]["cal"]["run_false_alert"] for sc in scen]
        ys = [r["rate"] for r in rates]
        lo = [max(0.0, r["rate"] - r["ci95"][0]) for r in rates]  # Wilson bounds can sit 1e-17 off the rate
        hi = [max(0.0, r["ci95"][1] - r["rate"]) for r in rates]
        ax.bar(xs, ys, width=width * 0.9, color=col, label=lab, zorder=2)
        ax.errorbar(xs, ys, yerr=[lo, hi], fmt="none", ecolor=INK2, elinewidth=0.8, capsize=0, zorder=3)
        for x, y in zip(xs, ys):
            if y == 0:  # a zero-height bar is otherwise indistinguishable from a missing one
                ax.annotate("0", (x, 0), textcoords="offset points", xytext=(3, 1), ha="left", fontsize=7, color=INK2)
    ax.axhline(0.10, color=INK2, lw=0.8, zorder=1)
    ax.annotate(  # over G3, where no bar or interval reaches the line
        "v0.3 criterion \u2264 0.10",
        (3, 0.10),
        textcoords="offset points",
        xytext=(0, 3),
        ha="center",
        fontsize=7,
        color=INK2,
    )
    ax.set_xticks(range(len(scen)), [f"{sc}\n{n}" for sc, n in zip(scen, names)], fontsize=7.5)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("runs with a false alert")
    ax.set_title("Experiment G (simulation): workload changes on unchanged hardware, calibrated engine", fontsize=9)
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def fig_sweeps(plt, e, path: Path) -> None:
    """Left: confidently wrong T1 under drift (criteria H.C1, H.C2, H.C5/fc).
    Right: what the drift check costs on valid data (valid fits rejected, H.C3).
    Two measures, so two panels with their own scales."""
    s = e["summary"]
    designs = (
        ("sequential", ORANGE, "sequential (v0.2)"),
        ("randomized", AQUA, "random order"),
        ("interleaved", BLUE, "random order + references (v0.3)"),
    )
    panels = (
        (
            ["H11", "H11s", "H11l", "H12"],
            ["AR(1) offset\n(v0.2 D11)", "slow AR(1)\noffset", "linear offset", "T1 drift"],
            "false_confidence_rate",
            "confidently wrong T1 (fraction of fits)",
            "Measurement or T1 drifting during the sweep",
        ),
        (
            ["H1", "H2", "H3"],
            ["r = 3", "r = 1", "r = 10"],
            "not_ok_rate",
            "valid fits rejected (fraction)",
            "Valid data (cost)",
        ),
    )
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.2), gridspec_kw={"width_ratios": [4, 3]})
    width = 0.27
    for ax, (scen, names, key, ylab, title) in zip(axes, panels):
        top = 0.0
        for k, (d, col, _lab) in enumerate(designs):
            xs = [i + (k - 1) * width for i in range(len(scen))]
            ys = [s[f"{sc}/{d}"][key] for sc in scen]
            top = max(top, *ys)
            ax.bar(xs, ys, width=width * 0.9, color=col, zorder=2)
            for x, y in zip(xs, ys):
                if y == 0:  # a zero-height bar is otherwise indistinguishable from a missing one
                    ax.annotate(
                        "0", (x, 0), textcoords="offset points", xytext=(0, 2), ha="center", fontsize=7, color=INK2
                    )
        ax.axhline(0.10, color=INK2, lw=0.8, zorder=1)
        ax.annotate(
            "v0.3 criterion \u2264 0.10",
            (len(scen) - 0.5, 0.10),
            textcoords="offset points",
            xytext=(-2, 3),
            ha="right",
            fontsize=7,
            color=INK2,
        )
        ax.set_ylim(0, max(0.13, 1.08 * top))
        ax.set_xticks(range(len(scen)), names, fontsize=7.5)
        ax.set_ylabel(ylab, fontsize=8.5)
        ax.set_title(title, fontsize=8.5)
    handles = [plt.Rectangle((0, 0), 1, 1, color=col, label=lab) for _d, col, lab in designs]
    fig.legend(handles=handles, loc="lower center", ncol=3, fontsize=8, bbox_to_anchor=(0.5, -0.01))
    fig.suptitle("Experiment H (simulation): T1 fits by acquisition design", fontsize=9.5, color=INK, y=1.0)
    fig.tight_layout(rect=(0, 0.08, 1, 0.97))
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", default=str(ROOT / "results"))
    ap.add_argument("--out", default=str(ROOT / "paper" / "figures"))
    ap.add_argument("--allow-smoke", action="store_true")
    a = ap.parse_args(argv)
    plt = setup()
    L = latest(Path(a.results_dir), a.allow_smoke)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    made = []
    if "V03_G_workload_probes" in L:
        fig_workload(plt, L["V03_G_workload_probes"], out / "fig8_workload_thresholds.png")
        made.append("fig8")
    if "V03_H_sweep_drift" in L:
        fig_sweeps(plt, L["V03_H_sweep_drift"], out / "fig9_sweep_designs.png")
        made.append("fig9")
    if "V03_I_operational" in L:
        fig_operational(plt, L["V03_I_operational"], out / "fig10_operational_frontier.png")
        made.append("fig10")
    print("made", made)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
