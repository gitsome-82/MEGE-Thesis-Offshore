# Run command (from repo root):
# .venv\Scripts\streamlit run "3. system model/3.2 system model v2/app/streamlit_app.py"

"""
Streamlit dashboard for the offshore wind + H2 storage control model.

Calls the scenario runner and displays the hourly output table
plus summary metrics and plots.
"""
# --- Ensure all required packages are installed (auto-install if missing) ---
import subprocess
import sys

_required = ["streamlit", "pandas", "plotly", "folium", "streamlit_folium"]
for _pkg in _required:
    try:
        __import__(_pkg)
    except ImportError:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', _pkg])

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pathlib
import folium
from streamlit_folium import st_folium

# Ensure src/ is importable when running `streamlit run app/streamlit_app.py`
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.scenarios.config import ScenarioConfig
from src.scenarios.run_scenario import run_scenario
from src.scenarios.library import SCENARIOS, get_scenario

st.set_page_config(page_title="Offshore Wind + H₂ Storage Model", layout="wide")
st.title("Offshore Wind + H₂ Storage Control Model")


# ── Sidebar: scenario parameters ─────────────────────────────────────────
st.sidebar.header("Scenario Parameters")

# ── Preset loader ─────────────────────────────────────────────────────────
# Selecting a preset writes its values into st.session_state so sliders
# (which Streamlit would otherwise keep from previous user interaction)
# actually reset to the preset values.  Only fires when the preset changes.
preset_options = ["— custom —"] + sorted(SCENARIOS.keys())

if "last_preset" not in st.session_state:
    st.session_state["last_preset"] = "— custom —"

preset = st.sidebar.selectbox("Load preset scenario", preset_options, index=0)

if preset != "— custom —" and preset != st.session_state["last_preset"]:
    # Preset just changed — push all its values into session state
    _p = get_scenario(preset)
    st.session_state["preset_country"]      = _p.country
    st.session_state["preset_year"]         = _p.year
    st.session_state["preset_farm_mw"]      = int(_p.target_farm_capacity_mw)
    st.session_state["preset_derate"]       = float(_p.derate_factor)
    st.session_state["preset_elec_mw"]      = int(_p.electrolyser_capacity_mw)
    st.session_state["preset_elec_eff"]     = float(_p.electrolyser_efficiency_kwh_per_kg)
    st.session_state["preset_tank_kg"]      = int(_p.tank_capacity_kg)
    st.session_state["preset_h2_offtake"]   = int(_p.h2_daily_offtake_kg)
    st.session_state["preset_h2_price"]     = float(_p.h2_selling_price_eur_per_kg)
    st.session_state["preset_opex"]         = float(_p.opex_eur_per_mwh)
    st.session_state["preset_prioritise"]   = bool(_p.prioritise_h2)
    st.session_state["preset_use_lp"]       = bool(_p.use_optimised_dispatch)
    st.session_state["preset_lp_obj"]       = _p.dispatch_objective
    st.session_state["last_preset"]         = preset


def _ss(key, fallback):
    """Return session-state override if present (from a just-applied preset),
    else the fallback default."""
    return st.session_state.get(key, fallback)


country = st.sidebar.selectbox(
    "Country", ["Germany", "Portugal"],
    index=["Germany", "Portugal"].index(_ss("preset_country", "Germany")),
)

if country == "Germany":
    data_source = st.sidebar.selectbox("Data Source", ["SMARD", "Frauenhofer"])
    available_years = [2022, 2023, 2024, 2025]
else:
    data_source = "ENTSO-E"
    st.sidebar.info("Data source: ENTSO-E (Portugal)")
    available_years = [2022, 2023, 2024, 2025]

_def_year = _ss("preset_year", 2023)
year = st.sidebar.selectbox(
    "Year", available_years,
    index=available_years.index(_def_year) if _def_year in available_years else 0,
)

st.sidebar.subheader("Wind Farm")
target_farm_mw = st.sidebar.slider("Target farm capacity (MW)", 25, 25000, _ss("preset_farm_mw", 500), 50)
derate = st.sidebar.slider("Derate factor", 0.5, 1.0, _ss("preset_derate", 1.0), 0.01)

st.sidebar.subheader("Electrolyser")
elec_mw = st.sidebar.slider("Electrolyser capacity (MW)", 0, 1000, _ss("preset_elec_mw", 100), 10)
elec_eff = st.sidebar.slider("Specific consumption (kWh/kg)", 40.0, 70.0, _ss("preset_elec_eff", 55.0), 1.0)

st.sidebar.subheader("H₂ Tank")
tank_kg = st.sidebar.slider("Tank capacity (kg)", 0, 1_000_000, _ss("preset_tank_kg", 10_000), 5_000)
h2_offtake = st.sidebar.slider("H₂ daily offtake (kg/day)", 0, 50_000, _ss("preset_h2_offtake", 2_000), 500)

st.sidebar.subheader("Economics")
h2_price = st.sidebar.slider("H₂ selling price (EUR/kg)", 1.0, 15.0, _ss("preset_h2_price", 5.0), 0.5)
opex = st.sidebar.slider("Operating cost (EUR/MWh)", 0.0, 50.0, _ss("preset_opex", 23.0), 1.0)

st.sidebar.subheader("Dispatch")
prioritise_h2 = st.sidebar.checkbox(
    "Prioritise H₂ over grid",
    value=_ss("preset_prioritise", True),
    help="Rule-based only. LP always optimises automatically.",
)
use_lp = st.sidebar.checkbox(
    "Use LP optimiser",
    value=_ss("preset_use_lp", False),
    help="LP solves 24h window at once (slower but optimal). Rule-based uses greedy priority logic.",
)
if use_lp:
    lp_obj = st.sidebar.radio(
        "LP objective",
        ["revenue", "h2"],
        index=0 if _ss("preset_lp_obj", "revenue") == "revenue" else 1,
        horizontal=True,
    )
else:
    lp_obj = "revenue"

# ── Build config ──────────────────────────────────────────────────────────
cfg = ScenarioConfig(
    country=country,
    data_source=data_source,
    year=year,
    target_farm_capacity_mw=target_farm_mw,
    derate_factor=derate,
    electrolyser_capacity_mw=elec_mw,
    electrolyser_efficiency_kwh_per_kg=elec_eff,
    tank_capacity_kg=tank_kg,
    h2_daily_offtake_kg=h2_offtake,
    h2_selling_price_eur_per_kg=h2_price,
    opex_eur_per_mwh=opex,
    prioritise_h2=prioritise_h2,
    use_optimised_dispatch=use_lp,
    dispatch_objective=lp_obj,
)


# ── Run scenario (cached) ────────────────────────────────────────────────
@st.cache_data
def cached_run(cfg_dict):
    c = ScenarioConfig(**cfg_dict)
    return run_scenario(c)

from dataclasses import asdict
hourly_df, summary = cached_run(asdict(cfg))


# ── Summary metrics ──────────────────────────────────────────────────────
st.header("Annual Summary")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Generation (GWh)", f"{summary['total_generation_mwh']/1e3:,.0f}")
c2.metric("To Grid (GWh)", f"{summary['total_to_grid_mwh']/1e3:,.0f}")
c3.metric("H₂ Produced (t)", f"{summary['total_h2_produced_kg']/1e3:,.1f}")
c4.metric("Curtailed (GWh)", f"{summary['total_curtailed_mwh']/1e3:,.0f}")
c5.metric("Curtailment Rate", f"{summary['curtailment_rate_pct']:.1f}%")

r1, r2, r3, r4 = st.columns(4)
r1.metric("Grid Revenue (M€)", f"{summary['total_grid_revenue_eur']/1e6:,.2f}")
r2.metric("H₂ Revenue (M€)", f"{summary['total_h2_revenue_eur']/1e6:,.2f}")
r3.metric("Total Revenue (M€)", f"{summary['total_revenue_eur']/1e6:,.2f}")
r4.metric("PV of Operating Profit (M€)", f"{summary['npv_eur']/1e6:,.2f}",
          help="Present value of this year's profit × 25yr annuity factor. No CAPEX included — not a true project NPV.")


# ── Project location map ──────────────────────────────────────────────────
if country == "Germany":
    # Alpha Ventus offshore wind farm
    SITE_LAT, SITE_LON = 54.011111, 6.607778
    SITE_NAME = "Alpha Ventus OWF"
    SITE_INFO = "Alpha Ventus — Germany's first offshore wind farm<br>45 km north of Borkum<br>Installed: 60 MW (12 × 5 MW)"
else:
    # WindFloat Atlantic (WGS 84, exact — Wikipedia [8])
    SITE_LAT, SITE_LON = 41.6865, -9.0574
    SITE_NAME = "WindFloat Atlantic"
    SITE_INFO = "WindFloat Atlantic — Portugal's first floating offshore wind farm<br>Viana do Castelo<br>Installed: 25.2 MW (3 × 8.4 MW)"

with st.expander(f"Project location — {SITE_NAME}", expanded=True):
    m = folium.Map(location=[SITE_LAT, SITE_LON], zoom_start=8, tiles="CartoDB positron")
    folium.Marker(
        location=[SITE_LAT, SITE_LON],
        popup=folium.Popup(SITE_INFO, max_width=280),
        tooltip=SITE_NAME,
        icon=folium.Icon(color="blue", icon="cloud", prefix="fa"),
    ).add_to(m)
    # Add a circle showing approximate farm extent
    folium.Circle(
        location=[SITE_LAT, SITE_LON],
        radius=5000,  # 5 km radius
        color="steelblue",
        fill=True,
        fill_opacity=0.15,
        tooltip="Approx. farm extent",
    ).add_to(m)
    st_folium(m, width=700, height=400, returned_objects=[])


# ── Hourly output table (supervisor's format) ────────────────────────────
st.header("Hourly Output Table")
display_cols = [
    "timestamp", "action", "energy_flux_battery_kwh",
    "h2_produced_kg", "to_grid_mwh", "curtailed_mwh",
    "ancillary_revenue_eur", "total_revenue_eur", "profit_eur",
]
st.dataframe(hourly_df[display_cols], use_container_width=True, height=400)


# ── Plots ─────────────────────────────────────────────────────────────────
st.header("Dispatch Overview")

# Time-range selector
min_date = hourly_df["timestamp"].min().date()
max_date = hourly_df["timestamp"].max().date()
date_range = st.date_input("Date range", value=(min_date, max_date),
                           min_value=min_date, max_value=max_date)
if len(date_range) == 2:
    mask = (hourly_df["timestamp"].dt.date >= date_range[0]) & \
           (hourly_df["timestamp"].dt.date <= date_range[1])
    plot_df = hourly_df[mask]
else:
    plot_df = hourly_df

# Stacked area: generation allocation
fig_alloc = go.Figure()
fig_alloc.add_trace(go.Scatter(
    x=plot_df["timestamp"], y=plot_df["to_grid_mwh"],
    stackgroup='one', name="To Grid", line=dict(width=0)))
fig_alloc.add_trace(go.Scatter(
    x=plot_df["timestamp"], y=plot_df["to_electrolyser_mwh"],
    stackgroup='one', name="To Electrolyser", line=dict(width=0)))
fig_alloc.add_trace(go.Scatter(
    x=plot_df["timestamp"], y=plot_df["curtailed_mwh"],
    stackgroup='one', name="Curtailed", line=dict(width=0)))
fig_alloc.update_layout(title="Generation Allocation", yaxis_title="MWh/h")
st.plotly_chart(fig_alloc, use_container_width=True)

# Tank SOC
fig_soc = px.line(plot_df, x="timestamp", y="tank_soc_kg",
                  title="H₂ Tank State of Charge")
fig_soc.update_yaxes(title_text="kg H₂")
st.plotly_chart(fig_soc, use_container_width=True)

# Cumulative revenue
plot_df = plot_df.copy()
plot_df["cumulative_revenue"] = plot_df["total_revenue_eur"].cumsum()
fig_rev = px.line(plot_df, x="timestamp", y="cumulative_revenue",
                  title="Cumulative Revenue")
fig_rev.update_yaxes(title_text="EUR")
st.plotly_chart(fig_rev, use_container_width=True)
