"""
Shared UI components and plot functions used by all country modules.
All plot functions expect a DataFrame with standardised columns:
    timestamp, gen_scaled, load_scaled, load_met, surplus, unmet, month, day, hour
"""

import calendar
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# Meteorological seasons (DWD / WMO standard)
seasons = {
    "Winter": [12, 1, 2],
    "Spring": [3, 4, 5],
    "Summer": [6, 7, 8],
    "Autumn": [9, 10, 11],
}


def apply_css():
    st.markdown("""
<style>
[data-testid="stMetricValue"] > div { font-size: 1.1rem !important; }
[data-testid="stMetricLabel"] { font-size: 0.75rem !important; }
</style>
""", unsafe_allow_html=True)


def _fmt_energy(mwh):
    """Auto-scale energy value to TWh / GWh / MWh."""
    if abs(mwh) >= 1e6:
        return f"{mwh / 1e6:.2f} TWh"
    elif abs(mwh) >= 1e3:
        return f"{mwh / 1e3:.1f} GWh"
    return f"{mwh:.0f} MWh"


def render_top_metrics(df):
    total_load = df["load_scaled"].sum()
    total_gen = df["gen_scaled"].sum()
    total_met = df["load_met"].sum()
    coverage_pct = 100 * total_met / total_load if total_load else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Annual load", _fmt_energy(total_load))
    c2.metric("Annual generation", _fmt_energy(total_gen))
    c3.metric("Coverage (%)", f"{coverage_pct:.1f}")
    return total_load, total_gen, total_met


def render_summary_expander(df, target_capacity, capacity_unit="GW"):
    total_load = df["load_scaled"].sum()
    total_gen = df["gen_scaled"].sum()
    total_met = df["load_met"].sum()
    hours = len(df)
    cap_mw = target_capacity * 1000 if capacity_unit == "GW" else target_capacity
    capacity_factor = (total_gen / (cap_mw * hours) * 100) if (cap_mw > 0 and hours > 0) else 0
    total_surplus = df["surplus"].sum()
    full_load_hours = (total_gen / cap_mw) if cap_mw > 0 else 0
    unit_div = 1000 if capacity_unit == "GW" else 1

    with st.expander("📊 Annual Summary", expanded=True):
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Capacity Factor", f"{capacity_factor:.1f} %")
        s2.metric("Equivalent Full-Load Hours", f"{full_load_hours:,.0f} h")
        s3.metric("Total Surplus", _fmt_energy(total_surplus))
        s4.metric("Total Unmet Load", _fmt_energy(total_load - total_met))

        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Peak Generation", f"{df['gen_scaled'].max() / unit_div:.2f} {capacity_unit}")
        p2.metric("Peak Load", f"{df['load_scaled'].max() / unit_div:.2f} {capacity_unit}")
        p3.metric("Peak Surplus", f"{df['surplus'].max() / unit_div:.2f} {capacity_unit}")
        p4.metric("Peak Unmet", f"{df['unmet'].max() / unit_div:.2f} {capacity_unit}")


# ---------------------------------------------------------------------------
# View plot functions — each takes a pre-filtered / pre-scaled DataFrame
# ---------------------------------------------------------------------------

def plot_year_view(df):
    total_load = df["load_scaled"].sum()
    total_met = df["load_met"].sum()

    monthly = df.resample("ME", on="timestamp").sum(numeric_only=True).reset_index()
    monthly["load_met_gwh"] = monthly["load_met"] / 1000
    monthly["unmet_gwh"] = monthly["unmet"] / 1000
    monthly["month_label"] = monthly["timestamp"].dt.strftime("%b %Y")
    monthly["coverage_pct"] = 100 * monthly["load_met"] / monthly["load_scaled"]

    fig_pie = px.pie(
        names=["Load Met", "Unmet Load"],
        values=[total_met / 1e6, (total_load - total_met) / 1e6],
        title="Annual Load Coverage (TWh)",
    )
    fig_pie.update_traces(hovertemplate="<b>%{label}</b><br>%{value:.3f} TWh<extra></extra>")
    st.plotly_chart(fig_pie, width="stretch")

    fig_stack = go.Figure()
    fig_stack.add_trace(go.Bar(x=monthly["month_label"], y=monthly["load_met_gwh"],
                               name="Load Met by Offshore", marker_color="#2ca02c"))
    fig_stack.add_trace(go.Bar(x=monthly["month_label"], y=monthly["unmet_gwh"],
                               name="Unmet Load", marker_color="#d3d3d3"))
    fig_stack.update_layout(barmode="stack", title="Monthly Load Coverage",
                            yaxis_title="Energy (GWh)", xaxis_title="Month")
    st.plotly_chart(fig_stack, width="stretch")

    fig_pct = go.Figure()
    fig_pct.add_trace(go.Bar(x=monthly["month_label"], y=monthly["coverage_pct"],
                             name="Covered by Offshore", marker_color="#2ca02c"))
    fig_pct.add_trace(go.Bar(x=monthly["month_label"], y=100 - monthly["coverage_pct"],
                             name="Unmet", marker_color="#d3d3d3"))
    fig_pct.update_layout(barmode="stack", title="Monthly Offshore Wind Coverage (%)",
                          yaxis=dict(title="Coverage (%)", range=[0, 100]), xaxis_title="Month")
    st.plotly_chart(fig_pct, width="stretch")


def plot_season_view(season_df, season_name):
    season_met = season_df["load_met"].sum()
    season_load = season_df["load_scaled"].sum()

    fig_pie = px.pie(
        names=["Load Met", "Unmet Load"],
        values=[season_met / 1e6, (season_load - season_met) / 1e6],
        title=f"{season_name} Load Coverage (TWh)",
    )
    fig_pie.update_traces(hovertemplate="<b>%{label}</b><br>%{value:.3f} TWh<extra></extra>")
    st.plotly_chart(fig_pie, width="stretch")

    fig_line = px.line(season_df, x="timestamp", y=["gen_scaled", "load_scaled"],
                       title=f"{season_name} Generation vs Load")
    fig_line.update_yaxes(title_text="Power (MWh/h)")
    fig_line.update_xaxes(range=[season_df["timestamp"].min(), season_df["timestamp"].max()])
    fig_line.for_each_trace(lambda t: t.update(name="Generation" if t.name == "gen_scaled" else "Load"))
    st.plotly_chart(fig_line, width="stretch")

    season_daily = season_df.groupby("day").sum(numeric_only=True).reset_index()
    season_daily["coverage_pct"] = 100 * season_daily["load_met"] / season_daily["load_scaled"]
    fig_pct = go.Figure()
    fig_pct.add_trace(go.Bar(x=season_daily["day"], y=season_daily["coverage_pct"],
                             name="Covered by Offshore", marker_color="#2ca02c"))
    fig_pct.add_trace(go.Bar(x=season_daily["day"], y=100 - season_daily["coverage_pct"],
                             name="Unmet", marker_color="#d3d3d3"))
    fig_pct.update_layout(barmode="stack", title=f"{season_name} Daily Coverage (%)",
                          yaxis=dict(title="Coverage (%)", range=[0, 100]), xaxis_title="Day")
    st.plotly_chart(fig_pct, width="stretch")


def plot_month_view(df, month_num):
    month_df = df[df["month"] == month_num]
    month_name = calendar.month_name[month_num]

    daily = month_df.groupby("day").sum(numeric_only=True).reset_index()
    daily["load_met_gwh"] = daily["load_met"] / 1000
    daily["unmet_gwh"] = daily["unmet"] / 1000
    daily["coverage_pct"] = 100 * daily["load_met"] / daily["load_scaled"]

    month_met = month_df["load_met"].sum()
    month_load = month_df["load_scaled"].sum()
    fig_pie = px.pie(
        names=["Load Met", "Unmet Load"],
        values=[month_met / 1e6, (month_load - month_met) / 1e6],
        title=f"{month_name} Load Coverage",
    )
    fig_pie.update_traces(hovertemplate="<b>%{label}</b><br>%{value:.4f} TWh<extra></extra>")
    st.plotly_chart(fig_pie, width="stretch")

    fig_stack = go.Figure()
    fig_stack.add_trace(go.Bar(x=daily["day"], y=daily["load_met_gwh"],
                               name="Load Met by Offshore", marker_color="#2ca02c"))
    fig_stack.add_trace(go.Bar(x=daily["day"], y=daily["unmet_gwh"],
                               name="Unmet Load", marker_color="#d3d3d3"))
    fig_stack.update_layout(barmode="stack", title=f"{month_name} Daily Load Coverage",
                            yaxis_title="Energy (GWh)", xaxis_title="Day")
    st.plotly_chart(fig_stack, width="stretch")

    fig_pct = go.Figure()
    fig_pct.add_trace(go.Bar(x=daily["day"], y=daily["coverage_pct"],
                             name="Covered by Offshore", marker_color="#2ca02c"))
    fig_pct.add_trace(go.Bar(x=daily["day"], y=100 - daily["coverage_pct"],
                             name="Unmet", marker_color="#d3d3d3"))
    fig_pct.update_layout(barmode="stack", title=f"{month_name} Daily Coverage (%)",
                          yaxis=dict(title="Coverage (%)", range=[0, 100]), xaxis_title="Day")
    st.plotly_chart(fig_pct, width="stretch")


def plot_day_view(df, day):
    day_df = df[df["day"] == day]

    day_met_gwh = day_df["load_met"].sum() / 1000
    day_load_gwh = day_df["load_scaled"].sum() / 1000
    fig_pie = px.pie(
        names=["Load Met", "Unmet Load"],
        values=[day_met_gwh, day_load_gwh - day_met_gwh],
        title=f"{day} Load Coverage (GWh)",
    )
    fig_pie.update_traces(hovertemplate="<b>%{label}</b><br>%{value:.3f} GWh<extra></extra>")
    st.plotly_chart(fig_pie, width="stretch")

    fig_stack = go.Figure()
    fig_stack.add_trace(go.Bar(x=day_df["hour"], y=day_df["load_met"],
                               name="Load Met by Offshore", marker_color="#2ca02c"))
    fig_stack.add_trace(go.Bar(x=day_df["hour"], y=day_df["unmet"],
                               name="Unmet Load", marker_color="#d3d3d3"))
    fig_stack.update_layout(barmode="stack", title=f"{day} Hourly Load Coverage",
                            yaxis_title="Energy (MWh)", xaxis_title="Hour")
    st.plotly_chart(fig_stack, width="stretch")

    day_pct = day_df.copy()
    day_pct["coverage_pct"] = 100 * day_pct["load_met"] / day_pct["load_scaled"]
    fig_pct = go.Figure()
    fig_pct.add_trace(go.Bar(x=day_pct["hour"], y=day_pct["coverage_pct"],
                             name="Covered by Offshore", marker_color="#2ca02c"))
    fig_pct.add_trace(go.Bar(x=day_pct["hour"], y=100 - day_pct["coverage_pct"],
                             name="Unmet", marker_color="#d3d3d3"))
    fig_pct.update_layout(barmode="stack", title=f"{day} Hourly Coverage (%)",
                          yaxis=dict(title="Coverage (%)", range=[0, 100]), xaxis_title="Hour")
    st.plotly_chart(fig_pct, width="stretch")
