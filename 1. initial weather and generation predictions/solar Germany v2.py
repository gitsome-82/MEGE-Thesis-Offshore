import pandas as pd
import zipfile
import os
import matplotlib.pyplot as plt

# ---------------------------------------------------
# USER SETTINGS
# ---------------------------------------------------
base = r"C:\Users\IanPe\OneDrive - Universidade de Lisboa\Documents\IST\MEGE\~Thesis Sem 4 26\DWD data\Hourly Solar"

paths = {
    "braunlage":    os.path.join(base, "stundenwerte_ST_00656_row.zip"),
    "braunschweig": os.path.join(base, "stundenwerte_ST_00662_row.zip"),
    "norderney":    os.path.join(base, "stundenwerte_ST_03631_row.zip"),
}

installed_capacity_mw = 9000     # Niedersachsen installed PV capacity
performance_ratio = 0.85         # simple first-pass PR assumption
typical_year_label = 2021        # use a non-leap year so final series has 8760 hours

# ---------------------------------------------------
# 1. FUNCTION TO LOAD ONE STATION FROM A ZIP FILE
# ---------------------------------------------------
def load_station_from_zip(zip_path):
    with zipfile.ZipFile(zip_path, 'r') as z:
        txt_files = [f for f in z.namelist() if f.startswith("produkt_st_stunde")]
        if len(txt_files) == 0:
            raise ValueError(f"No produkt_st_stunde file found in {zip_path}")
        txt_file = txt_files[0]

        with z.open(txt_file) as f:
            df = pd.read_csv(
                f,
                sep=';',
                na_values=['-999', -999],
                dtype=str
            )

    # Clean column names
    df.columns = df.columns.str.strip()

    # Convert needed columns to numeric
    df['FG_LBERG'] = pd.to_numeric(df['FG_LBERG'], errors='coerce')
    df['QN_592'] = pd.to_numeric(df['QN_592'], errors='coerce')

    # Parse datetime
    df['MESS_DATUM'] = pd.to_datetime(
        df['MESS_DATUM'].str.strip(),
        format='%Y%m%d%H:%M',
        errors='coerce'
    )

    # Drop rows where timestamp failed
    df = df.dropna(subset=['MESS_DATUM'])

    # Keep only good quality rows
    df = df[df['QN_592'].isin([1, 3])]

    # Keep only datetime + radiation, then drop missing values
    df = df[['MESS_DATUM', 'FG_LBERG']].dropna()

    # Set datetime index
    df = df.set_index('MESS_DATUM').sort_index()

    df = df[df.index.year >= 1970]
    return df


# ---------------------------------------------------
# 2. LOAD ALL THREE STATIONS
# ---------------------------------------------------
braunlage = load_station_from_zip(paths["braunlage"]).rename(columns={'FG_LBERG': 'braunlage'})
braunschweig = load_station_from_zip(paths["braunschweig"]).rename(columns={'FG_LBERG': 'braunschweig'})
norderney = load_station_from_zip(paths["norderney"]).rename(columns={'FG_LBERG': 'norderney'})


# ---------------------------------------------------
# 3. MERGE STATIONS BY DATETIME
#    This aligns data by timestamp, not by row number
# ---------------------------------------------------
df = braunlage.join(braunschweig, how='outer').join(norderney, how='outer')
df = df.dropna(how='all')

# Add calendar fields for climatology grouping
df['month'] = df.index.month
df['day'] = df.index.day
df['hour'] = df.index.hour


# ---------------------------------------------------
# 4. COMPUTE LONG-TERM HOURLY CLIMATOLOGY
#    Group by (month, day, hour) to avoid leap-year DOY issues
# ---------------------------------------------------
clim = df.groupby(['month', 'day', 'hour'])[['braunlage', 'braunschweig', 'norderney']].mean()

# Average across stations (equal weighting)
clim['ghi_avg_jcm2'] = clim[['braunlage', 'braunschweig', 'norderney']].mean(axis=1)


# ---------------------------------------------------
# 5. BUILD A NON-LEAP TYPICAL YEAR (8760 HOURS)
# ---------------------------------------------------
typical_index = pd.date_range(
    f"{typical_year_label}-01-01 00:00",
    f"{typical_year_label}-12-31 23:00",
    freq="h"
)

typical_year = pd.DataFrame(index=typical_index)
typical_year['month'] = typical_year.index.month
typical_year['day'] = typical_year.index.day
typical_year['hour'] = typical_year.index.hour

# Merge climatology values onto the typical-year calendar
typical_year = typical_year.merge(
    clim[['ghi_avg_jcm2']],
    left_on=['month', 'day', 'hour'],
    right_index=True,
    how='left'
)

# Put the datetime index back after merge
typical_year.index = typical_index

# Keep only relevant columns for now
typical_year = typical_year[['ghi_avg_jcm2']]
typical_year['ghi_avg_jcm2'] = typical_year['ghi_avg_jcm2'].clip(lower=0)

# ---------------------------------------------------
# 6. CONVERT GHI UNITS
#    Source unit: J/cm^2 per hour
#    Convert to W/m^2:
#       1 cm^2 = 1e-4 m^2  -> multiply by 10000
#       1 W = 1 J/s        -> divide by 3600 for hourly data
#    So:
#       W/m^2 = J/cm^2 * 10000 / 3600
# ---------------------------------------------------
typical_year['ghi_wm2'] = typical_year['ghi_avg_jcm2'] * 10000 / 3600


# ---------------------------------------------------
# 7. CONVERT GHI TO TYPICAL PV GENERATION
#    Simple first-pass approximation:
#       generation = installed_capacity * (GHI / 1000) * PR
#
#    Why divide by 1000?
#    Because installed PV capacity is rated at 1000 W/m^2 irradiance (STC reference).
#    NOTE: that we are ignoring temperature effects (roughly incorporated into perf. ratio)
# ---------------------------------------------------
typical_year['gen_mw'] = (
    installed_capacity_mw *
    (typical_year['ghi_wm2'] / 1000.0) *
    performance_ratio
)

# Prevent negative values and cap output at installed capacity
typical_year['gen_mw'] = typical_year['gen_mw'].clip(lower=0, upper=installed_capacity_mw)

# Since data are hourly, MW sustained over 1 hour = MWh in that hour
typical_year['energy_mwh'] = typical_year['gen_mw']


# ---------------------------------------------------
# 8. DAILY AND MONTHLY ENERGY TOTALS
# ---------------------------------------------------
daily_energy = typical_year['energy_mwh'].resample('D').sum()
monthly_energy = typical_year['energy_mwh'].resample('ME').sum()


# ---------------------------------------------------
# 9. QUICK CHECKS
# ---------------------------------------------------
print("\n--- FIRST 5 ROWS ---")
print(typical_year.head())

print("\n--- LAST 5 ROWS ---")
print(typical_year.tail())

print("\n--- EXAMPLE DAY: JUNE 15 ---")
print(typical_year.loc[f"{typical_year_label}-06-15"])

print("\n--- GENERATION SUMMARY ---")
print(typical_year['gen_mw'].describe())

print("\n--- ANNUAL ENERGY ---")
print(f"Annual energy = {typical_year['energy_mwh'].sum() / 1000:.2f} GWh")


# ---------------------------------------------------
# 10. LOOK UP ANY DAY OR MONTH
# ---------------------------------------------------
# Example lookup: one hour
print("\n--- EXAMPLE HOUR ---")
print(typical_year.loc[f"{typical_year_label}-06-15 12:00"])

# Example lookup: one month
print("\n--- EXAMPLE MONTH: JUNE ---")
print(typical_year.loc[f"{typical_year_label}-06"].head())


# ---------------------------------------------------
# 11. PLOT ONE DAY
# ---------------------------------------------------
day_to_plot = f"{typical_year_label}-06-15"
day_data = typical_year.loc[day_to_plot]

plt.figure(figsize=(10, 4))
plt.plot(day_data.index, day_data['gen_mw'])
plt.title(f"Typical PV generation on {day_to_plot}")
plt.xlabel("Time")
plt.ylabel("Generation (MW)")
plt.grid(True)
plt.tight_layout()
plt.show()


# ---------------------------------------------------
# 12. PLOT ONE MONTH
# ---------------------------------------------------
month_to_plot = f"{typical_year_label}-06"
month_data = typical_year.loc[month_to_plot]

plt.figure(figsize=(12, 4))
plt.plot(month_data.index, month_data['gen_mw'])
plt.title(f"Typical PV generation during {month_to_plot}")
plt.xlabel("Date")
plt.ylabel("Generation (MW)")
plt.grid(True)
plt.tight_layout()
plt.show()


# ---------------------------------------------------
# 13. PLOT MONTHLY ENERGY TOTALS
# ---------------------------------------------------
plt.figure(figsize=(10, 4))
plt.bar(monthly_energy.index.strftime('%b'), monthly_energy.values)
plt.title("Typical monthly PV energy")
plt.xlabel("Month")
plt.ylabel("Energy (MWh)")
plt.grid(True, axis='y')
plt.tight_layout()
plt.show()


# ---------------------------------------------------
# 14. SAVE RESULTS TO CSV
# ---------------------------------------------------
output_folder = base

typical_year.to_csv(os.path.join(output_folder, "typical_year_pv_niedersachsen.csv"))
daily_energy.to_csv(os.path.join(output_folder, "typical_daily_energy_niedersachsen.csv"), header=['energy_mwh'])
monthly_energy.to_csv(os.path.join(output_folder, "typical_monthly_energy_niedersachsen.csv"), header=['energy_mwh'])

print("\nCSV files saved successfully.")


# ---------------------------------------------------
# 15. SANITY CHECK: ANNUAL ENERGY + CAPACITY FACTOR
# ---------------------------------------------------

annual_energy_mwh = typical_year['energy_mwh'].sum()

full_load_hours = annual_energy_mwh / installed_capacity_mw

capacity_factor = full_load_hours / 8760

print("\n--- SANITY CHECK ---")
print(f"Installed capacity: {installed_capacity_mw} MW")
print(f"Annual energy: {annual_energy_mwh/1e6:.2f} TWh")
print(f"Full-load hours: {full_load_hours:.0f} h/year")
print(f"Capacity factor: {capacity_factor*100:.1f} %")
print(f"Peak generation: {typical_year['gen_mw'].max():.0f} MW")


print("\nMissing values in typical year:")
print(typical_year.isna().sum())

print("\nJanuary sample:")
print(typical_year.loc["2021-01-01":"2021-01-07"].head(50))

print("\nMonthly non-NaN counts:")
print(typical_year['gen_mw'].resample('ME').count())

print(df.index.min())
print(df.index.max())
print(df.loc[df.index.month == 1].head())
print(df.loc[df.index.month == 1].tail())