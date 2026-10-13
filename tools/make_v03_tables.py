"""Generate results/V03_TABLES.md from the recorded v0.3 runs (no hand-copied numbers).

python tools/make_v03_tables.py [--results-dir DIR] [--out FILE]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTS = ("V03_G_workload_probes", "V03_H_sweep_drift", "V03_I_operational", "V03_P_pilot")


def latest(results: Path, allow_smoke: bool) -> dict:
    out = {}
    for line in (results / "runs.jsonl").read_text().splitlines():
        if line.strip():
            e = json.loads(line)
            smoke = (
                e.get("config", {}).get("smoke")
                or "SMOKE" in e.get("notes", "")
                or e.get("config", {}).get("rehearsal")
            )
            if e["experiment"] in EXPERIMENTS and (allow_smoke or not smoke):
                out[e["experiment"]] = e
    return out


def ci(r) -> str:
    return f"{r['rate']:.3f} [{r['ci95'][0]:.3f}, {r['ci95'][1]:.3f}] ({r['k']}/{r['n']})"


def f(x, nd=3) -> str:
    if x is None:
        return "-"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, (int, float)):
        return f"{x:.{nd}f}"
    return str(x)


def criteria_table(e) -> list[str]:
    rows = ["| Criterion | Description | Observed | Required | Result |", "|---|---|---|---|---|"]
    for c in e["criteria"]:
        desc = c["description"].replace("|", "\\|")
        rows.append(
            f"| {c['name']} | {desc} | {c['observed']:.4g} | {c['comparison']} {c['threshold']:g} | "
            f"{'PASS' if c['passed'] else 'FAIL'} |"
        )
    return rows


def g_tables(e) -> list[str]:
    s = e["summary"]
    out = [f"## Experiment G — workload changes with readout probes (`{e['run_id']}`)", ""]
    out += [
        "Run-level false-alert rate, Wilson 95% interval (k/n). `v02`: thresholds on every effective-flip "
        "context; `v03`: threshold on MEASURED readout probes only.",
        "",
        "| Scenario | v02 anytime | v02 calibrated | v03 anytime | v03 calibrated |",
        "|---|---|---|---|---|",
    ]
    for sc in ("G0", "G1", "G2", "G3", "G4", "G5", "G6"):
        r = s[sc]
        out.append(
            f"| {sc} | {ci(r['v02']['anytime']['run_false_alert'])} | {ci(r['v02']['cal']['run_false_alert'])} | "
            f"{ci(r['v03']['anytime']['run_false_alert'])} | {ci(r['v03']['cal']['run_false_alert'])} |"
        )
    out += ["", "Which channel raised the calibrated false alerts (fraction of runs):", ""]
    out += [
        "| Scenario | arch | drift | threshold | forecast | effective flip | readout probes |",
        "|---|---|---|---|---|---|---|",
    ]
    for sc in ("G0", "G1", "G2", "G3", "G4", "G5", "G6"):
        for arch in ("v02", "v03"):
            r = s[sc][arch]["cal"]
            ch = r["run_false_alert_by_channel"]
            bm = r["run_false_alert_by_metric"]
            out.append(
                f"| {sc} | {arch} | {ch['drift']['rate']:.3f} | {ch['threshold']['rate']:.3f} | "
                f"{ch['forecast']['rate']:.3f} | {bm.get('effective_flip_rate', 0):.3f} | {bm.get('readout_error', 0):.3f} |"
            )
    g7, g8 = s["G7"], s["G8"]
    out += ["", "| G7 (readout x1.5 at the workload change) | v02 cal | v03 cal |", "|---|---|---|"]
    out.append(
        f"| q0 detected within 6 batches | {ci(g7['v02']['cal']['q0_detected_within_6'])} | {ci(g7['v03']['cal']['q0_detected_within_6'])} |"
    )
    out.append(f"| ... by the readout probes | - | {ci(g7['v03']['cal']['q0_readout_detected_within_6'])} |")
    out.append(
        f"| false alert (q0 before the change, any q1) | {ci(g7['v02']['cal']['false_alert'])} | {ci(g7['v03']['cal']['false_alert'])} |"
    )
    out += [
        "",
        "| G8 (readout ramp 2 -> 6%) | v02 anytime | v02 cal | v03 anytime | v03 cal |",
        "|---|---|---|---|---|",
    ]
    out.append(
        "| early detection | "
        + " | ".join(ci(g8[a][m]["early_detection"]) for a in ("v02", "v03") for m in ("anytime", "cal"))
        + " |"
    )
    out.append(
        "| median lead (min) | "
        + " | ".join(f(g8[a][m]["median_lead_min"], 1) for a in ("v02", "v03") for m in ("anytime", "cal"))
        + " |"
    )
    out += ["", *criteria_table(e), ""]
    return out


def h_tables(e) -> list[str]:
    s = e["summary"]
    out = [f"## Experiment H — T1 sweeps under measurement drift (`{e['run_id']}`)", ""]
    out += [
        "Per scenario and design: not-OK rate / false-confidence rate / coverage among OK.",
        "",
        "| Scenario | sequential (v0.2) | randomized | interleaved (v0.3) |",
        "|---|---|---|---|",
    ]
    for sc in e["config"]["scenarios"]:
        cells = []
        for d in ("sequential", "randomized", "interleaved"):
            r = s.get(f"{sc}/{d}")
            cells.append(
                "-"
                if r is None
                else f"{r['not_ok_rate']:.3f} / {r['false_confidence_rate']:.3f} / {f(r['coverage_among_ok'])}"
            )
        out.append(f"| {sc} | " + " | ".join(cells) + " |")
    out += ["", "Reason codes, interleaved design:", ""]
    for sc in e["config"]["scenarios"]:
        r = s.get(f"{sc}/interleaved")
        if r:
            out.append(f"- {sc}: {r['reason_codes']}")
    out += ["", *criteria_table(e), ""]
    return out


def i_tables(e) -> list[str]:
    s = e["summary"]
    c = e["config"]
    out = [f"## Experiment I — operational value (`{e['run_id']}`)", ""]
    out += [
        f"{c['n_runs']} runs x {c['days']:g} days x {c['n_qubits']} qubits per scenario. Failed = fraction of jobs run on a "
        "qubit whose true error was above 5%; calibrations per qubit-day (the start-of-run calibration is not counted).",
        "",
    ]
    pols = list(next(iter(s.values()))["policies"])
    out.append("| Policy | " + " | ".join(f"{sc} failed / cal" for sc in c["scenarios"]) + " |")
    out.append("|---|" + "---|" * len(c["scenarios"]))
    for p in pols:
        out.append(
            f"| {p} | "
            + " | ".join(
                f"{s[sc]['policies'][p]['failed']:.4f} / {s[sc]['policies'][p]['cal_per_qday']:.2f}"
                for sc in c["scenarios"]
            )
            + " |"
        )
    out += ["", "Contrasts against the fixed-schedule frontier (95% paired bootstrap intervals):", ""]
    out.append("| Scenario | Policy | failed - frontier at same calibrations | calibrations saved per qubit-day |")
    out.append("|---|---|---|---|")
    for sc in c["scenarios"]:
        for m, v in s[sc]["contrasts"].items():
            a = v["failed_minus_frontier"]
            aci = v["failed_minus_frontier_ci95"]
            b = v["calibrations_saved_per_qday"]
            bci = v["calibrations_saved_ci95"]
            bound = " (lower bound)" if v["savings_is_lower_bound"] else ""
            out.append(
                f"| {sc} | {m} | {f(a, 4)} [{f(aci[0], 4) if aci else '-'}, {f(aci[1], 4) if aci else '-'}] | "
                f"{f(b, 2)}{bound} [{f(bci[0], 2) if bci else '-'}, {f(bci[1], 2) if bci else '-'}] |"
            )
    out += [
        "",
        "Triggered calibrations per qubit-day by the true state at the trigger (above threshold / degraded / false):",
        "",
    ]
    out.append("| Policy | " + " | ".join(c["scenarios"]) + " |")
    out.append("|---|" + "---|" * len(c["scenarios"]))
    for p in c["monitor_policies"]:
        cells = []
        for sc in c["scenarios"]:
            r = s[sc]["policies"][p]
            cells.append(
                f"{r['triggered_above_per_qday']:.2f} / {r['triggered_degraded_per_qday']:.2f} / {r['triggered_false_per_qday']:.2f}"
            )
        out.append(f"| {p} | " + " | ".join(cells) + " |")
    out += ["", "Paired differences (policy a - policy b), 95% bootstrap intervals:", ""]
    out.append("| Scenario | a - b | failed | calibrations per qubit-day |")
    out.append("|---|---|---|---|")
    for sc in c["scenarios"]:
        for k, v in s[sc]["paired"].items():
            fci, cci = v["failed_diff_ci95"], v["cal_diff_ci95"]
            out.append(
                f"| {sc} | {k} | {v['failed_diff']:+.4f} [{fci[0]:+.4f}, {fci[1]:+.4f}] | "
                f"{v['cal_diff']:+.2f} [{cci[0]:+.2f}, {cci[1]:+.2f}] |"
            )
    out += ["", *criteria_table(e), ""]
    return out


def p_tables(e) -> list[str]:
    s = e["summary"]
    out = [f"## Experiment P — hardware pilot (`{e['run_id']}`)", ""]
    if e["config"].get("rehearsal"):
        out += ["**Rehearsal on a fake backend (local simulation): not hardware evidence.**", ""]
    out += [f"Backend `{s['backend']}`, qubits {s['qubits']}; timing {s['timing']}.", "", *criteria_table(e), ""]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", default=str(ROOT / "results"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--allow-smoke", action="store_true")
    a = ap.parse_args(argv)
    results = Path(a.results_dir)
    L = latest(results, a.allow_smoke)
    out = [
        "# v0.3 result tables",
        "",
        "Generated by `tools/make_v03_tables.py` from `results/runs.jsonl`; do not edit by hand.",
        "",
    ]
    total = sum(len(e["criteria"]) for e in L.values() if not e["experiment"].endswith("pilot"))
    passed = sum(sum(c["passed"] for c in e["criteria"]) for e in L.values() if not e["experiment"].endswith("pilot"))
    out += [f"**Preregistered simulation criteria (G, H, I): {passed} of {total} passed.**", ""]
    for name, fn in (
        ("V03_G_workload_probes", g_tables),
        ("V03_H_sweep_drift", h_tables),
        ("V03_I_operational", i_tables),
        ("V03_P_pilot", p_tables),
    ):
        if name in L:
            out += fn(L[name])
    text = "\n".join(out) + "\n"
    Path(a.out or results / "V03_TABLES.md").write_text(text)
    print(f"wrote {a.out or results / 'V03_TABLES.md'}: {passed}/{total} criteria passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
