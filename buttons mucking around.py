import streamlit as st

st.title("Renewable generation vs load")

load = st.slider("Total load (MW)", 0, 10000, 5000, step=100)
wind_capacity = st.slider("Wind capacity (MW)", 0, 8000, 2000, step=100)
solar_capacity = st.slider("Solar capacity (MW)", 0, 8000, 1000, step=100)

# Dummy generation assumptions
wind_generation = wind_capacity * 0.30  # assume 30% capacity factor
solar_generation = solar_capacity * 0.20  # assume 20% capacity factor

renewable_generation = wind_generation + solar_generation
load_met = min(load, renewable_generation)
unmet_load = max(0, load - renewable_generation)
surplus = max(0, renewable_generation - load)

st.metric("Wind generation (MW)", f"{wind_generation:.0f}")
st.metric("Solar generation (MW)", f"{solar_generation:.0f}")
st.metric("Total renewable generation (MW)", f"{renewable_generation:.0f}")
st.metric("Load met by renewables (MW)", f"{load_met:.0f}")
st.metric("Unmet load (MW)", f"{unmet_load:.0f}")
st.metric("Surplus renewable (MW)", f"{surplus:.0f}")

st.write("---")
st.write(
    f"Renewable share of load: "
    f"{(load_met / load * 100):.1f}%"
    if load > 0 else "Load is zero"
)