"""
demo_all.py — One script to demo every model feature and plot everything.

Run from the "3.2 system model v2/" folder:
    python demo_all.py

Or from workspace root:
    python "3. system model/3.2 system model v2/demo_all.py"

What it shows
─────────────
Section 1 : Power curve shape  (parametric cubic, several turbine specs)
Section 2 : Wind-speed height correction comparison (log-law vs power-law)
Section 3 : ERA5 wind → generation via power curve (full-year 2023)
Section 4 : Rule-based dispatch  — greedy H₂-first  (4-panel summary, single day)
Section 5 : LP-optimised dispatch — revenue objective  (4-panel, same day, same sizing)
Section 6 : LP-optimised dispatch — max H₂ objective  (4-panel, same day, same sizing)
Section 7 : Annual comparison bar chart  (rule-based / LP-revenue / LP-max-H₂, identical sizing)

All plots open in matplotlib windows.  Close each window to advance to the next.
Set SAVE_FIGS = True to save PNGs to outputs/ instead of showing interactively.
"""

import sys
import os

# Ensure Unicode box-drawing characters print correctly on Windows consoles
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Make sure imports resolve from the project root ──────────────────────────
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

from src.scenarios.config import ScenarioConfig, OUTPUT_DIR
from src.scenarios.run_scenario import run_scenario
from src.data.loaders import load_alpha_ventus_wind
from src.models.generation import (
    power_curve_parametric,
    extrapolate_wind_speed,
    generate_from_wind_speed,
)
from src.models.dispatch_optimised import plot_optimised_dispatch
from src.scenarios.library import get_scenario

# ── Configuration ─────────────────────────────────────────────────────────────
YEAR        = 2023
DEMO_DAY    = "2023-01-15"   # pick a day to inspect in detail
SAVE_FIGS   = False          # True → save to outputs/; False → show interactively
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Styling ───────────────────────────────────────────────────────────────────
BG   = "#0d0d1a"
LINE = "#c8e64c"
GRID = "#2a2a3d"
TEXT = "#cccccc"
BLUE = "#5599ff"
ORNG = "#ff7733"
PINK = "#ff44aa"

def _style(ax):
    ax.set_facecolor(BG)
    ax.tick_params(colors=TEXT, labelsize=9)
    ax.yaxis.label.set_color(TEXT)
    ax.xaxis.label.set_color(TEXT)
    ax.title.set_color(TEXT)
    for sp in ax.spines.values():
        sp.set_edgecolor(GRID)
    ax.grid(True, color=GRID, linewidth=0.6)

def _show_or_save(fig, name: str):
    if SAVE_FIGS:
        path = OUTPUT_DIR / f"{name}.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        print(f"  Saved → {path}")
        plt.close(fig)
    else:
        plt.show()


# ══════════════════════════════════════════════════════════════════════════════
# Section 1 — Power curve shape
# ══════════════════════════════════════════════════════════════════════════════
print("\n── Section 1: Power curve shape ─────────────────────────")

v_range = np.linspace(0, 30, 300)

turbines = {
    "Adwen AD 5-116 (old, v_r=14 m/s)":  dict(cut_in_ms=3.5, rated_speed_ms=14.0, cut_out_ms=25.0),
    "Modern 12 MW  (v_r=12 m/s)":        dict(cut_in_ms=3.0, rated_speed_ms=12.0, cut_out_ms=25.0),
    "Modern 15 MW  (v_r=11 m/s)":        dict(cut_in_ms=3.0, rated_speed_ms=11.0, cut_out_ms=25.0),
    "Next-gen 20 MW (v_r=10 m/s)":       dict(cut_in_ms=3.0, rated_speed_ms=10.0, cut_out_ms=25.0),
}

fig, ax = plt.subplots(figsize=(9, 5), facecolor=BG)
_style(ax)
colours = [LINE, ORNG, BLUE, PINK]
for (label, params), colour in zip(turbines.items(), colours):
    cf = power_curve_parametric(v_range, **params)
    ax.plot(v_range, cf * 100, color=colour, linewidth=2, label=label)

ax.set_xlabel("Wind speed at hub height [m/s]")
ax.set_ylabel("Capacity factor [%]")
ax.set_title("Parametric Power Curves — Modern vs Old Turbine")
ax.legend(fontsize=8, facecolor=BG, labelcolor=TEXT, framealpha=0.7)
ax.axvline(8.5, color="#888", linestyle=":", linewidth=1.0, label="Typical offshore mean ~8.5 m/s")
ax.set_xlim(0, 30)
ax.set_ylim(0, 110)
fig.suptitle("Section 1 — Power Curve Shape", color=TEXT, fontsize=11)
plt.tight_layout()
_show_or_save(fig, "01_power_curves")


# ══════════════════════════════════════════════════════════════════════════════
# Section 2 — Wind-speed height correction (log-law)
# ══════════════════════════════════════════════════════════════════════════════
print("── Section 2: Height correction (log-law) ────────────────")

v_ref    = np.linspace(0, 20, 200)   # wind speed at 100 m
z_ref    = 100.0
heights  = [100, 120, 150, 180]      # hub heights to compare
z0       = 0.0002                    # !! REPLACE WITH ACTUAL z0 FOR SITE !!

fig, ax = plt.subplots(figsize=(9, 5), facecolor=BG)
fig.patch.set_facecolor(BG)
_style(ax)
colours_h = [LINE, ORNG, BLUE, PINK]
for z_hub, colour in zip(heights, colours_h):
    v_hub = extrapolate_wind_speed(v_ref, z_ref=z_ref, z_hub=z_hub, z0=z0)
    ax.plot(v_ref, v_hub, color=colour, linewidth=2,
            label=f"z_hub = {z_hub} m")
ax.plot(v_ref, v_ref, color="#888", linestyle="--", linewidth=1, label="No correction (ref = 100 m)")
ax.set_xlabel("v at 100 m [m/s]")
ax.set_ylabel("v at hub height [m/s]")
ax.set_title(f"Log-law  (z₀ = {z0} m, open sea)  —  ref = {z_ref} m")
ax.legend(fontsize=8, facecolor=BG, labelcolor=TEXT, framealpha=0.7)
fig.suptitle("Section 2 — Wind Speed Height Correction (Log-law)", color=TEXT, fontsize=11)
plt.tight_layout()
_show_or_save(fig, "02_height_correction")


# ══════════════════════════════════════════════════════════════════════════════
# Section 3 — ERA5 wind speed → generation via power curve
# ══════════════════════════════════════════════════════════════════════════════
print(f"── Section 3: ERA5 wind → power curve generation ({YEAR}) ─")

try:
    wind_df = load_alpha_ventus_wind(year=YEAR)
    # Strip timezone so timestamps are naive UTC, matching load_df
    wind_df["timestamp"] = wind_df["timestamp"].dt.tz_localize(None)
    cfg_pc = ScenarioConfig(
        use_power_curve=True,
        year=YEAR,
        target_farm_capacity_mw=500.0,
        turbine_rated_speed_ms=11.0,
        turbine_hub_height_m=120.0,
        wind_data_height_m=100.0,
        z0_roughness_m=0.0002,    # !! REPLACE WITH ACTUAL z0 !!
    )
    # Minimal load data to satisfy merge (generation only needed here)
    from src.data.loaders import load_smard_load
    load_df = load_smard_load(year=YEAR)
    df_wind = pd.merge(wind_df, load_df, on="timestamp", how="inner")
    df_wind = generate_from_wind_speed(df_wind, cfg_pc)

    fig, axes = plt.subplots(3, 1, figsize=(13, 9), facecolor=BG)
    fig.patch.set_facecolor(BG)

    # Panel 1: full-year generation
    ax = axes[0]
    _style(ax)
    ax.fill_between(df_wind["timestamp"], df_wind["gen_scaled_mwh"],
                    alpha=0.5, color=LINE)
    ax.plot(df_wind["timestamp"], df_wind["gen_scaled_mwh"],
            color=LINE, linewidth=0.6)
    ax.set_ylabel("Generation [MWh/h]")
    ax.set_title(f"Full-year Generation — Power-curve path  ({YEAR})")
    ax.set_xlim(df_wind["timestamp"].iloc[0], df_wind["timestamp"].iloc[-1])

    # Panel 2: wind speed
    ax = axes[1]
    _style(ax)
    ax.plot(df_wind["timestamp"], df_wind["wind_speed_ms"],
            color=ORNG, linewidth=0.6, alpha=0.8)
    ax.set_ylabel("Wind speed @ 100 m [m/s]")
    ax.set_title("ERA5 Wind Speed (100 m)")
    ax.set_xlim(df_wind["timestamp"].iloc[0], df_wind["timestamp"].iloc[-1])

    # Panel 3: capacity factor distribution
    ax = axes[2]
    _style(ax)
    v_vals = extrapolate_wind_speed(
        df_wind["wind_speed_ms"].to_numpy(),
        z_ref=100.0, z_hub=120.0, z0=0.0002
    )
    cf_vals = power_curve_parametric(v_vals, cut_in_ms=3.0,
                                     rated_speed_ms=11.0, cut_out_ms=25.0)
    ax.hist(cf_vals * 100, bins=50, color=LINE, alpha=0.75, edgecolor=BG)
    ax.set_xlabel("Capacity factor [%]")
    ax.set_ylabel("Hours per year")
    ax.set_title("Capacity Factor Distribution")
    mean_cf = cf_vals.mean() * 100
    ax.axvline(mean_cf, color=ORNG, linestyle="--", linewidth=1.5,
               label=f"Mean CF = {mean_cf:.1f}%")
    ax.legend(fontsize=8, facecolor=BG, labelcolor=TEXT, framealpha=0.7)

    fig.suptitle("Section 3 — ERA5 Wind → Generation (Power-curve path)", color=TEXT, fontsize=11)
    plt.tight_layout()
    _show_or_save(fig, "03_wind_to_generation")

except FileNotFoundError as e:
    print(f"  SKIPPED (data not found): {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Section 4 — Rule-based dispatch  ("balanced" scenario)
# Electrolyser sized to just cover the offtake contract: the tank actually
# cycles meaningfully instead of filling in 2 days and sitting full all year.
# ══════════════════════════════════════════════════════════════════════════════
print("── Section 4: Rule-based dispatch (balanced) ────────────")

cfg_rule = get_scenario("balanced", year=YEAR)
df_rule, summary_rule = run_scenario(cfg_rule)
print(f"  Rule-based  | Revenue: €{summary_rule['total_revenue_eur']:,.0f}  "
      f"| H₂ sold: {summary_rule['total_h2_sold_kg']/1000:.0f} t")

fig_rule = plot_optimised_dispatch(
    df_rule, day=DEMO_DAY,
    title=f"Rule-based Dispatch (balanced)  ·  {DEMO_DAY}",
    h2_price_eur_per_kg=cfg_rule.h2_selling_price_eur_per_kg,
    tank_capacity_kg=cfg_rule.tank_capacity_kg,
)
_show_or_save(fig_rule, "04_rule_based_dispatch")


# ══════════════════════════════════════════════════════════════════════════════
# Section 5 — LP-optimised dispatch  ("balanced" scenario, revenue objective)
# Same sizing as Section 4 — direct apples-to-apples comparison.
# ══════════════════════════════════════════════════════════════════════════════
print("── Section 5: LP-optimised dispatch (balanced) ──────────")

cfg_opt_rev = get_scenario("balanced_lp", year=YEAR)
df_rev, summary_rev = run_scenario(cfg_opt_rev)
print(f"  LP-revenue  | Revenue: €{summary_rev['total_revenue_eur']:,.0f}  "
      f"| H₂ sold: {summary_rev['total_h2_sold_kg']/1000:.0f} t")

fig_rev = plot_optimised_dispatch(
    df_rev, day=DEMO_DAY,
    title=f"LP-Optimised Dispatch (balanced)  ·  {DEMO_DAY}",
    h2_price_eur_per_kg=cfg_opt_rev.h2_selling_price_eur_per_kg,
    tank_capacity_kg=cfg_opt_rev.tank_capacity_kg,
)
_show_or_save(fig_rev, "05_lp_revenue_dispatch")


# ══════════════════════════════════════════════════════════════════════════════
# Section 6 — LP-optimised dispatch  ("balanced_h2" scenario)
# Same sizing as Sections 4 & 5, but LP maximises H₂ production volume
# instead of revenue.  Runs the electrolyser as hard as wind and tank allow;
# grid only absorbs surplus when the tank is full.
# Compare with Section 5 (LP-revenue) to see the H₂ vs profit trade-off.
# ══════════════════════════════════════════════════════════════════════════════
print("── Section 6: LP-optimised dispatch (max H₂) ────────────")

cfg_opt_h2 = get_scenario("balanced_h2", year=YEAR)
df_h2, summary_h2 = run_scenario(cfg_opt_h2)
print(f"  LP-max H₂  | Revenue: €{summary_h2['total_revenue_eur']:,.0f}  "
      f"| H₂ sold: {summary_h2['total_h2_sold_kg']/1000:.0f} t")

fig_h2 = plot_optimised_dispatch(
    df_h2, day=DEMO_DAY,
    title=f"LP-Optimised Dispatch (max H₂)  ·  {DEMO_DAY}",
    h2_price_eur_per_kg=cfg_opt_h2.h2_selling_price_eur_per_kg,
    tank_capacity_kg=cfg_opt_h2.tank_capacity_kg,
)
_show_or_save(fig_h2, "06_lp_max_h2_dispatch")


# ══════════════════════════════════════════════════════════════════════════════
# Section 7 — Annual comparison bar chart
# ══════════════════════════════════════════════════════════════════════════════
print("── Section 7: Annual comparison ─────────────────────────")

labels   = ["Rule-based\n(H₂ first)", "LP\n(max revenue)", "LP\n(max H₂)"]
revenues = [
    summary_rule["total_revenue_eur"] / 1e6,
    summary_rev["total_revenue_eur"]  / 1e6,
    summary_h2["total_revenue_eur"]   / 1e6,
]
h2_sold  = [
    summary_rule["total_h2_sold_kg"]  / 1e3,
    summary_rev["total_h2_sold_kg"]   / 1e3,
    summary_h2["total_h2_sold_kg"]    / 1e3,
]
profits  = [
    summary_rule["total_profit_eur"]  / 1e6,
    summary_rev["total_profit_eur"]   / 1e6,
    summary_h2["total_profit_eur"]    / 1e6,
]

x = np.arange(len(labels))
w = 0.25

fig, axes = plt.subplots(1, 3, figsize=(13, 5), facecolor=BG)
fig.patch.set_facecolor(BG)

for ax, values, ylabel, colour, title in zip(
    axes,
    [revenues, h2_sold, profits],
    ["Revenue [M€]", "H₂ sold [t]", "Profit [M€]"],
    [LINE, ORNG, BLUE],
    ["Annual Revenue", "H₂ Sold", "Annual Profit"],
):
    _style(ax)
    bars = ax.bar(x, values, width=0.55, color=colour, alpha=0.85, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8, color=TEXT, rotation=10)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.01,
                f"{val:.1f}", ha="center", va="bottom", fontsize=8, color=TEXT)

fig.suptitle(f"Section 7 — Dispatch Strategy Comparison  ({YEAR})", color=TEXT, fontsize=12)
plt.tight_layout()
_show_or_save(fig, "07_annual_comparison")

print("\n── All done ─────────────────────────────────────────────")
print(f"   Rule-based (H₂ first) profit: €{summary_rule['total_profit_eur']:>12,.0f}")
print(f"   LP-revenue (balanced) profit: €{summary_rev['total_profit_eur']:>12,.0f}")
print(f"   LP-max H₂ (balanced) profit:  €{summary_h2['total_profit_eur']:>12,.0f}")
