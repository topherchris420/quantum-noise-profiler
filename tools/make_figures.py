"""Publication figures from recorded results only (results/runs.jsonl + raw).

    python tools/make_figures.py [--results-dir results] [--out paper/figures]

Every number plotted is read from a recorded run; nothing is simulated here.
Uses the latest non-smoke entry of each experiment.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

from v02.compact import first_true, method_alarms  # noqa: E402

# Reference categorical palette (validated: adjacent CVD dE >= 9.1, normal >= 19.6);
# slots 3-5 are below 3:1 on the surface, so every series is also direct-labelled.
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = {"v02": "#2a78d6", "v02cal": "#eb6834", "shewhart": "#1baf7a", "cusum": "#eda100", "v01": "#e87ba4"}
LABEL = {
    "v02": "v0.2 anytime-valid",
    "v02cal": "v0.2 calibrated",
    "shewhart": "Shewhart (calibrated)",
    "cusum": "CUSUM (calibrated)",
    "v01": "v0.1",
    "v01cal": "v0.1 re-thresholded",
    "naive": "naive threshold",
}


def setup():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": INK2,
            "axes.labelcolor": INK,
            "xtick.color": INK2,
            "ytick.color": INK2,
            "text.color": INK,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "font.size": 9,
            "axes.titlesize": 10,
            "legend.frameon": False,
            "lines.linewidth": 2.0,
            "figure.dpi": 150,
        }
    )
    return plt


def load(results: Path):
    entries = [json.loads(x) for x in (results / "runs.jsonl").read_text().splitlines() if x.strip()]
    latest = {}
    for e in entries:
        if e.get("config", {}).get("smoke") or "SMOKE" in e.get("notes", ""):
            continue
        latest[e["experiment"]] = e
    return latest


def trials(results: Path, e):
    p = results / "raw" / Path(e["raw"]).name
    txt = gzip.decompress(p.read_bytes()).decode() if p.suffix == ".gz" else p.read_text()
    return [json.loads(x) for x in txt.splitlines() if x.strip()]


def params(e):
    p = dict(e["config"]["calibrated"])
    p.update(shots_per_batch=e["config"]["shots_per_batch"], ref=e["config"]["ref"], threshold=0.05)
    return p


def dodge(values, gap):
    """Spread label positions so neighbours are at least ``gap`` apart, keeping order."""
    order = np.argsort(values)
    out = np.array(values, float)
    for k in range(1, len(order)):
        a, b = order[k - 1], order[k]
        if out[b] - out[a] < gap:
            out[b] = out[a] + gap
    return out


def end_labels(ax, xs, ys, texts, gap):
    for x, y, yl, t in zip(xs, ys, dodge(ys, gap), texts):
        ax.annotate(
            t,
            (x, y),
            xytext=(x * 1.03, yl),
            textcoords="data",
            fontsize=7,
            color=INK2,
            va="center",
            arrowprops={"arrowstyle": "-", "color": INK2, "lw": 0.4} if abs(yl - y) > 1e-9 else None,
        )


def fig_trajectory(plt, R, latest, out):
    from scipy import stats as sps

    e = latest["V02_B_gradual"]
    t = [t for t in trials(R, e) if t["cond"] == "B1"][0]
    spb = e["config"]["shots_per_batch"]
    rates = np.array([row[0] for row in t["naive"]])
    k = np.round(rates * spb)
    lo = sps.beta.ppf(0.025, k + 0.5, spb - k + 0.5)
    hi = sps.beta.ppf(0.975, k + 0.5, spb - k + 0.5)
    x = np.arange(len(rates)) * e["config"]["batch_minutes"] / 60
    truth = np.linspace(*e["config"]["conditions"]["B1"]["ramp"], len(rates))
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    ax.fill_between(x, lo, hi, color=SERIES["v02"], alpha=0.18, linewidth=0, label="95% credible interval")
    ax.plot(x, rates, color=SERIES["v02"], lw=1.5, label="per-batch estimate, qubit 0")
    ax.plot(x, truth, color=INK2, lw=1.2, ls="--", label="injected rate")
    ax.axhline(0.05, color=INK, lw=1, ls=":")
    ax.text(x[0], 0.0505, "threshold 5%", fontsize=8, color=INK2, va="bottom", ha="left")
    p = params(e)
    for row, m in enumerate(("v02", "v02cal", "shewhart", "cusum")):
        i = first_true(method_alarms(t, 0, m, p), 0, None, t["v02"]["i"])
        yy = 0.0135 - 0.0026 * row
        if i is not None:
            ax.plot(
                [x[i]],
                [yy],
                marker="v",
                ms=8,
                color=SERIES[m],
                markeredgecolor=SURFACE,
                markeredgewidth=1,
                linestyle="none",
            )
            ax.text(x[i] + 0.1, yy, f"first alert: {LABEL[m]} ({x[i]:.1f} h)", fontsize=7, color=INK2, va="center")
        else:
            ax.text(0.05, yy, f"{LABEL[m]}: no alert", fontsize=7, color=INK2, va="center")
    i_cross = e["config"]["conditions"]["B1"]["i_cross"] * e["config"]["batch_minutes"] / 60
    ax.axvline(i_cross, color=INK, lw=1)
    ax.text(i_cross, 0.066, " true crossing", fontsize=8, color=INK2)
    ax.set_ylim(0.004, None)
    ax.set_xlabel("monitoring time (h)")
    ax.set_ylabel("effective flip rate")
    ax.set_title("Fig. 1 - Drift trajectory and first alerts (Experiment B1, first run)", loc="left")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(out / "fig1_trajectory.png")
    plt.close(fig)


def _fa_and_lead(a_ts, b_ts, method, key, values, p, cfg):
    pts = []
    for v in values:
        pp = dict(p)
        pp[key] = v
        fa = np.mean([any(any(method_alarms(t, q, method, pp)) for q in (0, 1)) for t in a_ts])
        ic = cfg["conditions"]["B1"]["i_cross"]
        leads = []
        for t in b_ts:
            i = first_true(method_alarms(t, 0, method, pp), 0, None, t["v02"]["i"])
            if i is not None:
                leads.append((ic - i) * cfg["batch_minutes"])
        pts.append((fa, np.median(leads) if leads else np.nan, v))
    return pts


def fig_operating(plt, R, latest, out):
    ea, eb = latest["V02_A_false_alarm"], latest["V02_B_gradual"]
    a_ts = [t for t in trials(R, ea) if t["cond"] == "A3"]
    b_ts = [t for t in trials(R, eb) if t["cond"] == "B1"]
    p = params(eb)
    curves = {
        "v02cal": ("c_star", [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.25]),
        "shewhart": ("k_star", [2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5]),
        "cusum": ("h_star", [6, 10, 15, 20, 25, 30, 40]),
    }
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    rows, labs = [], []
    for m, (key, vals) in curves.items():
        pts = sorted(_fa_and_lead(a_ts, b_ts, m, key, vals, p, eb["config"]))
        ax.plot([q[0] for q in pts], [q[1] for q in pts], "-o", color=SERIES[m], ms=4, lw=1.5)
        cal = _fa_and_lead(a_ts, b_ts, m, key, [p[key]], p, eb["config"])[0]
        ax.plot([cal[0]], [cal[1]], "s", ms=9, color=SERIES[m], markeredgecolor=SURFACE, markeredgewidth=2)
        labs.append((cal[0], cal[1], f"{LABEL[m]} ({key[0]}*={p[key]}): FA {cal[0]:.2f}, lead {cal[1]:.0f} min"))
        rows.append((m, cal))
    ylab = dodge([q[1] for q in labs], 9.0)
    xmax = max(ax.get_xlim()[1], 0.3)
    for (x0, y0, t), yl in zip(labs, ylab):
        ax.annotate(
            t,
            (x0, y0),
            xytext=(0.35 * xmax, yl),
            textcoords="data",
            fontsize=7,
            color=INK2,
            va="center",
            arrowprops={"arrowstyle": "-", "color": INK2, "lw": 0.4},
        )
    ax.axvline(0.10, color=INK, lw=1, ls=":")
    ax.text(0.103, ax.get_ylim()[0], "10% budget", fontsize=8, color=INK2, va="bottom")
    ax.set_xlabel("run-level false-alert probability (Experiment A3: q0 at 4.5%, 8 h)")
    ax.set_ylabel("median warning lead (min, Experiment B1)")
    ax.set_title("Fig. 2 - Lead time versus false-alert probability (squares: calibrated settings)", loc="left")
    fig.tight_layout()
    fig.savefig(out / "fig2_lead_vs_false_alert.png")
    plt.close(fig)
    return rows


def fig_accumulation(plt, R, latest, out):
    e = latest["V02_A_false_alarm"]
    allt = trials(R, e)
    p = params(e)
    fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.3), sharey=True)
    for ax, cond, title in ((axes[0], "A3", "A3: q0 at 4.5%, 8 h"), (axes[1], "A5", "A5: both at 2%, 24 h")):
        ts = [t for t in allt if t["cond"] == cond]
        n = ts[0]["n_batches"]
        hours = np.arange(1, n + 1) * e["config"]["batch_minutes"] / 60
        ends = []
        for m in ("v01", "v02", "v02cal", "shewhart", "cusum"):
            pool = [t for t in ts if t.get("v01") is not None] if m == "v01" else ts
            if not pool:
                continue
            firsts = []
            for t in pool:
                fi = [first_true(method_alarms(t, q, m, p), 0, None, t["v02"]["i"]) for q in (0, 1)]
                fi = [x for x in fi if x is not None]
                firsts.append(min(fi) if fi else None)
            cum = [np.mean([f is not None and f <= i for f in firsts]) for i in range(n)]
            ax.plot(hours, cum, color=SERIES[m], lw=1.8)
            ends.append((hours[-1], cum[-1], f"{LABEL[m]} {cum[-1]:.2f}"))
        end_labels(ax, [a for a, _, _ in ends], [b for _, b, _ in ends], [c for _, _, c in ends], 0.075)
        ax.axhline(0.10, color=INK, lw=1, ls=":")
        ax.set_title(title, loc="left")
        ax.set_xlabel("monitoring time (h)")
        ax.set_xlim(0, hours[-1] * 1.6)
    axes[0].set_ylabel("runs with >= 1 false alert")
    fig.suptitle(
        "Fig. 3 - Sequential accumulation of false alerts (dotted: 10% budget)", x=0.01, ha="left", fontsize=10
    )
    fig.tight_layout()
    fig.savefig(out / "fig3_false_alert_accumulation.png")
    plt.close(fig)


def fig_fits(plt, R, latest, out):
    e = latest["V02_D_misspecification"]
    s = e["summary"]
    names = {
        "D1": "single exp, r=3",
        "D2": "single exp, r=1",
        "D3": "single exp, r=10",
        "D4": "short range r=0.2",
        "D5": "short range r=0.05",
        "D6": "fluctuating T1 s=0.3",
        "D7": "fluctuating T1 s=0.1",
        "D8": "bi-exponential 70/30",
        "D9": "bi-exponential 90/10",
        "D10": "heavy-tailed noise",
        "D11": "correlated readout drift",
        "D12": "T1 drifts in sweep",
        "D13": "Aer thermal relaxation",
    }
    order = list(names)[::-1]
    fig, ax = plt.subplots(figsize=(6.6, 4.0))
    cols = {
        "ok": SERIES["v02"],
        "insufficient_evidence": SERIES["shewhart"],
        "model_misspecification": SERIES["v02cal"],
    }
    lab = {
        "ok": "OK (value reported)",
        "insufficient_evidence": "INSUFFICIENT_EVIDENCE",
        "model_misspecification": "MODEL_MISSPECIFICATION",
    }
    for j, sc in enumerate(order):
        left = 0.0
        for k in ("ok", "insufficient_evidence", "model_misspecification"):
            w = s[sc][k] / s[sc]["n"]
            ax.barh(
                j,
                w,
                left=left,
                color=cols[k],
                height=0.7,
                edgecolor=SURFACE,
                linewidth=2,
                label=lab[k] if j == 0 else None,
            )
            left += w
        fc = s[sc]["false_confidence_rate"]
        txt = f"value reported {fc:.2f}" if sc in ("D8", "D9") else f"false conf. {fc:.2f}"
        ax.text(1.02, j, txt, va="center", fontsize=7, color=INK2)
    ax.set_yticks(range(len(order)), [f"{k} {names[k]}" for k in order], fontsize=8)
    ax.set_xlim(0, 1.32)
    ax.set_xlabel("fraction of fits")
    ax.legend(loc="lower center", bbox_to_anchor=(0.45, 1.0), ncol=3, fontsize=7)
    ax.set_title("Fig. 4 - T1 fit outcomes (Experiment D)", loc="left", pad=22)
    fig.tight_layout()
    fig.savefig(out / "fig4_fit_diagnostics.png")
    plt.close(fig)


def fig_forecast(plt, R, latest, out):
    e = latest["V02_B_gradual"]
    allt = trials(R, e)
    fig, ax = plt.subplots(figsize=(5.0, 4.0))
    cov, n = 0, 0
    for cond, mk in (("B1", "o"), ("B2", "^")):
        ic = e["config"]["conditions"][cond]["i_cross"]
        xs, ys, lo, hi = [], [], [], []
        for t in [t for t in allt if t["cond"] == cond]:
            for i, log_e, med, p10, p90, fb in t["v02"]["fc"]:
                if log_e is None or log_e < fb or i >= ic or med is None:
                    continue
                truth = (ic - i) * e["config"]["batch_minutes"] / 60
                xs.append(truth)
                ys.append(med)
                lo.append(p10)
                hi.append(p90 if p90 is not None else math.inf)
                cov += p10 <= truth <= (p90 if p90 is not None else math.inf)
                n += 1
        xs, ys = np.array(xs), np.array(ys)
        sel = np.arange(len(xs))[:: max(1, len(xs) // 150)]
        ax.errorbar(
            xs[sel],
            ys[sel],
            yerr=[ys[sel] - np.array(lo)[sel], np.minimum(np.array(hi)[sel], 20) - ys[sel]],
            fmt=mk,
            ms=3,
            color=SERIES["v02"] if cond == "B1" else SERIES["v02cal"],
            elinewidth=0.6,
            alpha=0.7,
            label=f"{cond} forecasts (80% predictive interval)",
        )
    m = max(ax.get_xlim()[1], 1)
    ax.set_ylim(0, 1.8 * m)
    ax.text(
        0.02 * m,
        1.75 * m,
        "interval upper ends beyond the plot are open (no crossing in some draws)",
        fontsize=7,
        color=INK2,
        va="top",
    )
    ax.plot([0, m], [0, m], color=INK2, lw=1, ls="--")
    ax.text(0.98 * m, 0.98 * m, "perfect", fontsize=8, color=INK2, ha="right", va="bottom")
    ax.set_xlabel("true time to threshold crossing (h)")
    ax.set_ylabel("forecast median (h)")
    ax.set_title(f"Fig. 5 - Forecast calibration: 80% intervals cover {cov}/{n} = {cov / max(n, 1):.2f}", loc="left")
    ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(0, 0.93))
    fig.tight_layout()
    fig.savefig(out / "fig5_forecast_calibration.png")
    plt.close(fig)
    return cov, n


def fig_workload(plt, R, latest, out):
    e = latest["V02_E_workload_shift"]
    s = e["summary"]
    scs = ["E1", "E2", "E3", "E4", "E5", "E6"]
    names = ["depth", "gate mix", "frequencies", "schedule", "idle time", "2q gates"]
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    w = 0.38
    for k, (mode, col) in enumerate((("bucket", SERIES["v02cal"]), ("exact", SERIES["v02"]))):
        r = [s[sc][mode]["v02cal"]["run_false_alert"] for sc in scs]
        x = np.arange(len(scs)) + (k - 0.5) * w
        ax.bar(x, [q["rate"] for q in r], width=w - 0.04, color=col, label=f"{mode} contexts")
        ax.errorbar(
            x,
            [q["rate"] for q in r],
            yerr=[[max(0.0, q["rate"] - q["ci95"][0]) for q in r], [max(0.0, q["ci95"][1] - q["rate"]) for q in r]],
            fmt="none",
            ecolor=INK2,
            elinewidth=0.8,
            capsize=2,
        )
        for xi, q in zip(x, r):
            ax.text(xi, q["ci95"][1] + 0.02, f"{q['rate']:.2f}", ha="center", fontsize=7, color=INK2)
    ax.axhline(0.10, color=INK, lw=1, ls=":")
    ax.set_xticks(range(len(scs)), [f"{a}\n{b}" for a, b in zip(scs, names)], fontsize=8)
    ax.set_ylim(0, 1.12)
    ax.set_ylabel("runs with a false alert (v0.2 calibrated)")
    ax.set_title("Fig. 6 - Workload changes on unchanged hardware (Experiment E)", loc="left", pad=26)
    ax.legend(fontsize=8, loc="lower center", bbox_to_anchor=(0.5, 1.06), ncol=2)
    fig.tight_layout()
    fig.savefig(out / "fig6_workload_shift.png")
    plt.close(fig)


def fig_v01_v02(plt, latest, out):
    e1, e2, e3 = latest["E1_gradual_drift"], latest["E2_matched_comparison"], latest["E3_insufficient_evidence"]
    a, c, d = latest["V02_A_false_alarm"], latest["V02_C_abrupt"], latest["V02_D_misspecification"]
    rows = [
        (
            "false alerts, q0 at 4.5%\n(E1 control / A3)",
            e1["summary"]["control_profiler_any_alert_rate"],
            a["summary"]["A3"]["v02cal"]["run_false_alert"]["rate"],
        ),
        (
            "false alerts, 2% step study\n(E2 matched / C pooled)",
            e2["summary"]["profiler_v01_warn"]["run_false_alarm"]["rate"],
            c["summary"]["pooled_run_false_alert"]["v02cal"]["rate"],
        ),
        (
            "x1.2 step detected\n(E2 / C, within 24)",
            e2["summary"]["profiler_v01_warn"]["x1.2"]["within_24"],
            c["summary"]["x1.2"]["v02cal"]["within_24"]["rate"],
        ),
        (
            "false confidence,\nfluctuating T1 (E3 / D6)",
            e3["summary"]["E3d"]["fluctuating_T1"]["false_confidence_rate"],
            d["summary"]["D6"]["false_confidence_rate"],
        ),
        (
            "abstention,\nbi-exponential (E3 / D8)",
            e3["summary"]["E3d"]["bi_exponential"]["abstention_rate"],
            d["summary"]["D8"]["not_ok_rate"],
        ),
    ]
    fig, ax = plt.subplots(figsize=(6.8, 3.4))
    x = np.arange(len(rows))
    w = 0.38
    for k, (name, col) in enumerate((("v0.1", SERIES["v01"]), ("v0.2 (calibrated)", SERIES["v02"]))):
        vals = [r[1 + k] for r in rows]
        xx = x + (k - 0.5) * w
        ax.bar(xx, vals, width=w - 0.04, color=col, label=name)
        for xi, v in zip(xx, vals):
            ax.text(xi, v + 0.02, f"{v:.2f}", ha="center", fontsize=7, color=INK2)
    ax.set_xticks(x, [r[0] for r in rows], fontsize=7)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("rate")
    ax.set_title("Fig. 7 - v0.1 versus v0.2 on the matched questions (different seeds; see text)", loc="left")
    ax.legend(fontsize=8, loc="upper center", ncol=2)
    fig.tight_layout()
    fig.savefig(out / "fig7_v01_vs_v02.png")
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", default=str(ROOT / "results"))
    ap.add_argument("--out", default=str(ROOT / "paper" / "figures"))
    args = ap.parse_args(argv)
    R, out = Path(args.results_dir), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    plt = setup()
    latest = load(R)
    fig_trajectory(plt, R, latest, out)
    fig_operating(plt, R, latest, out)
    fig_accumulation(plt, R, latest, out)
    fig_fits(plt, R, latest, out)
    cov = fig_forecast(plt, R, latest, out)
    fig_workload(plt, R, latest, out)
    if "E1_gradual_drift" in latest:
        fig_v01_v02(plt, latest, out)
    print("figures written to", out, "| forecast coverage", cov)


if __name__ == "__main__":
    main()
