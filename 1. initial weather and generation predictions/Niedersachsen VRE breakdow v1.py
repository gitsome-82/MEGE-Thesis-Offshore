# scripts/niedersachsen_vre_breakdown.py
"""
Combine PV + wind outputs and plot Niedersachsen VRE breakdown.

Notes:
- "day" view uses the YEAR files (hourly).
- "month" view prefers DAILY files if provided; otherwise resamples the YEAR files.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


@dataclass(frozen=True)
class Inputs:
    pv_year: Path
    wind_year: Path
    pv_daily: Path | None
    wind_daily: Path | None
    pv_monthly: Path | None
    wind_monthly: Path | None
    view: str  # day | month
    date: str | None
    month: str | None
    out: Path | None


def _read_csv_with_dt_index(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)

    # Your exports use "Unnamed: 0" as the datetime column
    dt_col = "Unnamed: 0" if "Unnamed: 0" in df.columns else df.columns[0]
    df[dt_col] = pd.to_datetime(df[dt_col], errors="coerce")
    df = df.dropna(subset=[dt_col]).set_index(dt_col).sort_index()
    return df


def _pv_hourly_mw(pv_year: pd.DataFrame) -> pd.Series:
    if "gen_mw" in pv_year.columns:
        return pv_year["gen_mw"].rename("solar_mw")
    if "energy_mwh" in pv_year.columns:
        return pv_year["energy_mwh"].rename("solar_mw")
    raise ValueError("PV year CSV missing gen_mw or energy_mwh")


def _wind_hourly_mw(wind_year: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    needed = ["gen_onshore_mw", "gen_offshore_mw"]
    missing = [c for c in needed if c not in wind_year.columns]
    if missing:
        raise ValueError(f"Wind year CSV missing columns: {missing}")
    return (
        wind_year["gen_onshore_mw"].rename("onshore_mw"),
        wind_year["gen_offshore_mw"].rename("offshore_mw"),
    )


def _combine_hourly(pv_year_path: Path, wind_year_path: Path) -> pd.DataFrame:
    pv_year = _read_csv_with_dt_index(pv_year_path)
    wind_year = _read_csv_with_dt_index(wind_year_path)

    solar = _pv_hourly_mw(pv_year)
    onshore, offshore = _wind_hourly_mw(wind_year)

    df = pd.concat([solar, onshore, offshore], axis=1).fillna(0.0)
    df["total_mw"] = df[["solar_mw", "onshore_mw", "offshore_mw"]].sum(axis=1)
    return df


def _combine_daily(
    pv_daily_path: Path,
    wind_daily_path: Path,
) -> pd.DataFrame:
    pv_d = _read_csv_with_dt_index(pv_daily_path)
    w_d = _read_csv_with_dt_index(wind_daily_path)

    if "energy_mwh" not in pv_d.columns:
        raise ValueError("PV daily CSV missing energy_mwh")
    for c in ["energy_onshore_mwh", "energy_offshore_mwh"]:
        if c not in w_d.columns:
            raise ValueError(f"Wind daily CSV missing {c}")

    df = pd.DataFrame(index=pv_d.index.union(w_d.index).sort_values())
    df["solar_mwh"] = pv_d["energy_mwh"]
    df["onshore_mwh"] = w_d["energy_onshore_mwh"]
    df["offshore_mwh"] = w_d["energy_offshore_mwh"]
    df = df.fillna(0.0)
    df["total_mwh"] = df[["solar_mwh", "onshore_mwh", "offshore_mwh"]].sum(axis=1)
    return df


def _shares(numerators: pd.DataFrame, total_col: str) -> pd.DataFrame:
    denom = numerators[total_col].replace(0.0, pd.NA)
    out = numerators.drop(columns=[total_col]).div(denom, axis=0).fillna(0.0)
    return out


def _plot_day(hourly: pd.DataFrame, day: str, out: Path | None) -> None:
    day_df = hourly.loc[day].copy()
    share = _shares(
        day_df[["solar_mw", "onshore_mw", "offshore_mw", "total_mw"]],
        "total_mw",
    )

    fig = plt.figure(figsize=(12, 7))

    ax1 = fig.add_subplot(2, 1, 1)
    ax1.stackplot(
        day_df.index,
        day_df["solar_mw"],
        day_df["onshore_mw"],
        day_df["offshore_mw"],
        labels=["Solar", "Onshore wind", "Offshore wind"],
    )
    ax1.set_title(f"Niedersachsen VRE generation (MW) — {day}")
    ax1.set_ylabel("MW")
    ax1.grid(True)
    ax1.legend(loc="upper left")

    ax2 = fig.add_subplot(2, 1, 2)
    ax2.stackplot(
        share.index,
        share["solar_mw"] * 100,
        share["onshore_mw"] * 100,
        share["offshore_mw"] * 100,
        labels=["Solar", "Onshore wind", "Offshore wind"],
    )
    ax2.set_title(f"VRE share (%) by hour — {day}")
    ax2.set_ylabel("% of VRE")
    ax2.set_ylim(0, 100)
    ax2.grid(True)
    ax2.legend(loc="upper left")

    fig.tight_layout()
    if out:
        fig.savefig(out, dpi=200, bbox_inches="tight")
    else:
        plt.show()


def _plot_month_from_daily(daily: pd.DataFrame, month: str, out: Path | None) -> None:
    m = daily.loc[month].copy()
    share = _shares(
        m[["solar_mwh", "onshore_mwh", "offshore_mwh", "total_mwh"]],
        "total_mwh",
    )

    fig = plt.figure(figsize=(12, 7))

    ax1 = fig.add_subplot(2, 1, 1)
    ax1.bar(m.index, m["solar_mwh"], label="Solar")
    ax1.bar(m.index, m["onshore_mwh"], bottom=m["solar_mwh"], label="Onshore wind")
    ax1.bar(
        m.index,
        m["offshore_mwh"],
        bottom=m["solar_mwh"] + m["onshore_mwh"],
        label="Offshore wind",
    )
    ax1.set_title(f"Niedersachsen daily VRE energy (MWh/day) — {month}")
    ax1.set_ylabel("MWh/day")
    ax1.grid(True, axis="y")
    ax1.legend(loc="upper left")

    ax2 = fig.add_subplot(2, 1, 2)
    ax2.stackplot(
        share.index,
        share["solar_mwh"] * 100,
        share["onshore_mwh"] * 100,
        share["offshore_mwh"] * 100,
        labels=["Solar", "Onshore wind", "Offshore wind"],
    )
    ax2.set_title(f"VRE share (%) by day — {month}")
    ax2.set_ylabel("% of VRE")
    ax2.set_ylim(0, 100)
    ax2.grid(True)
    ax2.legend(loc="upper left")

    fig.tight_layout()
    if out:
        fig.savefig(out, dpi=200, bbox_inches="tight")
    else:
        plt.show()


def _month_from_hourly(hourly: pd.DataFrame) -> pd.DataFrame:
    # Convert hourly MW to daily MWh by summing hours
    d = hourly[["solar_mw", "onshore_mw", "offshore_mw"]].resample("D").sum()
    d = d.rename(columns={"solar_mw": "solar_mwh", "onshore_mw": "onshore_mwh", "offshore_mw": "offshore_mwh"})
    d["total_mwh"] = d.sum(axis=1)
    return d


def _parse_args() -> Inputs:
    p = argparse.ArgumentParser()
    p.add_argument("--pv-year", required=True, type=Path)
    p.add_argument("--wind-year", required=True, type=Path)

    p.add_argument("--pv-daily", type=Path)
    p.add_argument("--wind-daily", type=Path)
    p.add_argument("--pv-monthly", type=Path)
    p.add_argument("--wind-monthly", type=Path)

    p.add_argument("--view", choices=["day", "month"], required=True)
    p.add_argument("--date", help="YYYY-MM-DD (required for --view day)")
    p.add_argument("--month", help="YYYY-MM (required for --view month)")
    p.add_argument("--out", type=Path, help="Save plot to file instead of showing.")

    args = p.parse_args()

    if args.view == "day" and not args.date:
        raise SystemExit("--date is required when --view day")
    if args.view == "month" and not args.month:
        raise SystemExit("--month is required when --view month")

    return Inputs(
        pv_year=args.pv_year,
        wind_year=args.wind_year,
        pv_daily=args.pv_daily,
        wind_daily=args.wind_daily,
        pv_monthly=args.pv_monthly,
        wind_monthly=args.wind_monthly,
        view=args.view,
        date=args.date,
        month=args.month,
        out=args.out,
    )


def main() -> None:
    cfg = _parse_args()

    hourly = _combine_hourly(cfg.pv_year, cfg.wind_year)

    if cfg.view == "day":
        _plot_day(hourly, cfg.date, cfg.out)
        return

    # month view
    if cfg.pv_daily and cfg.wind_daily:
        daily = _combine_daily(cfg.pv_daily, cfg.wind_daily)
    else:
        daily = _month_from_hourly(hourly)

    _plot_month_from_daily(daily, cfg.month, cfg.out)


if __name__ == "__main__":
    main()