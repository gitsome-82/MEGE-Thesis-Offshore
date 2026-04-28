# Offshore Wind + H₂ Storage Control Model

**WP5.4 — Economic potential of storage solutions to meet demand fluctuations**

A short-term storage control model for a hypothetical offshore wind farm at (a scaled Alpha Ventus) coupled
with hydrogen energy storage.  Given hourly wind generation, electricity prices,
and demand forecasts, the model decides — for every hour of the year — how to
split the farm's output between **grid export**, **hydrogen production**, and
**curtailment**, then computes financial outcomes.

---

## Quick Start

```bash
# From the "3. system model/" directory:

# 1. Install dependencies (one time)
pip install streamlit pandas plotly

# 2a. Run the Streamlit dashboard (interactive, recommended)
streamlit run app/streamlit_app.py

# 2b. Or run a scenario from the command line
python -m src.scenarios.run_scenario
```

The CLI run prints an annual summary and saves an hourly CSV to `outputs/`.

---

## Project Structure

```
3. system model/
│
├── app/
│   └── streamlit_app.py           ← Interactive dashboard (Streamlit)
│
├── src/
│   ├── data/
│   │   ├── loaders.py             ← Loads generation, load, price CSVs
│   │   └── preprocess.py          ← SMARD timestamp & number parsing
│   │
│   ├── models/
│   │   ├── generation.py          ← Scales national output → target farm
│   │   ├── hydrogen.py            ← Electrolyser + H₂ tank state objects
│   │   ├── battery.py             ← Battery storage (placeholder)
│   │   ├── dispatch.py            ← THE BRAIN — hourly decision engine
│   │   └── economics.py           ← Revenue, profit, NPV calculations
│   │
│   ├── scenarios/
│   │   └── run_scenario.py        ← "Mother" script — wires everything
│   │
│   └── utils/
│       └── config.py              ← All parameters in a single dataclass
│
├── data/                          ← raw/ and processed/ folders
├── outputs/                       ← Scenario CSV exports
├── notebooks/                     ← Exploratory notebooks
└── model.py                       ← Old demo (archived, unused)
```

---

## How It Works — Full Operating Logic

The model runs in **four sequential steps** for each scenario:

### Step 1 — Load Input Data (`loaders.py`)

Three hourly time series are loaded for the chosen year:

| Series | Source | Unit |
|---|---|---|
| **Offshore wind generation** | SMARD or Frauenhofer energy-charts | MWh/h |
| **System load (demand)** | SMARD or Frauenhofer | MWh/h |
| **Day-ahead electricity price** | Frauenhofer spot price file | EUR/MWh |

If no price data file is found for the chosen year, a **flat fallback price of
50 EUR/MWh** is used for every hour.  This is a known limitation — we recommend
sourcing proper price data for each year under study.

### Step 2 — Scale Generation (`generation.py`)

We do **not** have site-specific Alpha Ventus output data.  Instead, we take the
**total German offshore wind generation** (national fleet) and scale it
proportionally to represent a single hypothetical farm:

```
gen_scaled = national_generation × (target_farm_MW / installed_national_capacity_MW)
```

**What this means:**  if Germany's installed offshore capacity in January 2023 was
8,350 MW and the national fleet generated 2,000 MWh in a given hour, a
hypothetical 500 MW farm would be attributed:

```
2,000 × (500 / 8,350) = 119.8 MWh
```

**Assumption:**  the hypothetical farm has the same capacity factor, availability,
wake losses, and weather profile as the national average offshore fleet.  This is
a simplification — Alpha Ventus's specific North Sea location would have its own
wind characteristics.  For an MVP case study this is defensible, provided it is
clearly stated.

**Monthly installed capacity** is looked up from Frauenhofer data, so the scaling
denominator updates each month as new turbines come online nationally.

Two optional modifiers are available:

- **Derate factor** (default 1.0): a simple multiplier to reduce output.  Setting
  it to 0.9 simulates a 10% availability loss (downtime, cable losses, larger-farm
  wake effects, etc.) without modelling each loss individually.

- **Smoothing window** (default 1 = no smoothing): a rolling-average window in
  hours.  For a very large hypothetical farm, real output would be geographically
  smoother than a single-site profile.

### Step 3 — Hourly Dispatch (`dispatch.py`)

This is the core of the storage control model.  For **every hour** of the year,
the engine decides how to allocate the farm's generation.

#### Order of operations each timestep

```
Step 0:  H₂ TANK OFFTAKE
         → Withdraw a fixed hourly amount from the tank (buyer takes delivery)
         → Happens regardless of generation — it's a demand-side schedule

Step 1:  CURTAILMENT CHECK
         → Is the spot electricity price above our operating cost floor?
         → If price ≤ floor → do NOT sell to grid (you'd lose money)

Step 2:  ALLOCATION
         → Compare H₂ value per MWh vs grid spot price
         → Route generation to the more profitable channel
         → Whatever can't go anywhere → curtailed

Step 3:  BATTERY (if enabled)
         → Charge battery with any remaining energy

Step 4:  CURTAILMENT
         → Anything still left over is curtailed (wasted)
```

#### H₂ vs Grid price comparison

The model pre-computes the **marginal value of sending 1 MWh to the electrolyser**
rather than selling it on the grid:

```
H₂ value per MWh = (1000 / efficiency_kWh_per_kg) × h2_price_EUR_per_kg
```

With default parameters (55 kWh/kg efficiency, 5 EUR/kg H₂ price):

```
(1000 / 55) × 5 = 90.9 EUR/MWh
```

This means: every MWh sent to the electrolyser produces 18.2 kg of hydrogen,
sold at 5 EUR/kg = 90.9 EUR.  If the spot electricity price that hour is below
90.9 EUR/MWh, it's more profitable to make hydrogen than to sell power.

**Note:** if `prioritise_h2 = True` (the default), hydrogen production is
*always* preferred over grid sale, regardless of the price comparison.  Set it to
`False` to enable pure economic switching.

#### Curtailment floor (operating cost)

The **curtailment price threshold** defaults to the operating cost (`opex_eur_per_mwh`,
default = 23 EUR/MWh).  This represents the cost of running the turbines
(maintenance, staff, insurance, vessel hire, etc.) that must be paid regardless of
what happens to the electricity.

If the spot price drops below this floor, selling to the grid would lose money
on every MWh exported.  In that case the model will:

1. Send power to the electrolyser (if profitable: H₂ value > 0 and tank has space)
2. Curtail whatever remains

The 23 EUR/MWh default is a representative industry estimate for offshore wind
O&M costs.  IRENA's *Renewable Power Generation Costs* reports and BVG Associates'
*Guide to an Offshore Wind Farm* both cite ranges of roughly 20–30 EUR/MWh for
European offshore wind O&M, depending on distance to shore, water depth, and
turbine age.  This parameter is fully adjustable in the dashboard sidebar.

#### Electrolyser model (`hydrogen.py`)

The electrolyser is modelled as a simple PEM unit with three characteristics:

- **Capacity** (default 100 MW): maximum electrical input
- **Specific consumption** (default 55 kWh/kg): energy needed per kg of H₂
- **Minimum load** (default 10% of capacity): below this, the electrolyser
  switches off entirely (real electrolysers cannot run at arbitrarily low loads)

**Current simplifications:**
- No ramp-up time — the electrolyser starts/stops instantaneously each hour
- No degradation — efficiency is constant over the project lifetime
- No compressor energy — going into the tank is "free" (in reality, compression
  to high-pressure storage takes ~5–10% of the energy)

#### H₂ tank and discharge rule

The hydrogen tank is a simple state-of-charge model: it has a maximum capacity
in kg and tracks how full it is each hour.

**Discharge rule — fixed daily offtake:**

The tank drains via a **fixed daily offtake** (default 2,000 kg/day), spread
evenly across 24 hours (83.3 kg/hour).  This represents a **steady industrial
buyer** — for example a refinery, ammonia plant, or hydrogen refuelling depot —
connected via pipeline under a delivery contract.  The buyer takes delivery on a
fixed schedule regardless of how much wind is blowing or what the electricity
price is.

This means:
- The tank **cycles continuously**: charging from the electrolyser during
  production hours, draining via offtake every hour
- If the tank is empty, the buyer misses that hour's delivery (no penalty
  modelled yet)
- H₂ revenue is earned **when hydrogen is sold (offtake)**, not when it is
  produced — this is more financially realistic

**Why this approach?**  A "produce and immediately sell" model would make the
tank pointless (no storage).  A demand-profile-based model would need external
H₂ demand data we don't have.  The fixed-offtake approach is the simplest
defensible assumption that makes the tank cycle realistically and can be stated
clearly in the thesis methodology.

**Sizing consideration:**  with a 100 MW electrolyser at 55 kWh/kg, peak
production is ~1,818 kg/hour.  A 10,000 kg tank with 2,000 kg/day offtake
(83.3 kg/hr) will tend to fill up and stay near full, since production rate
far exceeds withdrawal.  To see more dynamic cycling, either increase the daily
offtake, decrease the electrolyser size, or increase the tank capacity.

### Step 4 — Economics (`economics.py`)

After dispatch, financial columns are computed for every hour:

| Column | Formula |
|---|---|
| `grid_revenue_eur` | `to_grid_mwh × price_eur_per_mwh` |
| `h2_revenue_eur` | `h2_offtake_kg × h2_selling_price_eur_per_kg` |
| `ancillary_revenue_eur` | 0 (placeholder for future work) |
| `total_revenue_eur` | sum of above |
| `opex_eur` | `generation_mwh × opex_eur_per_mwh` |
| `profit_eur` | `total_revenue - opex` |

**Annual summary** aggregates these into totals (TWh generated, tonnes H₂
produced/sold, curtailment rate, total revenue and profit).

**NPV** is computed as a simple constant-annuity discounted cash flow over the
project lifetime (default 25 years at 8% discount rate).  CAPEX is not yet
included — this is a revenue/profit model only for now.

---

## Example Run (Default Parameters)

With default settings (500 MW farm, 100 MW electrolyser, 55 kWh/kg, 10t tank,
2,000 kg/day offtake, 5 EUR/kg H₂, SMARD 2023 data):

| Metric | Value |
|---|---|
| Annual generation | 1,400 GWh |
| To grid | 1,359 GWh |
| H₂ produced | 740 tonnes |
| H₂ sold (offtake) | 730 tonnes |
| Curtailed | ~0 GWh |
| Grid revenue | €67.9M |
| H₂ revenue | €3.7M |
| Total revenue | €71.6M |
| Opex | €32.2M |
| Profit | €39.4M |
| PV of operating profit (25yr, 8%) | €420.6M = €39.4M × 10.7 annuity factor — **not true project NPV, no CAPEX** |

H₂ revenue is modest here because the tank is small (10t) and daily offtake is
only 2t/day.  The electrolyser reaches full tank quickly, then only tops up what
the buyer withdraws.  Most generation goes to the grid.

---

## Hourly Output Table

The model produces one row per hour with columns matching the supervisor's
requested format:

| Column | Unit | Description |
|---|---|---|
| `timestamp` | datetime | Hour |
| `action` | string | What happened: `grid`, `electrolyse + grid`, `curtail`, etc. |
| `generation_mwh` | MWh | Farm output this hour |
| `demand_mwh` | MWh | System demand (context, not a constraint) |
| `price_eur_per_mwh` | EUR/MWh | Day-ahead spot price |
| `to_grid_mwh` | MWh | Sold to grid |
| `to_electrolyser_mwh` | MWh | Sent to electrolyser |
| `h2_produced_kg` | kg | H₂ produced this hour |
| `h2_offtake_kg` | kg | H₂ sold (withdrawn from tank) |
| `tank_soc_kg` | kg | Tank state of charge after this hour |
| `energy_flux_battery_kwh` | kWh | Battery charge (0 if battery disabled) |
| `curtailed_mwh` | MWh | Wasted energy |
| `grid_revenue_eur` | EUR | Revenue from grid sale |
| `h2_revenue_eur` | EUR | Revenue from H₂ sale |
| `ancillary_revenue_eur` | EUR | Ancillary services (placeholder) |
| `total_revenue_eur` | EUR | Sum of all revenue |
| `opex_eur` | EUR | Operating cost |
| `profit_eur` | EUR | Revenue minus opex |

---

## Key Assumptions & Limitations

1. **Generation proxy:** national German offshore fleet output is used as a proxy
   for single-farm output.  The farm is assumed to have the same capacity factor
   and availability as the national average.

2. **No grid congestion:** the farm can always export whatever it wants to the
   grid.  There are no transmission constraints or curtailment orders from the TSO.

3. **Demand is context only:** system demand (load) is recorded in the output
   table for reference, but the farm does not "serve" local demand directly — it
   sells to the wholesale market.

4. **Price data availability:** spot prices are loaded from Frauenhofer energy-charts.
   If the file is not available for the chosen year, a flat 50 EUR/MWh fallback is
   used.  This significantly affects dispatch decisions and should be replaced with
   real data.

5. **H₂ price is constant:** a single offtake price is used for the whole year.
   Real hydrogen contracts may have indexation, seasonal variation, or
   volume-dependent pricing.

6. **No electrolyser dynamics:** start-up/shut-down is instantaneous, no ramp
   constraints, no efficiency degradation over time, no compressor energy.

7. **No CAPEX:** the economic model computes revenue and operating profit only.
   CAPEX (turbines, electrolyser, tank, grid connection) is not yet included.
   The metric labelled "PV of Operating Profit" is the **present value of this
   year's operating profit repeated over the project lifetime** — it is an annuity
   calculation, not a true project NPV.  With a 25-year horizon at 8% discount
   rate the annuity factor is ~10.7, so this figure will always be roughly 10×
   the annual profit shown.  A true project NPV would subtract CAPEX upfront,
   which for a 500 MW offshore farm plus electrolyser would typically be €1–2B+,
   likely making the net figure much lower or negative at current H₂ prices.

8. **Battery is a placeholder:** the battery model exists structurally but defaults
   to 0 capacity (disabled).  To be developed as a future extension.

9. **Ancillary services:** a placeholder column exists but is set to zero.  To be
   developed in collaboration with the ancillary-services workstream.

---

## Configuration Parameters

All parameters live in `src/utils/config.py` as a `ScenarioConfig` dataclass.
They can be overridden in code, via the Streamlit sidebar, or by creating a
custom config.

| Parameter | Default | Description |
|---|---|---|
| `target_farm_capacity_mw` | 500 | Hypothetical farm size [MW] |
| `alpha_ventus_capacity_mw` | 60 | Alpha Ventus reference capacity [MW] |
| `derate_factor` | 1.0 | Availability/loss multiplier (1.0 = none) |
| `smoothing_window` | 1 | Rolling average window [hours] |
| `electrolyser_capacity_mw` | 100 | Max electrical input to electrolyser [MW] |
| `electrolyser_efficiency_kwh_per_kg` | 55 | Specific energy consumption [kWh/kg H₂] |
| `electrolyser_min_load_frac` | 0.10 | Min partial load (fraction of capacity) |
| `tank_capacity_kg` | 10,000 | Max H₂ storage [kg] |
| `tank_initial_soc_kg` | 0 | Starting tank level [kg] |
| `h2_daily_offtake_kg` | 2,000 | Fixed daily H₂ withdrawal [kg/day] |
| `h2_selling_price_eur_per_kg` | 5.0 | Green H₂ offtake price [EUR/kg] |
| `opex_eur_per_mwh` | 23.0 | Operating cost floor [EUR/MWh] |
| `curtailment_price_threshold_eur` | None | Override curtailment floor [EUR/MWh] |
| `prioritise_h2` | True | Always prefer H₂ over grid sale |
| `discount_rate` | 0.08 | NPV discount rate |
| `project_lifetime_years` | 25 | NPV horizon [years] |
| `data_source` | "SMARD" | Input data source |
| `year` | 2023 | Simulation year |

---

## Future Work

- [ ] Electrolyser ramp constraints and degradation
- [ ] Price-responsive H₂ discharge (sell H₂ when electricity price is high)
- [ ] CAPEX model (LCOE, LCOH, IRR)
- [ ] Battery dispatch integration
- [ ] Ancillary services revenue
- [ ] Multiple site comparison (East Anglia, UK)
- [ ] Containerisation for deployment
- [ ] Sensitivity / scenario sweep tools
