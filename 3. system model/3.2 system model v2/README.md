# Offshore Wind + H₂ Storage Control Model

**Economic potential of storage solutions to meet demand fluctuations**

A short-term storage control model for a hypothetical offshore wind farm at (IN THE FUTURE but not yet: a scaled Alpha Ventus) coupled
with hydrogen energy storage.  Given hourly wind generation, electricity prices,
and demand forecasts, the model decides — for every hour of the year — how to
split the farm's output between **grid export**, **hydrogen production**, and
**curtailment**, then computes financial outcomes.

---

## Model Equations

All key mathematical relationships used in the model, collected in one place.

### Generation scaling (generation.py)

$$
P_{\text{farm},t} = P_{\text{national},t} \times \frac{C_{\text{target}}}{C_{\text{installed},t}} \times f_{\text{derate}}
$$

where $C_{\text{installed},t}$ is the monthly national installed offshore capacity (MW), looked up from Frauenhofer data.

### Electrolyser (hydrogen.py)

$$
\dot{m}_{\text{H}_2} = \frac{P_{\text{el}} \times 1000}{\eta_{\text{el}}} \quad \left[\frac{\text{kg}}{\text{h}}\right]
$$

where $\eta_{\text{el}}$ is specific energy consumption [kWh/kg] (default 55 kWh/kg), and $P_{\text{el}}$ is in MW (= MWh/h).

Marginal value of sending 1 MWh to electrolyser vs grid:

$$
V_{\text{H}_2} = \frac{1000}{\eta_{\text{el}}} \times p_{\text{H}_2} \quad \left[\frac{\text{€}}{\text{MWh}_{\text{elec}}}\right]
$$

With defaults: $(1000/55) \times 5 = 90.9$ €/MWh → prefer H₂ over grid when spot price < 90.9 €/MWh.

### Fuel cell (hydrogen.py)

$$
P_{\text{FC,out}} = \dot{m}_{\text{H}_2,\text{in}} \times \frac{\eta_{\text{FC}}}{1000} \quad \text{[MW]}
$$

where $\eta_{\text{FC}}$ = 16.7 kWh$_{\text{elec}}$/kg$_{\text{H}_2}$ ≈ 50% LHV efficiency  
(H₂ LHV ≈ 33.3 kWh/kg → $0.5 \times 33.3 \approx 16.65$ kWh/kg).

### Battery (battery.py) — √η split model

Charge leg ($\eta_c = \sqrt{\eta}$):

$$
E_{\text{stored}} = P_{\text{charge}} \times \sqrt{\eta}
$$

Discharge leg ($\eta_d = \sqrt{\eta}$):

$$
P_{\text{out}} = E_{\text{withdrawn}} \times \sqrt{\eta}
$$

Round-trip efficiency = $\eta_c \times \eta_d = \eta$ (default 0.90).  
The √η split is the correct symmetric formulation — applying all losses to one leg would bias the solver.

### H₂ tank dynamics (LP constraint)

$$
\text{SoC}_{\text{H}_2,t} = \text{SoC}_{\text{H}_2,t-1} + \frac{P_{\text{el},t} \times 1000}{\eta_{\text{el}}} - \frac{P_{\text{FC},t} \times 1000}{\eta_{\text{FC}}} - m_{\text{offtake},t}
$$

### Battery dynamics (LP constraint)

$$
\text{SoC}_{\text{batt},t} = \text{SoC}_{\text{batt},t-1} + P_{\text{bc},t} \cdot \sqrt{\eta} - \frac{P_{\text{bd},t}}{\sqrt{\eta}}
$$

### Power balance (LP constraint, every hour)

$$
\underbrace{P_{\text{grid},t} + P_{\text{el},t} + P_{\text{bc},t} + P_{\text{curtail},t}}_{\text{sinks}} = \underbrace{P_{\text{wind},t} + P_{\text{FC},t} + P_{\text{bd},t}}_{\text{sources}}
$$

### LP Objective — Revenue mode

$$
\max \sum_{t=1}^{T} \left[ \pi_t \cdot (P_{\text{grid},t} + P_{\text{FC},t}) + p_{\text{H}_2} \cdot m_{\text{offtake},t} - \lambda (P_{\text{bc},t} + P_{\text{bd},t}) \right]
$$

where $\pi_t$ = spot price [€/MWh], $p_{\text{H}_2}$ = H₂ offtake price [€/kg], $\lambda$ = battery cycling penalty [€/MWh].

### LP Objective — H₂ mode

$$
\max \sum_{t=1}^{T} \left[ \frac{1000}{\eta_{\text{el}}} \cdot P_{\text{el},t} - \frac{1000}{\eta_{\text{FC}}} \cdot P_{\text{FC},t} \right]
$$

(Maximise net H₂ produced; tiny grid tiebreaker term omitted here for clarity.)

### Economics (economics.py)

$$
R_{\text{grid},t} = P_{\text{grid},t} \times \pi_t \qquad
R_{\text{H}_2,t} = m_{\text{offtake},t} \times p_{\text{H}_2}
$$

$$
\text{Profit}_t = R_{\text{grid},t} + R_{\text{H}_2,t} - P_{\text{wind},t} \times c_{\text{opex}}
$$

### NPV — annuity present value (economics.py)

$$
\text{PV} = \sum_{n=1}^{N} \frac{\text{Profit}_{\text{annual}}}{(1+r)^n} = \text{Profit}_{\text{annual}} \times \frac{1-(1+r)^{-N}}{r}
$$

where $r$ = discount rate (default 8%), $N$ = project lifetime (default 25 years).  
**Note:** CAPEX not yet included — this is operating profit PV only.

---



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
│   │   ├── hydrogen.py            ← Electrolyser, H₂ tank, FuelCell models
│   │   ├── battery.py             ← Battery storage (√η split model)
│   │   ├── dispatch.py            ← Rule-based hourly decision engine (V1)
│   │   ├── dispatch_optimised.py  ← LP-optimised day-ahead dispatch (V2)
│   │   └── economics.py           ← Revenue, profit, NPV calculations
│   │
│   ├── scenarios/
│   │   ├── config.py              ← All parameters in a single dataclass
│   │   └── run_scenario.py        ← "Mother" script — wires everything
│   │
│   └── utils/
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

#### Fuel cell model (`hydrogen.py`)

A simple PEM fuel cell that converts stored H₂ back into electricity.
Modelled as a fixed electrical efficiency:

- **Capacity** (default 0 MW, i.e. disabled): maximum electrical output
- **Efficiency** (default 16.7 kWh_elec/kg_H₂): corresponds to ~50% LHV efficiency
  (H₂ LHV ≈ 33.3 kWh/kg → 50% × 33.3 = 16.65 kWh/kg)
- **Minimum load** (default 10%): below this the cell is off

Enable via `ScenarioConfig(fuel_cell_capacity_mw=20.0)`.  The fuel cell is only
useful with the optimised dispatch (V2) — the rule-based dispatch does not use it.

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

### Step 3b — LP-Optimised Dispatch (`dispatch_optimised.py`)

An alternative dispatch engine that replaces the rule-based logic with a
**linear programme (LP)** solved over a rolling 24-hour horizon.

#### How it works

Instead of making decisions one hour at a time, the optimiser sees the full
24-hour price and wind forecast upfront and finds the single best strategy
across all hours simultaneously.

For each 24-hour window it chooses **9 numbers per hour** (216 variables total):

| Variable | Meaning |
|---|---|
| `p_grid` | MW exported to grid |
| `p_el` | MW consumed by electrolyser |
| `p_fc` | MW generated by fuel cell (burns stored H₂) |
| `p_bc` | MW charging the battery |
| `p_bd` | MW discharging the battery |
| `soc_h2` | H₂ tank level at end of hour |
| `soc_batt` | Battery level at end of hour |
| `curtail` | MW curtailed / wasted |
| `h2_offtake` | kg H₂ sold this hour |

Subject to three hard physical constraints every hour:

1. **Power balance** — everything generated must go somewhere:
   `p_grid + p_el + p_bc + curtail = wind_gen + p_fc + p_bd`
2. **H₂ tank dynamics** — mass balance in the tank each hour
3. **Battery dynamics** — energy balance in the battery each hour

Plus capacity bounds (can't exceed rated MW, can't overfill tanks, etc.).

#### Two objectives

**`"revenue"` (default) — maximise profit:**
Maximise `Σ [price × p_grid + h2_price × h2_offtake − λ × (p_bc + p_bd)]`

The LP naturally learns to charge/electrolyse at 3am when prices are low, and
sell/discharge at 6pm when prices spike.  No fixed rules needed.
`λ` is the battery cycling penalty (default 1 €/MWh) to prevent unrealistic
churning.

**`"h2"` — maximise green H₂ volume:**
Maximise `Σ [el_rate × p_el − fc_rate × p_fc]`

Useful when you have a fixed industrial H₂ delivery contract and volume is what
matters, not price arbitrage.  The electrolyser runs as hard as wind and tank
allow.

#### Solver — swap point

The actual solving is isolated in one function `_solve_lp()`.  By default it
uses **scipy's HiGHS** solver (open-source, fast, ships with scipy — no extra
install needed).  A full-year run (8,760 hours, solved as 365 × 24-h windows)
takes a few seconds.

When a more powerful solver is available (e.g. Gurobi with an academic licence),
only `_solve_lp()` needs to change — everything else stays the same.  The comment
block in the code is labelled **SWAP POINT** for exactly this purpose.

#### Battery cycling penalty (√η model)

Battery round-trip efficiency is split across the charge and discharge legs:

```
energy_stored = power_in  × √η      (charge-leg loss)
power_out     = energy_out × √η     (discharge-leg loss)
```

This is the correct formulation — it makes charge and discharge symmetric and
avoids artefacts that arise from applying all losses to one leg.

#### Enabling the optimised dispatch

In `config.py` / the Streamlit sidebar:

```python
cfg = ScenarioConfig(
    use_optimised_dispatch=True,
    dispatch_objective="revenue",    # or "h2"
    dispatch_horizon_hours=24,       # 168 for weekly lookahead
    fuel_cell_capacity_mw=20.0,      # 0 = fuel cell disabled
)
```

`run_scenario.py` automatically routes through the optimiser when
`use_optimised_dispatch=True`.

#### Visualisation

`plot_optimised_dispatch(df, day="YYYY-MM-DD")` produces a 4-panel figure:
- Panel 1: H₂ Tank State of Charge
- Panel 2: Power flows (wind, grid, electrolyser, fuel cell, battery, curtailment)
- Panel 3: Electricity price with mean dashed line
- Panel 4: Cumulative revenue [k€]

Inspired by the [RTC-Tools BESS scheduling demo](https://portfolioenergy-bess-demo.readthedocs.io/en/latest/scheduling.html).

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

The model produces one row per hour with columns matching Ricardo's xcel sheet format:

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
| `fc_power_mwh` | MWh | Fuel cell electrical output *(optimised dispatch only)* |
| `fc_h2_consumed_kg` | kg | H₂ consumed by fuel cell *(optimised dispatch only)* |

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

- [ ] Electrolyser ramp constraints and degradation over life
- [ ] Price-responsive H₂ discharge (sell H₂ when electricity price is high)
- [ ] CAPEX model (LCOE, LCOH, IRR). LCOE could include CAPEX and decomissioning?
- [ ] Battery dispatch integration
- [ ] Battery passive discharge, cycle life degradation
- [ ] Ancillary services revenue
- [ ] Multiple site comparison (East Anglia, UK)
- [ ] Containerisation for deployment
- [ ] Sensitivity / scenario sweep tools
- [ ] Maintenence / downtime 
- [ ] Confirm no situation where the BESS is being charged and the remainder is being curtailed where the remainder could be producing H2.
- [ ] different operational strategies and see how it affects NPV/LCOH e.g. discharge battery every evening at peak house regardless of price, or playing around with rules for discharging when price is above a seasonal average.