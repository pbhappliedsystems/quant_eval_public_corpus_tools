#!/usr/bin/env python3
"""Generate the four quant_eval corpus figures from rollup.json values only.

No value is recomputed, smoothed, or derived. Every plotted number is read
directly from the six publication bundles' rollup.json files. Figure 4 also
reads the accelerator on each lane from the hardware map, the same declaration
build_datasets.py requires for D7 (v1.0.1 onward).

    python3 make_figures.py --bundles-file corpus_runs.txt \
                            --hardware-map hardware_map.txt \
                            --runs-root /mnt/e/QUANT_EVAL/runs --out figures

Each figure is written as SVG (whitepaper, this repo) and 200-dpi PNG (dataset
cards). Regenerate, never hand-edit.
"""
import argparse
import json
import os
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

# The six corpus runs and the short key each figure uses for them.
KEY = {
    "Mistral_Nemo_Instruct_2407_20260814_030505": "Q4_K_M",
    "Mistral_Nemo_Instruct_2407_20260815_113254": "Q5_K_M",
    "Mistral_Nemo_Instruct_2407_20260816_084553": "Q8_0",
    "Qwen2.5_7B_Instruct_20260814_234822": "7B",
    "Qwen2.5_14B_Instruct_1M_20260815_220633": "14B-1M",
    "Qwen2.5_32B_Instruct_20260815_081051": "32B",
}
# Display names for the accelerator tokens used in hardware_map.txt and D7.
ACCEL = {
    "nvidia_geforce_rtx_4090": "RTX 4090",
    "nvidia_a100_40gb": "A100-40GB",
    "nvidia_a100_80gb": "A100-80GB",
    "nvidia_a10g": "A10G",
    "nvidia_t4": "T4",
    "nvidia_l4": "L4",
    "nvidia_h100": "H100",
}


def die(msg):
    sys.exit("make_figures.py: " + msg)


def read_list(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if line:
                out.append(line)
    return out


def rollup_path(entry, runs_root):
    p = entry if os.path.isabs(entry) else os.path.join(runs_root, entry)
    if os.path.basename(os.path.normpath(p)) != "publication":
        p = os.path.join(p, "publication")
    return os.path.join(p, "rollup.json")


def read_hardware_map(path):
    """RUN_ID BASELINE_ACCELERATOR QUANTIZED_ACCELERATOR, one run per line
    (build_datasets.py format). hardware_matched_pair is computed from the two
    tokens, never declared."""
    hw = {}
    for n, line in enumerate(read_list(path), 1):
        parts = line.split()
        if len(parts) != 3:
            die(f"{path}: line {n}: expected 3 fields, got {len(parts)}")
        hw[parts[0]] = (parts[1], parts[2])
    return hw


ap = argparse.ArgumentParser(description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--bundles-file", default="corpus_runs.txt")
ap.add_argument("--hardware-map", default="hardware_map.txt")
ap.add_argument("--runs-root", default="/mnt/e/QUANT_EVAL/runs")
ap.add_argument("--out", default="figures")
args = ap.parse_args()

OUT = args.out
os.makedirs(OUT, exist_ok=True)

BUNDLES = {}
for entry in read_list(args.bundles_file):
    rid = os.path.basename(os.path.normpath(entry))
    if rid == "publication":
        rid = os.path.basename(os.path.dirname(os.path.normpath(entry)))
    if rid not in KEY:
        die(f"run {rid} is not one of the six corpus runs this script plots")
    BUNDLES[KEY[rid]] = (rid, rollup_path(entry, args.runs_root))
if set(BUNDLES) != set(KEY.values()):
    die("expected the six corpus runs, got: " + ", ".join(sorted(BUNDLES)))
HW = read_hardware_map(args.hardware_map)
missing = [rid for rid, _ in BUNDLES.values() if rid not in HW]
if missing:
    die("hardware map has no line for: " + ", ".join(missing))
for rid, _ in BUNDLES.values():
    for tok in HW[rid]:
        if tok not in ACCEL:
            die(f"unknown accelerator token {tok!r} for {rid}; add it to ACCEL")

FAM = ["json", "json_multistep", "mcq", "mixed_brief_json",
       "stateful_followup", "toolcall", "toolcall_only", "fuzz"]
LABEL = {"json": "json", "json_multistep": "json_multistep", "mcq": "mcq",
         "mixed_brief_json": "mixed_brief_json",
         "stateful_followup": "stateful_followup", "toolcall": "toolcall",
         "toolcall_only": "toolcall_only", "fuzz": "fuzz"}

# Okabe-Ito, colourblind-safe
C = {"Q4_K_M": "#D55E00", "Q5_K_M": "#0072B2", "Q8_0": "#009E73",
     "7B": "#CC79A7", "14B-1M": "#E69F00", "32B": "#56B4E9"}
INK = "#1a1a1a"
GRID = "#d9d9d9"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.edgecolor": INK,
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": INK,
    "ytick.color": INK,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
    "savefig.facecolor": "white",
})

D = {}
for k, (rid, p) in BUNDLES.items():
    if not os.path.isfile(p):
        die(f"missing {p}")
    o = json.load(open(p, encoding="utf-8"))
    d = {}
    for f in FAM:
        P = o["paired_runner_comparison"][f]
        ci = P["pass_rate_delta_ci"]
        d[f] = dict(delta=P["pass_rate_delta_runner_b_minus_runner_a"],
                    lo=ci["low"], hi=ci["high"],
                    p=P["mcnemar_exact"]["p_value"])
    e = o["efficiency"]
    af = e["artifact_footprint"][0]
    rc = e["runtime_comparison"]
    d["_foot"] = dict(base=af["baseline_bytes"], quant=af["quantized_bytes"],
                      comp=af["compression_ratio"],
                      red=af["size_reduction_fraction"])
    d["_rt"] = dict(v=rc["headline_runtime_metric"]["value"],
                    dirn=rc["headline_runtime_metric"].get("direction"))
    base_acc, quant_acc = HW[rid]
    d["_hw"] = dict(base=ACCEL[base_acc], quant=ACCEL[quant_acc],
                    matched=(base_acc == quant_acc))
    D[k] = d


def nsig(k):
    return sum(1 for f in FAM if D[k][f]["p"] < 0.05)


def save(fig, name):
    for ext in ("svg", "png"):
        fig.savefig(f"{OUT}/{name}.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {name}.svg / {name}.png")


def forest(keys, title, subtitle, fname, legend_title, note, legloc="upper left"):
    """Dot-and-whisker of paired delta with 95% CI, grouped by family."""
    n = len(keys)
    fig, ax = plt.subplots(figsize=(9.0, 6.4))
    offs = [(i - (n - 1) / 2) * 0.26 for i in range(n)]
    for yi, f in enumerate(FAM):
        y0 = len(FAM) - 1 - yi
        if yi % 2 == 0:
            ax.axhspan(y0 - 0.5, y0 + 0.5, color="#f5f5f5", zorder=0)
        for ki, k in enumerate(keys):
            r = D[k][f]
            y = y0 + offs[ki]
            sig = r["p"] < 0.05
            ax.plot([r["lo"], r["hi"]], [y, y], color=C[k],
                    lw=2.0 if sig else 1.2,
                    alpha=1.0 if sig else 0.55, zorder=3,
                    solid_capstyle="butt")
            ax.plot([r["lo"], r["lo"]], [y - 0.06, y + 0.06], color=C[k],
                    lw=1.6 if sig else 1.0, alpha=1.0 if sig else 0.55, zorder=3)
            ax.plot([r["hi"], r["hi"]], [y - 0.06, y + 0.06], color=C[k],
                    lw=1.6 if sig else 1.0, alpha=1.0 if sig else 0.55, zorder=3)
            ax.scatter([r["delta"]], [y], s=52 if sig else 26, color=C[k],
                       edgecolor="white" if sig else C[k],
                       linewidth=1.1, zorder=4,
                       alpha=1.0 if sig else 0.65)
    ax.axvline(0, color=INK, lw=1.0, zorder=2)
    ax.set_yticks(range(len(FAM)))
    ax.set_yticklabels([LABEL[f] for f in reversed(FAM)], fontsize=10)
    ax.set_ylim(-0.6, len(FAM) - 0.4)
    ax.set_xlabel("Paired pass-rate difference (quantized − full weight), "
                  "95% CI", fontsize=10)
    ax.grid(axis="x", color=GRID, lw=0.7, zorder=1)
    ax.set_axisbelow(True)
    handles = [Line2D([], [], color=C[k], marker="o", lw=2.0, ms=7,
                      label=k) for k in keys]
    handles += [Line2D([], [], color="#888888", marker="o", lw=1.2, ms=5,
                       alpha=0.6, label="not significant (p ≥ 0.05)")]
    leg = ax.legend(handles=handles, title=legend_title, loc=legloc,
                    frameon=True, framealpha=0.95, edgecolor=GRID,
                    fontsize=9, title_fontsize=9)
    leg.get_frame().set_linewidth(0.7)
    fig.suptitle(title, x=0.02, ha="left", fontsize=14, weight="bold", y=1.005)
    ax.set_title(subtitle, loc="left", fontsize=9, color="#555555", pad=10)
    fig.text(0.02, -0.055, note, fontsize=8, color="#666666", ha="left",
             va="top", wrap=True)
    save(fig, fname)


# ---------------------------------------------------------------- Figure 1
forest(
    ["Q4_K_M", "Q5_K_M", "Q8_0"],
    "Behavioral degradation is a cliff, not a slope",
    "Mistral-Nemo-Instruct-2407 · identical F16 baseline and fixtures\n"
    "n = 200 paired cases per family",
    "fig1_precision_curve_mistral_nemo",
    "Quantization",
    "Solid markers: two-sided exact McNemar p < 0.05. Families significant: "
    f"Q4_K_M {nsig('Q4_K_M')} of 8; Q5_K_M {nsig('Q5_K_M')} of 8; "
    f"Q8_0 {nsig('Q8_0')} of 8.\n"
    "Intervals are 95% confidence intervals on the paired difference. "
    "Source: quant_eval v7.22.22, rollup.json paired_runner_comparison.",
)

# ---------------------------------------------------------------- Figure 2
fig, ax1 = plt.subplots(figsize=(8.2, 5.0))
order = ["Q8_0", "Q5_K_M", "Q4_K_M"]
xs = [D[k]["_foot"]["red"] * 100 for k in order]
# degraded = significant (exact McNemar p < 0.05) AND the quantized lane scored lower; an improvement is not a loss
sig = [sum(1 for f in FAM if D[k][f]["p"] < 0.05 and D[k][f]["delta"] < 0) for k in order]
gb = [D[k]["_foot"]["quant"] / 1e9 for k in order]

ax1.plot(xs, sig, color="#999999", lw=1.4, zorder=2, linestyle="--")
PLACE = {"Q8_0": (0, 20, "center"), "Q5_K_M": (14, 16, "left"),
         "Q4_K_M": (0, -40, "center")}
for k, x, y, g in zip(order, xs, sig, gb):
    ax1.scatter([x], [y], s=230, color=C[k], zorder=4,
                edgecolor="white", linewidth=2)
    dx, dy, ha = PLACE[k]
    ax1.annotate(f"{k}\n{g:.2f} GB", (x, y), xytext=(dx, dy),
                 textcoords="offset points", ha=ha, fontsize=10,
                 weight="bold", color=C[k])
ax1.set_xlabel("Storage saved versus F16 (%)", fontsize=10)
ax1.set_ylabel("Task families significantly degraded\n(of 8, McNemar p < 0.05)",
               fontsize=10)
ax1.set_ylim(-1.3, 7.6)
ax1.set_xlim(42, 78)
ax1.set_yticks(range(0, 8))
ax1.grid(color=GRID, lw=0.7, zorder=1)
ax1.set_axisbelow(True)
share = 100 * D["Q5_K_M"]["_foot"]["red"] / D["Q4_K_M"]["_foot"]["red"]
ax1.annotate(f"{share:.1f}% of Q4_K_M's saving,\nnone of the damage",
             xy=(64.0, 0.28), xytext=(52.0, 3.0), fontsize=9.5,
             color="#333333", ha="center",
             arrowprops=dict(arrowstyle="->", color="#666666", lw=1.1,
                             connectionstyle="arc3,rad=-0.28"))
fig.suptitle("The entire behavioral cost is paid in one step",
             x=0.02, ha="left", fontsize=14, weight="bold", y=1.01)
ax1.set_title("Mistral-Nemo-Instruct-2407 · F16 baseline = "
              f"{D['Q4_K_M']['_foot']['base'] / 1e9:.2f} GB",
              loc="left", fontsize=10, color="#555555", pad=10)
fig.text(0.02, -0.02,
         "Storage saved is size_reduction_fraction from rollup.json "
         "efficiency.artifact_footprint. Dashed line joins measured points; "
         "it is not a fitted model.",
         fontsize=8, color="#666666", ha="left", va="top")
save(fig, "fig2_precision_cliff_cost_benefit")

# ---------------------------------------------------------------- Figure 3
forest(
    ["7B", "14B-1M", "32B"],
    "Quantization sensitivity across the Qwen2.5 scale ladder",
    "Q4_K_M versus each model's own F16 baseline\nn = 200 paired cases per family",
    "fig3_qwen_scale_ladder",
    "Qwen2.5 parameters",
    "Solid markers: two-sided exact McNemar p < 0.05. Families significant: "
    f"7B {nsig('7B')} of 8; 14B-1M {nsig('14B-1M')} of 8; 32B {nsig('32B')} of 8.\n"
    "CONFOUNDED: 7B ran on local llama.cpp with seed 42 applied; 14B-1M and "
    "32B ran on Modal, which records seed status 'unsupported'. Scale and "
    "substrate are not separated by this corpus.",
    legloc="lower left",
)

# ---------------------------------------------------------------- Figure 4
# Observed wall-time ratio per pair, with the accelerator on each lane.
# A pair whose lanes ran on different accelerators is drawn hatched and labelled
# hardware-unmatched: its ratio measures the hardware difference, not quantization.
fig, ax = plt.subplots(figsize=(9.2, 5.2))
names = {"Q4_K_M": "Mistral-Nemo  Q4_K_M", "Q5_K_M": "Mistral-Nemo  Q5_K_M",
         "Q8_0": "Mistral-Nemo  Q8_0", "7B": "Qwen2.5-7B  Q4_K_M",
         "14B-1M": "Qwen2.5-14B-1M  Q4_K_M", "32B": "Qwen2.5-32B  Q4_K_M"}
rows = sorted(names, key=lambda k: (not D[k]["_hw"]["matched"], -D[k]["_rt"]["v"]))
ypos = list(range(len(rows)))[::-1]
xmax = max(D[k]["_rt"]["v"] for k in rows)
for y, k in zip(ypos, rows):
    v, hw = D[k]["_rt"]["v"], D[k]["_hw"]
    ax.barh([y], [v], height=0.58, color=C[k] if hw["matched"] else "white",
            alpha=0.92 if hw["matched"] else 1.0, zorder=3,
            edgecolor=C[k], linewidth=1.6,
            hatch=None if hw["matched"] else "///")
    note = "" if hw["matched"] else "   hardware-unmatched"
    ax.text(max(v, 1.0) + 0.05, y, f"{v:.3f}×{note}", va="center", fontsize=10,
            weight="bold", color=INK)
ax.axvline(1.0, color=INK, lw=1.5, zorder=4)
ax.text(1.02, -0.85, "parity", fontsize=9, color=INK, va="center", ha="left")
ax.set_yticks(ypos)
ax.set_yticklabels([f"{names[k]}\n{D[k]['_hw']['base']} → {D[k]['_hw']['quant']}"
                    for k in rows], fontsize=9)
ax.set_ylim(-0.95, len(rows) - 0.45)
ax.set_xlim(0, max(3.05, xmax + 0.9))
ax.set_xlabel("Observed evaluation wall-time ratio (full weight ÷ quantized); "
              "accelerator shown as full-weight lane → quantized lane", fontsize=9.5)
ax.grid(axis="x", color=GRID, lw=0.7, zorder=1)
ax.set_axisbelow(True)
ax.legend(handles=[Patch(facecolor="#888888", edgecolor="#888888",
                         label="same accelerator on both lanes"),
                   Patch(facecolor="white", edgecolor="#888888", hatch="///",
                         label="different accelerators: not a quantization effect")],
          loc="lower right", frameon=True, framealpha=0.95, edgecolor=GRID,
          fontsize=8.5)
matched = [D[k]["_rt"]["v"] for k in rows if D[k]["_hw"]["matched"]]
fig.suptitle("Quantized lanes ran faster on every hardware-matched pair",
             x=0.02, ha="left", fontsize=14, weight="bold", y=1.02)
ax.set_title(f"{len(matched)} of {len(rows)} pairs ran both lanes on the same "
             f"accelerator: {min(matched):.3f}× to {max(matched):.3f}×",
             loc="left", fontsize=10, color="#555555", pad=10)
fig.text(0.02, -0.02,
         "Observed harness wall time on the recorded hardware and backends. Not a "
         "controlled throughput benchmark and not a general claim about quantization\n"
         "performance at any precision on any hardware. Hatched pairs ran the "
         "full-weight and quantized lanes on different accelerator classes; their\n"
         "ratios reflect that difference. Source: rollup.json "
         "efficiency.runtime_comparison.headline_runtime_metric; accelerators from "
         "hardware_map.txt (D7 v1.0.1).",
         fontsize=8, color="#666666", ha="left", va="top")
save(fig, "fig4_wall_time_ratio_six_pairs")

# ---------------------------------------------------------------- audit
print("\n--- PLOTTED VALUES (audit) ---")
for k in BUNDLES:
    print(k, "sig_families=%d" % nsig(k),
          "lanes=%s->%s" % (D[k]["_hw"]["base"], D[k]["_hw"]["quant"]),
          "matched=%s" % D[k]["_hw"]["matched"],
          "wall_time=%.4f" % D[k]["_rt"]["v"],
          "size_reduction=%.4f" % D[k]["_foot"]["red"],
          "quant_GB=%.2f" % (D[k]["_foot"]["quant"] / 1e9))
