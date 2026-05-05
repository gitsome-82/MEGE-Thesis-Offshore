# Francisco's WFA Hybrid Storage Model

Recreation of the techno-economic dispatch model from:

> **Hybrid Storage Solutions for Offshore Wind Farms: A study considering the WindFloat Atlantic**  
> Francisco Heitor Peixoto Pereira, MEng Thesis, IST Lisbon, October 2025

---

## Model Overview

Three energy storage configurations for a **1 GW hypothetical expansion** of WindFloat Atlantic
(Viana do Castelo, Portugal), modelled over a **25-year** project lifetime using **2023–2024**
hourly data tiled repeatedly.

| Scenario | Storage | Control variables |
|---|---|---|
| **HESS** | 350 MW PEMEL electrolyzer + H₂ tanks (VT h) | Single threshold `p_storage` (optimised globally) |
| **BESS** | 100 MW / 200 MWh LIB + inverter | Two thresholds `p_charge`, `p_discharge` (optimised daily) |
| **HybESS** | HESS + BESS combined | Same two thresholds as BESS; BESS prioritised |

All dispatch is **rule-based** (no MILP). NPV is the primary economic indicator,
complemented by LCOH (€/kg) and LCOS (€/MWh).

---

## Quick Start

```bash
# From repo root, activate the venv first:
.venv\Scripts\activate

# Run HESS (uses default thesis parameters, VT=264h, p_H2=8 €/kg)
python "2.5. cisco's model/HESS/run_hess.py"

# Run BESS
python "2.5. cisco's model/BESS/run_bess.py"

# Run HybESS (basic + enhanced strategy)
python "2.5. cisco's model/HybESS/run_hybess.py"
```

---

## Data Requirements

### Wind power
Uses actual ENTSO-E Portugal offshore wind generation — already present at:
```
DATA/Portugal Data/Gen data/{year}.csv
```
Since WFA (25.2 MW) is Portugal's only offshore wind farm, the national offshore total equals
WFA output. The capacity-factor profile is scaled up proportionally to the 1 GW hypothetical farm.
This is more accurate than a synthetic power-curve approach as it captures real availability,
curtailment, and weather conditions.

### Electricity prices
Uses ENTSO-E day-ahead price files — already present at:
```
DATA/Portugal Data/GUI_ENERGY_PRICES_<start>-<end>.csv
```
Source: <https://transparency.entsoe.eu/> → Day Ahead Prices → Portugal  
**Resolution note:** files up to end-2024 are hourly; from 2025 onwards they are 15-min.
The loader resamples automatically to hourly (mean within each hour) so no manual conversion
is needed.

### Fallback
If no price files are found, a flat **50 €/MWh** price is used with a warning.

---

## Project Structure

```
2.5. cisco's model/
├── README.md
├── common/
│   └── loaders.py         ← Wind + price data loading (ENTSO-E sources), 25-yr tiling
├── HESS/
│   ├── config.py          ← HESSConfig dataclass (Table 6.1 parameters)
│   ├── dispatch.py        ← simulate_hess() — Figure 6.5 flowchart
│   ├── economics.py       ← CAPEX, annual cash flows, NPV, LCOH
│   └── run_hess.py        ← CLI: optimise p_storage, run 25-yr simulation
├── BESS/
│   ├── config.py          ← BESSConfig dataclass (Table 6.2 parameters)
│   ├── dispatch.py        ← simulate_bess() — Figure 6.7 flowchart, daily optimisation
│   ├── economics.py       ← CAPEX, cash flows, NPV, LCOS
│   └── run_bess.py        ← CLI runner
└── HybESS/
    ├── config.py          ← HybESSConfig (combines HESS + BESS)
    ├── dispatch.py        ← simulate_hybess() — Figures 6.9 & 6.10 + enhanced strategy
    ├── economics.py       ← combined NPV
    └── run_hybess.py      ← CLI runner
```

---

## Key Assumptions (from thesis)

- Wind farm capacity: **1 GW** offshore
- Transmission losses (HVAC, 20 km): **5%**
- Wind farm OPEX: **30 €/MWh** (curtailment floor — sell only if price > 30 €/MWh)
- Project lifetime: **25 years**
- Discount rate: **7%**
- Price/wind data: 2023–2024 tiled over 25 years (no wind farm CAPEX in NPV)
- H₂ sold into Portgas gas grid (certified for 20% H₂ blend)
- NPV = incremental cash flows (storage vs base case, no wind farm CAPEX)

---

## Reference Results (thesis, Table 7.1)

| Case | Installed power | Storage | NPV | LCOH/LCOS |
|---|---|---|---|---|
| HESS | 350 MW EL | VT=264 h | **+503.5 M€** | 4.53 €/kg |
| BESS | 100 MW | 200 MWh | −17.33 M€ | 126.32 €/MWh |
| HybESS | 350+100 MW | 200 MWh + VT=216 h | −104.4 M€ | — |
| HybESS Enhanced | 350+100 MW | 200 MWh + VT=216 h | **+4.69 M€** | 4.60 €/kg |

*HESS and HybESS: H₂ price = 8 €/kg. BESS: 2 h autonomy.*
