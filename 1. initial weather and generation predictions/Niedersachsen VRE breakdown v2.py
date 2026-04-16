# Niedersachsen VRE breakdown v3.py
"""
One input date -> automatically shows:
  1) that DAY (hourly MW + hourly % share)
  2) that MONTH (daily MWh/day + daily % share)
  3) the FULL YEAR (12-month totals MWh/month + % share)

DATE can be:
  - "MM-DD"  e.g. "06-15"  (year inferred from CSV index)
  - "YYYY-MM-DD" e.g. "2021-06-15"

CSV expectations:
  PV:
    - typical_year_pv_niedersachsen.csv (gen_mw or energy_mwh)
    - typical_daily_energy_niedersachsen.csv (energy_mwh)
    - typical_monthly_energy_niedersachsen.csv (energy_mwh)
  Wind:
    - typical_year_wind_niedersachsen.csv (gen_onshore_mw, gen_offshore_mw)
    - typical_daily_energy_wind_niedersachsen.csv (energy_onshore_mwh, energy_offshore_mwh)
    - typical_monthly_energy_wind_niedersachsen.csv (energy_onshore_mwh, energy_offshore_mwh)

Deps:
  pip install pandas matplotlib
Recommended for popup:
  pip install pyqt6
"""

from __future__ import annotations

# =============================================================================
# ============================ 🔥 CHANGE ME HERE 🔥 ============================
# =============================================================================
CONFIG = {
    "DATE": "12-15",  # format "06-15" or "2021-06-15"

    "PV_YEAR_CSV": r"C:\Users\IanPe\OneDrive - Universidade de Lisboa\Documents\IST\MEGE\~Thesis Sem 4 26\DWD data\Hourly Solar\typical_year_pv_niedersachsen.csv",
    "WIND_YEAR_CSV": r"C:\Users\IanPe\OneDrive - Universidade de Lisboa\Documents\IST\MEGE\~Thesis Sem 4 26\DWD data\Hourly Wind\typical_year_wind_niedersachsen.csv",

    "PV_DAILY_CSV": r"C:\Users\IanPe\OneDrive - Universidade de Lisboa\Documents\IST\MEGE\~Thesis Sem 4 26\DWD data\Hourly Solar\typical_daily_energy_niedersachsen.csv",
    "WIND_DAILY_CSV": r"C:\Users\IanPe\OneDrive - Universidade de Lisboa\Documents\IST\MEGE\~Thesis Sem 4 26\DWD data\Hourly Wind\typical_daily_energy_wind_niedersachsen.csv",

    "PV_MONTHLY_CSV": r"C:\Users\IanPe\OneDrive - Universidade de Lisboa\Documents\IST\MEGE\~Thesis Sem 4 26\DWD data\Hourly Solar\typical_monthly_energy_niedersachsen.csv",
    "WIND_MONTHLY_CSV": r"C:\Users\IanPe\OneDrive - Universidade de Lisboa\Documents\IST\MEGE\~Thesis Sem 4 26\DWD data\Hourly Wind\typical_monthly_energy_wind_niedersachsen.csv",

    "SAVE_DIR": None,     # e.g. r"C:\Users\IanPe\Desktop\vre_plots" or None
    "ALWAYS_SHOW": True,  # popup windows
}
# =============================================================================
# =============================================================================


# ---- Force GUI backend (MUST be before importing pyplot) ---------------------
import os
import importlib

os.environ.setdefault("MPLBACKEND", "")

import matplotlib


def _can_import(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except Exception:
        return False


def _force_best_backend() -> str:
    if any(_can_import(m) for m in ("PyQt6", "PySide6", "PyQt5", "PySide2")):
        matplotlib.use("QtAgg", force=True)
        return "QtAgg"
    if _can_import("tkinter"):
        matplotlib.use("TkAgg", force=True)
        return "TkAgg"
    matplotlib.use("Agg", force=True)
    return "Agg"


_FORCE_BACKEND = _force_best_backend()
# -----------------------------------------------------------------------------


from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


def _read_csv_with_dt_index(path: Path) -> pd.DataFrame:
    """
    Reads CSV where the datetime is in "Unnamed: 0" (or first column),
    and coerces all other columns to numeric floats (handles comma decimals).
    """
    df = pd.read_csv(path)

    dt_col = "Unnamed: 0" if "Unnamed: 0" in df.columns else df.columns[0]
    df[dt_col] = pd.to_datetime(df[dt_col], errors="coerce")

    for c in df.columns:
        if c == dt_col:
            continue
        df[c] = (
            df[c]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.strip()
        )
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=[dt_col]).set_index(dt_col).sort_index()
    return df


def _pv_hourly_mw(pv_year: pd.DataFrame) -> pd.Series:
    if "gen_mw" in pv_year.columns:
        return pv_year["gen_mw"].astype(float).rename("solar_mw")
    if "energy_mwh" in pv_year.columns:
        return pv_year["energy_mwh"].astype(float).rename("solar_mw")
    raise ValueError("PV year CSV missing gen_mw or energy_mwh")


def _wind_hourly_mw(wind_year: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    for c in ("gen_onshore_mw", "gen_offshore_mw"):
        if c not in wind_year.columns:
            raise ValueError(f"Wind year CSV missing {c}")
    return (
        wind_year["gen_onshore_mw"].astype(float).rename("onshore_mw"),
        wind_year["gen_offshore_mw"].astype(float).rename("offshore_mw"),
    )


def _combine_hourly(pv_year_path: Path, wind_year_path: Path) -> pd.DataFrame:
    pv_year = _read_csv_with_dt_index(pv_year_path)
    wind_year = _read_csv_with_dt_index(wind_year_path)

    solar = _pv_hourly_mw(pv_year)
    onshore, offshore = _wind_hourly_mw(wind_year)

    df = pd.concat([solar, onshore, offshore], axis=1).fillna(0.0)
    df = df.astype(float)
    df["total_mw"] = df[["solar_mw", "onshore_mw", "offshore_mw"]].sum(axis=1)
    return df


def _combine_daily(pv_daily_path: Path, wind_daily_path: Path) -> pd.DataFrame:
    pv_d = _read_csv_with_dt_index(pv_daily_path)
    w_d = _read_csv_with_dt_index(wind_daily_path)

    if "energy_mwh" not in pv_d.columns:
        raise ValueError("PV daily CSV missing energy_mwh")
    for c in ("energy_onshore_mwh", "energy_offshore_mwh"):
        if c not in w_d.columns:
            raise ValueError(f"Wind daily CSV missing {c}")

    idx = pv_d.index.union(w_d.index).sort_values()
    df = pd.DataFrame(index=idx)
    df["solar_mwh"] = pv_d["energy_mwh"].astype(float)
    df["onshore_mwh"] = w_d["energy_onshore_mwh"].astype(float)
    df["offshore_mwh"] = w_d["energy_offshore_mwh"].astype(float)
    df = df.fillna(0.0).astype(float)
    df["total_mwh"] = df[["solar_mwh", "onshore_mwh", "offshore_mwh"]].sum(axis=1)
    return df


def _combine_monthly(pv_monthly_path: Path, wind_monthly_path: Path) -> pd.DataFrame:
    pv_m = _read_csv_with_dt_index(pv_monthly_path)
    w_m = _read_csv_with_dt_index(wind_monthly_path)

    if "energy_mwh" not in pv_m.columns:
        raise ValueError("PV monthly CSV missing energy_mwh")
    for c in ("energy_onshore_mwh", "energy_offshore_mwh"):
        if c not in w_m.columns:
            raise ValueError(f"Wind monthly CSV missing {c}")

    idx = pv_m.index.union(w_m.index).sort_values()
    df = pd.DataFrame(index=idx)
    df["solar_mwh"] = pv_m["energy_mwh"].astype(float)
    df["onshore_mwh"] = w_m["energy_onshore_mwh"].astype(float)
    df["offshore_mwh"] = w_m["energy_offshore_mwh"].astype(float)
    df = df.fillna(0.0).astype(float)
    df["total_mwh"] = df[["solar_mwh", "onshore_mwh", "offshore_mwh"]].sum(axis=1)
    return df


def _daily_from_hourly(hourly: pd.DataFrame) -> pd.DataFrame:
    d = hourly[["solar_mw", "onshore_mw", "offshore_mw"]].resample("D").sum()
    d = d.rename(columns={"solar_mw": "solar_mwh", "onshore_mw": "onshore_mwh", "offshore_mw": "offshore_mwh"})
    d["total_mwh"] = d[["solar_mwh", "onshore_mwh", "offshore_mwh"]].sum(axis=1)
    return d.astype(float)


def _monthly_from_daily(daily: pd.DataFrame) -> pd.DataFrame:
    m = daily[["solar_mwh", "onshore_mwh", "offshore_mwh"]].resample("M").sum()
    m["total_mwh"] = m[["solar_mwh", "onshore_mwh", "offshore_mwh"]].sum(axis=1)
    return m.astype(float)


def _shares(df: pd.DataFrame, cols: list[str], total_col: str) -> pd.DataFrame:
    denom = df[total_col].replace(0.0, pd.NA)
    out = df[cols].div(denom, axis=0).fillna(0.0)
    return out.astype(float)


def _maybe_save(fig: plt.Figure, save_dir: Path | None, filename: str) -> None:
    if not save_dir:
        return
    save_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(save_dir / filename, dpi=200, bbox_inches="tight")


def _infer_full_date_and_month(hourly_index: pd.DatetimeIndex, date_str: str) -> tuple[str, str]:
    s = date_str.strip()
    years = sorted({int(y) for y in hourly_index.year.unique()})
    if not years:
        raise ValueError("Could not infer year from hourly index.")
    inferred_year = years[0]

    if len(s) == 5 and s[2] == "-":  # MM-DD
        full = f"{inferred_year:04d}-{s}"
    else:
        full = s

    dt = pd.to_datetime(full, errors="raise")
    full_date = f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"
    month = f"{dt.year:04d}-{dt.month:02d}"
    return full_date, month


def _month_slice(df: pd.DataFrame, yyyy_mm: str) -> pd.DataFrame:
    start = pd.to_datetime(f"{yyyy_mm}-01")
    end = start + pd.offsets.MonthEnd(1)
    return df.loc[start:end]


def _plot_day(hourly: pd.DataFrame, full_date: str, save_dir: Path | None) -> None:
    day_df = hourly.loc[full_date].copy()
    share = _shares(day_df, ["solar_mw", "onshore_mw", "offshore_mw"], "total_mw")

    fig = plt.figure(figsize=(12, 7))
    ax1 = fig.add_subplot(2, 1, 1)
    ax1.stackplot(
        day_df.index,
        day_df["solar_mw"].to_numpy(dtype=float),
        day_df["onshore_mw"].to_numpy(dtype=float),
        day_df["offshore_mw"].to_numpy(dtype=float),
        labels=["Solar", "Onshore wind", "Offshore wind"],
    )
    ax1.set_title(f"Niedersachsen VRE (MW) — Day: {full_date}")
    ax1.set_ylabel("MW")
    ax1.grid(True)
    ax1.legend(loc="upper left")

    ax2 = fig.add_subplot(2, 1, 2)
    ax2.stackplot(
        share.index,
        (share["solar_mw"] * 100).to_numpy(dtype=float),
        (share["onshore_mw"] * 100).to_numpy(dtype=float),
        (share["offshore_mw"] * 100).to_numpy(dtype=float),
        labels=["Solar", "Onshore wind", "Offshore wind"],
    )
    ax2.set_title("Share of VRE (%) by hour")
    ax2.set_ylabel("% of VRE")
    ax2.set_ylim(0, 100)
    ax2.grid(True)
    ax2.legend(loc="upper left")

    fig.tight_layout()
    _maybe_save(fig, save_dir, f"vre_day_{full_date}.png")


def _plot_month(daily: pd.DataFrame, yyyy_mm: str, save_dir: Path | None) -> None:
    m = _month_slice(daily, yyyy_mm)
    share = _shares(m, ["solar_mwh", "onshore_mwh", "offshore_mwh"], "total_mwh")

    fig = plt.figure(figsize=(12, 7))
    ax1 = fig.add_subplot(2, 1, 1)
    ax1.bar(m.index, m["solar_mwh"].to_numpy(dtype=float), label="Solar")
    ax1.bar(
        m.index,
        m["onshore_mwh"].to_numpy(dtype=float),
        bottom=m["solar_mwh"].to_numpy(dtype=float),
        label="Onshore wind",
    )
    ax1.bar(
        m.index,
        m["offshore_mwh"].to_numpy(dtype=float),
        bottom=(m["solar_mwh"] + m["onshore_mwh"]).to_numpy(dtype=float),
        label="Offshore wind",
    )
    ax1.set_title(f"Niedersachsen VRE (MWh/day) — Month: {yyyy_mm}")
    ax1.set_ylabel("MWh/day")
    ax1.grid(True, axis="y")
    ax1.legend(loc="upper left")

    ax2 = fig.add_subplot(2, 1, 2)
    ax2.stackplot(
        share.index,
        (share["solar_mwh"] * 100).to_numpy(dtype=float),
        (share["onshore_mwh"] * 100).to_numpy(dtype=float),
        (share["offshore_mwh"] * 100).to_numpy(dtype=float),
        labels=["Solar", "Onshore wind", "Offshore wind"],
    )
    ax2.set_title("Share of VRE (%) by day")
    ax2.set_ylabel("% of VRE")
    ax2.set_ylim(0, 100)
    ax2.grid(True)
    ax2.legend(loc="upper left")

    fig.tight_layout()
    _maybe_save(fig, save_dir, f"vre_month_{yyyy_mm}.png")


def _plot_year_months(monthly: pd.DataFrame, save_dir: Path | None) -> None:
    m = monthly.sort_index()
    share = _shares(m, ["solar_mwh", "onshore_mwh", "offshore_mwh"], "total_mwh")

    fig = plt.figure(figsize=(12, 7))
    ax1 = fig.add_subplot(2, 1, 1)
    ax1.bar(m.index, m["solar_mwh"].to_numpy(dtype=float), label="Solar")
    ax1.bar(
        m.index,
        m["onshore_mwh"].to_numpy(dtype=float),
        bottom=m["solar_mwh"].to_numpy(dtype=float),
        label="Onshore wind",
    )
    ax1.bar(
        m.index,
        m["offshore_mwh"].to_numpy(dtype=float),
        bottom=(m["solar_mwh"] + m["onshore_mwh"]).to_numpy(dtype=float),
        label="Offshore wind",
    )
    ax1.set_title("Niedersachsen VRE (MWh/month) — Full year monthly totals")
    ax1.set_ylabel("MWh/month")
    ax1.grid(True, axis="y")
    ax1.legend(loc="upper left")

    ax2 = fig.add_subplot(2, 1, 2)
    ax2.stackplot(
        share.index,
        (share["solar_mwh"] * 100).to_numpy(dtype=float),
        (share["onshore_mwh"] * 100).to_numpy(dtype=float),
        (share["offshore_mwh"] * 100).to_numpy(dtype=float),
        labels=["Solar", "Onshore wind", "Offshore wind"],
    )
    ax2.set_title("Share of VRE (%) by month")
    ax2.set_ylabel("% of VRE")
    ax2.set_ylim(0, 100)
    ax2.grid(True)
    ax2.legend(loc="upper left")

    fig.tight_layout()
    _maybe_save(fig, save_dir, "vre_year_monthly.png")


def main() -> None:
    save_dir = Path(CONFIG["SAVE_DIR"]) if CONFIG.get("SAVE_DIR") else None

    hourly = _combine_hourly(Path(CONFIG["PV_YEAR_CSV"]), Path(CONFIG["WIND_YEAR_CSV"]))
    full_date, yyyy_mm = _infer_full_date_and_month(hourly.index, CONFIG["DATE"])

    pv_daily = Path(CONFIG["PV_DAILY_CSV"])
    wind_daily = Path(CONFIG["WIND_DAILY_CSV"])
    if pv_daily.exists() and wind_daily.exists():
        daily = _combine_daily(pv_daily, wind_daily)
    else:
        daily = _daily_from_hourly(hourly)

    pv_monthly = Path(CONFIG["PV_MONTHLY_CSV"])
    wind_monthly = Path(CONFIG["WIND_MONTHLY_CSV"])
    if pv_monthly.exists() and wind_monthly.exists():
        monthly = _combine_monthly(pv_monthly, wind_monthly)
    else:
        monthly = _monthly_from_daily(daily)

    _plot_day(hourly, full_date, save_dir)
    _plot_month(daily, yyyy_mm, save_dir)
    _plot_year_months(monthly, save_dir)

    if CONFIG.get("ALWAYS_SHOW", True):
        if _FORCE_BACKEND == "Agg":
            print("No GUI backend available (Qt/Tk missing). Set SAVE_DIR to save PNGs.")
        else:
            plt.show(block=True)


if __name__ == "__main__":
    main()