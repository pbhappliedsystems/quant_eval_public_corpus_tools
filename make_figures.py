#!/usr/bin/env python3
"""Generate the four quant_eval corpus figures from rollup.json values only.

No value is recomputed, smoothed, or derived. Every plotted number is read
directly from the six publication bundles' rollup.json files.
"""
import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

OUT = "/mnt/user-data/outputs/figures"
os.makedirs(OUT, exist_ok=True)

BUNDLES = {
    "Q4_K_M": "pub/publication/publication/rollup.json",
    "Q5_K_M": "pub/publication/publication_1/rollup.json",
    "Q8_0":   "pub6/rollup.json",
    "7B":     "pub/publication/publication_2/rollup.json",
    "14B-1M": "pub/publication/publication_3/rollup.json",
    "32B":    "pub/publication/publication_4/rollup.json",
}
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
for k, p in BUNDLES.items():
    o = json.load(open(p))
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
    D[k] = d


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
    "Q4_K_M 6 of 8; Q5_K_M 0 of 8; Q8_0 0 of 8.\n"
    "Intervals are 95% confidence intervals on the paired difference. "
    "Source: quant_eval v7.22.22, rollup.json paired_runner_comparison.",
)

# ---------------------------------------------------------------- Figure 2
fig, ax1 = plt.subplots(figsize=(8.2, 5.0))
order = ["Q8_0", "Q5_K_M", "Q4_K_M"]
xs = [D[k]["_foot"]["red"] * 100 for k in order]
sig = [sum(1 for f in FAM if D[k][f]["p"] < 0.05) for k in order]
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
ax1.annotate("two-thirds of the saving,\nnone of the damage",
             xy=(64.0, 0.28), xytext=(52.0, 3.0), fontsize=9.5,
             color="#333333", ha="center",
             arrowprops=dict(arrowstyle="->", color="#666666", lw=1.1,
                             connectionstyle="arc3,rad=-0.28"))
fig.suptitle("The entire behavioral cost is paid in one step",
             x=0.02, ha="left", fontsize=14, weight="bold", y=1.01)
ax1.set_title("Mistral-Nemo-Instruct-2407 · F16 baseline = 24.50 GB",
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
    "7B 4 of 8; 14B-1M 4 of 8; 32B 0 of 8.\n"
    "CONFOUNDED: 7B ran on local llama.cpp with seed 42 applied; 14B-1M and "
    "32B ran on Modal, which records seed status 'unsupported'. Scale and "
    "substrate are not separated by this corpus.",
    legloc="lower left",
)

# ---------------------------------------------------------------- Figure 4
fig, ax = plt.subplots(figsize=(8.6, 4.6))
rows = [
    ("Mistral-Nemo  Q4_K_M", "local", D["Q4_K_M"]["_rt"]["v"], "Q4_K_M"),
    ("Mistral-Nemo  Q5_K_M", "local", D["Q5_K_M"]["_rt"]["v"], "Q5_K_M"),
    ("Qwen2.5-7B  Q4_K_M", "local", D["7B"]["_rt"]["v"], "7B"),
    ("Mistral-Nemo  Q8_0", "local", D["Q8_0"]["_rt"]["v"], "Q8_0"),
    ("Qwen2.5-14B-1M  Q4_K_M", "Modal", D["14B-1M"]["_rt"]["v"], "14B-1M"),
    ("Qwen2.5-32B  Q4_K_M", "Modal", D["32B"]["_rt"]["v"], "32B"),
]
ypos = list(range(len(rows)))[::-1]
for y, (name, sub, v, key) in zip(ypos, rows):
    slow = v < 1.0
    ax.barh([y], [v], height=0.58, color=C[key],
            alpha=0.35 if slow else 0.92, zorder=3,
            edgecolor=C[key], linewidth=1.6,
            hatch="///" if slow else None)
    ax.text(v + 0.045, y, f"{v:.3f}×", va="center", fontsize=10,
            weight="bold", color=INK)
ax.axvline(1.0, color=INK, lw=1.5, zorder=4)
ax.set_ylim(-0.95, 5.55)
ax.text(1.02, -0.85, "parity", fontsize=9, color=INK, va="center", ha="left")
ax.set_yticks(ypos)
ax.set_yticklabels([f"{n}\n{s}" for n, s, _, _ in rows], fontsize=9)
ax.set_xlabel("Observed evaluation wall-time ratio "
              "(full weight ÷ quantized)", fontsize=10)
ax.set_xlim(0, 3.05)
ax.grid(axis="x", color=GRID, lw=0.7, zorder=1)
ax.set_axisbelow(True)
ax.annotate("slower under quantization", xy=(0.80, 0.45),
            xytext=(1.62, 1.25), fontsize=9.5, color="#333333", va="center",
            arrowprops=dict(arrowstyle="->", color="#666666", lw=1.1,
                            connectionstyle="arc3,rad=0.28"))
fig.suptitle("Quantization does not universally run faster",
             x=0.02, ha="left", fontsize=14, weight="bold", y=1.02)
ax.set_title("Two of six measured pairs are slower than full weight",
             loc="left", fontsize=10, color="#555555", pad=10)
fig.text(0.02, -0.10,
         "Observed harness wall time on the recorded hardware and backends. "
         "Not a controlled throughput benchmark and not a general claim about "
         "quantization performance\nat any precision on any hardware. "
         "Source: rollup.json efficiency.runtime_comparison."
         "headline_runtime_metric.",
         fontsize=8, color="#666666", ha="left", va="top")
save(fig, "fig4_wall_time_ratio_six_pairs")

# ---------------------------------------------------------------- audit
print("\n--- PLOTTED VALUES (audit) ---")
for k in BUNDLES:
    print(k, "sig_families=%d" % sum(1 for f in FAM if D[k][f]["p"] < 0.05),
          "wall_time=%.4f" % D[k]["_rt"]["v"],
          "size_reduction=%.4f" % D[k]["_foot"]["red"],
          "quant_GB=%.2f" % (D[k]["_foot"]["quant"] / 1e9))
