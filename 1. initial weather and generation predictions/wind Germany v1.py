import pandas as pd
import zipfile
import os
import glob
import numpy as np
import matplotlib.pyplot as plt

# ---------------------------------------------------
# USER SETTINGS
# ---------------------------------------------------
base = r"C:\Users\IanPe\OneDrive - Universidade de Lisboa\Documents\IST\MEGE\~Thesis Sem 4 26\DWD data\Hourly Wind"

sources = {
    "braunlage": {
        "station_id": "00656",
        "paths": [
            os.path.join(base, "stundenwerte_FF_00656_19370101_20241231_hist.zip"),
            os.path.join(base, "stundenwerte_FF_00656_19370101_20241231_hist"),
            os.path.join(base, "stundenwerte_FF_00656_akt.zip"),
            os.path.join(base, "stundenwerte_FF_00656_akt"),
        ],
    },
    "braunschweig": {
        "station_id": "00662",
        "paths": [
            os.path.join(base, "stundenwerte_FF_00662_19660101_20241231_hist.zip"),
            os.path.join(base, "stundenwerte_FF_00662_19660101_20241231_hist"),
            os.path.join(base, "stundenwerte_FF_00662_akt.zip"),
            os.path.join(base, "stundenwerte_FF_00662_akt"),
        ],
    },
    "norderney": {
        "station_id": "03631",
        "paths": [
            os.path.join(base, "stundenwerte_FF_03631_akt.zip"),
            os.path.join(base, "stundenwerte_FF_03631_akt"),
        ],
    },
}

onshore_capacity_mw = 13000
offshore_capacity_mw = 7000
typical_year_label = 2021

# Target hub height
hub_height_m = 100.0

# Roughness lengths for hub height correction
z0_onshore = 0.05
z0_offshore = 0.0002

# Power curve assumptions
cut_in_onshore = 3.0
rated_onshore = 12.0
cut_out_onshore = 25.0

cut_in_offshore = 3.0
rated_offshore = 12.0
cut_out_offshore = 25.0


# ---------------------------------------------------
# 1. HELPER FUNCTIONS
# ---------------------------------------------------
def power_fraction(v, cut_in, rated, cut_out):
  
    if pd.isna(v):
        return np.nan
    if v < cut_in:
        return 0.0
    if v < rated:
        return ((v - cut_in) / (rated - cut_in)) ** 3
    if v <= cut_out:
        return 1.0
    return 0.0


def log_law_adjust(v_meas, z_meas, z_target, z0):
    """
    Log-law profile:
        V(z_target) = V(z_meas) * ln(z_target / z0) / ln(z_meas / z0)
    """
    if pd.isna(v_meas) or pd.isna(z_meas):
        return np.nan
    if z0 <= 0 or z_meas <= z0 or z_target <= z0:
        return np.nan

    return v_meas * np.log(z_target / z0) / np.log(z_meas / z0)


def find_matching_file_in_folder(folder_path, prefix):
    patterns = [
        os.path.join(folder_path, f"{prefix}*"),
        os.path.join(folder_path, "**", f"{prefix}*"),
    ]

    matches = []
    for pattern in patterns:
        matches.extend(glob.glob(pattern, recursive=True))

    if not matches:
        return None

    return matches[0]


def read_data_table(file_obj_or_path):
    df = pd.read_csv(
        file_obj_or_path,
        sep=';',
        na_values=['-999', -999],
        dtype=str
    )

    df.columns = df.columns.str.strip()

    required = ['MESS_DATUM', 'F']
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column '{col}'. Columns found: {list(df.columns)}")

    df['F'] = pd.to_numeric(df['F'], errors='coerce')

    if 'QN_3' in df.columns:
        df['QN_3'] = pd.to_numeric(df['QN_3'], errors='coerce')

    if 'D' in df.columns:
        df['D'] = pd.to_numeric(df['D'], errors='coerce')

    df['MESS_DATUM'] = pd.to_datetime(
        df['MESS_DATUM'].astype(str).str.strip(),
        format='%Y%m%d%H',
        errors='coerce'
    )

    df = df.dropna(subset=['MESS_DATUM'])
    df = df.dropna(subset=['F'])

    keep_cols = ['MESS_DATUM', 'F']
    if 'QN_3' in df.columns:
        keep_cols.append('QN_3')
    if 'D' in df.columns:
        keep_cols.append('D')

    return df[keep_cols]


def read_metadata_table(file_obj_or_path):
    meta = pd.read_csv(
    file_obj_or_path,
    sep=';',
    dtype=str,
    engine='python',
    encoding='latin-1'
)

    meta.columns = meta.columns.str.strip()

    height_col = None
    start_col = None
    end_col = None

    for col in meta.columns:
        c = col.lower()
        if 'geberhoehe' in c and 'grund' in c:
            height_col = col
        elif 'von datum' in c:
            start_col = col
        elif 'bis datum' in c:
            end_col = col

    if height_col is None or start_col is None or end_col is None:
        raise ValueError(f"Could not identify metadata columns. Columns found: {list(meta.columns)}")

    meta[height_col] = pd.to_numeric(meta[height_col], errors='coerce')

    meta[start_col] = pd.to_datetime(
        meta[start_col].astype(str).str.strip(),
        format='%Y%m%d',
        errors='coerce'
    )

    meta[end_col] = pd.to_datetime(
        meta[end_col].astype(str).str.strip(),
        format='%Y%m%d',
        errors='coerce'
    )

    meta = meta.rename(columns={
        height_col: 'sensor_height_m',
        start_col: 'start_date',
        end_col: 'end_date'
    })

    meta = meta[['sensor_height_m', 'start_date', 'end_date']].dropna()
    meta = meta.sort_values('start_date')

    return meta


def load_zip_or_folder_data_and_metadata(path, station_id):
    if not os.path.exists(path):
        return None, None

    data_prefix = "produkt_ff_stunde"
    meta_prefix = f"Metadaten_Geraete_Windgeschwindigkeit_{station_id}"

    if os.path.isdir(path):
        data_file = find_matching_file_in_folder(path, data_prefix)
        meta_file = find_matching_file_in_folder(path, meta_prefix)

        if data_file is None:
            raise ValueError(f"No wind data file found in folder: {path}")
        if meta_file is None:
            raise ValueError(f"No wind metadata file found in folder: {path}")

        df = read_data_table(data_file)
        meta = read_metadata_table(meta_file)

    elif path.lower().endswith('.zip'):
        with zipfile.ZipFile(path, 'r') as z:
            names = z.namelist()

            data_files = [n for n in names if "produkt_ff_stunde" in n.lower()]
            meta_files = [n for n in names if f"metadaten_geraete_windgeschwindigkeit_{station_id}".lower() in n.lower()]

            if len(data_files) == 0:
                raise ValueError(f"No wind data file found in zip: {path}")
            if len(meta_files) == 0:
                raise ValueError(f"No wind metadata file found in zip: {path}")

            with z.open(data_files[0]) as f:
                df = read_data_table(f)

            with z.open(meta_files[0]) as f:
                meta = read_metadata_table(f)

    else:
        return None, None

    return df, meta


def assign_sensor_height(df, meta):
    df = df.copy()
    df['sensor_height_m'] = np.nan

    for _, row in meta.iterrows():
        start = row['start_date']
        end = row['end_date']
        h = row['sensor_height_m']

        mask = (df['MESS_DATUM'] >= start) & (df['MESS_DATUM'] < (end + pd.Timedelta(days=1)))
        df.loc[mask, 'sensor_height_m'] = h

    return df


def load_station_from_many_sources(path_list, station_id, z0, output_col_name):
    frames = []

    for path in path_list:
        df, meta = load_zip_or_folder_data_and_metadata(path, station_id)
        if df is None:
            continue

        df = assign_sensor_height(df, meta)

        df['wind_hub_mps'] = df.apply(
            lambda row: log_law_adjust(
                v_meas=row['F'],
                z_meas=row['sensor_height_m'],
                z_target=hub_height_m,
                z0=z0
            ),
            axis=1
        )

        df = df[['MESS_DATUM', 'wind_hub_mps']].dropna(subset=['wind_hub_mps'])
        frames.append(df)

    if not frames:
        raise ValueError(f"No valid sources found for station {station_id}")

    df_all = pd.concat(frames, ignore_index=True)
    df_all = df_all.sort_values('MESS_DATUM')
    df_all = df_all.drop_duplicates(subset=['MESS_DATUM'], keep='last')
    df_all = df_all.set_index('MESS_DATUM').sort_index()
    df_all = df_all.rename(columns={'wind_hub_mps': output_col_name})

    return df_all


# ---------------------------------------------------
# 2. LOAD STATIONS
# ---------------------------------------------------
print("\n--- CHECKING PATHS ---")
for station_name, info in sources.items():
    print(f"\n{station_name}:")
    for p in info["paths"]:
        print(os.path.exists(p), " | ", p)

braunlage = load_station_from_many_sources(
    sources["braunlage"]["paths"],
    station_id=sources["braunlage"]["station_id"],
    z0=z0_onshore,
    output_col_name='braunlage'
)

braunschweig = load_station_from_many_sources(
    sources["braunschweig"]["paths"],
    station_id=sources["braunschweig"]["station_id"],
    z0=z0_onshore,
    output_col_name='braunschweig'
)

norderney = load_station_from_many_sources(
    sources["norderney"]["paths"],
    station_id=sources["norderney"]["station_id"],
    z0=z0_offshore,
    output_col_name='norderney'
)


# ---------------------------------------------------
# 3. MERGE
# ---------------------------------------------------
df = braunlage.join(braunschweig, how='outer').join(norderney, how='outer')
df = df.dropna(how='all')

df['month'] = df.index.month
df['day'] = df.index.day
df['hour'] = df.index.hour


# ---------------------------------------------------
# 4. CLIMATOLOGY
# ---------------------------------------------------
clim = df.groupby(['month', 'day', 'hour'])[['braunlage', 'braunschweig', 'norderney']].mean()


# ---------------------------------------------------
# 5. BUILD TYPICAL YEAR
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

typical_year = typical_year.merge(
    clim,
    left_on=['month', 'day', 'hour'],
    right_index=True,
    how='left'
)

typical_year.index = typical_index
typical_year = typical_year[['braunlage', 'braunschweig', 'norderney']]


# ---------------------------------------------------
# 6. ONSHORE / OFFSHORE SERIES
# ---------------------------------------------------
typical_year['wind_onshore_mps'] = typical_year[['braunlage', 'braunschweig']].mean(axis=1)
typical_year['wind_offshore_mps'] = typical_year['norderney']


# ---------------------------------------------------
# 7. POWER CURVE
# ---------------------------------------------------
typical_year['pf_onshore'] = typical_year['wind_onshore_mps'].apply(
    lambda v: power_fraction(v, cut_in_onshore, rated_onshore, cut_out_onshore)
)

typical_year['pf_offshore'] = typical_year['wind_offshore_mps'].apply(
    lambda v: power_fraction(v, cut_in_offshore, rated_offshore, cut_out_offshore)
)


# ---------------------------------------------------
# 8. GENERATION
# ---------------------------------------------------
typical_year['gen_onshore_mw'] = typical_year['pf_onshore'] * onshore_capacity_mw
typical_year['gen_offshore_mw'] = typical_year['pf_offshore'] * offshore_capacity_mw
typical_year['gen_total_mw'] = typical_year['gen_onshore_mw'] + typical_year['gen_offshore_mw']

typical_year['energy_onshore_mwh'] = typical_year['gen_onshore_mw']
typical_year['energy_offshore_mwh'] = typical_year['gen_offshore_mw']
typical_year['energy_total_mwh'] = typical_year['gen_total_mw']


# ---------------------------------------------------
# 9. DAILY AND MONTHLY ENERGY
# ---------------------------------------------------
daily_energy = typical_year[['energy_onshore_mwh', 'energy_offshore_mwh', 'energy_total_mwh']].resample('D').sum()
monthly_energy = typical_year[['energy_onshore_mwh', 'energy_offshore_mwh', 'energy_total_mwh']].resample('ME').sum()


# ---------------------------------------------------
# 10. CHECKS
# ---------------------------------------------------
annual_energy_mwh = typical_year['energy_total_mwh'].sum()
full_load_hours_total = annual_energy_mwh / (onshore_capacity_mw + offshore_capacity_mw)
capacity_factor_total = full_load_hours_total / 8760

print("\n--- FIRST 5 ROWS ---")
print(typical_year.head())

print("\n--- LAST 5 ROWS ---")
print(typical_year.tail())

print("\n--- EXAMPLE DAY: JUNE 15 ---")
print(typical_year.loc[f"{typical_year_label}-06-15"])

print("\n--- WIND GENERATION SUMMARY ---")
print(typical_year['gen_total_mw'].describe())

print("\n--- SANITY CHECK ---")
print(f"Hub height used: {hub_height_m} m")
print(f"z0 onshore: {z0_onshore} m")
print(f"z0 offshore: {z0_offshore} m")
print(f"Onshore capacity: {onshore_capacity_mw} MW")
print(f"Offshore capacity: {offshore_capacity_mw} MW")
print(f"Total capacity: {onshore_capacity_mw + offshore_capacity_mw} MW")
print(f"Annual energy: {annual_energy_mwh/1e6:.2f} TWh")
print(f"Full-load hours: {full_load_hours_total:.0f} h/year")
print(f"Capacity factor: {capacity_factor_total*100:.1f} %")
print(f"Peak total generation: {typical_year['gen_total_mw'].max():.0f} MW")
print(f"Peak onshore generation: {typical_year['gen_onshore_mw'].max():.0f} MW")
print(f"Peak offshore generation: {typical_year['gen_offshore_mw'].max():.0f} MW")

print("\nMissing values in typical year:")
print(typical_year.isna().sum())


# ---------------------------------------------------
# 11. PLOTS
# ---------------------------------------------------
day_to_plot = f"{typical_year_label}-06-15"
day_data = typical_year.loc[day_to_plot]

plt.figure(figsize=(10, 4))
plt.plot(day_data.index, day_data['gen_onshore_mw'], label='Onshore')
plt.plot(day_data.index, day_data['gen_offshore_mw'], label='Offshore')
plt.plot(day_data.index, day_data['gen_total_mw'], label='Total')
plt.title(f"Typical wind generation on {day_to_plot}")
plt.xlabel("Time")
plt.ylabel("Generation (MW)")
plt.grid(True)
plt.legend()
plt.tight_layout()
plt.show()

month_to_plot = f"{typical_year_label}-06"
month_data = typical_year.loc[month_to_plot]

plt.figure(figsize=(12, 4))
plt.plot(month_data.index, month_data['gen_onshore_mw'], label='Onshore')
plt.plot(month_data.index, month_data['gen_offshore_mw'], label='Offshore')
plt.plot(month_data.index, month_data['gen_total_mw'], label='Total')
plt.title(f"Typical wind generation during {month_to_plot}")
plt.xlabel("Date")
plt.ylabel("Generation (MW)")
plt.grid(True)
plt.legend()
plt.tight_layout()
plt.show()

plt.figure(figsize=(10, 4))
plt.bar(monthly_energy.index.strftime('%b'), monthly_energy['energy_onshore_mwh'], label='Onshore')
plt.bar(
    monthly_energy.index.strftime('%b'),
    monthly_energy['energy_offshore_mwh'],
    bottom=monthly_energy['energy_onshore_mwh'],
    label='Offshore'
)
plt.title("Typical monthly wind energy")
plt.xlabel("Month")
plt.ylabel("Energy (MWh)")
plt.grid(True, axis='y')
plt.legend()
plt.tight_layout()
plt.show()


# ---------------------------------------------------
# 12. SAVE
# ---------------------------------------------------
output_folder = base

typical_year.to_csv(os.path.join(output_folder, "typical_year_wind_niedersachsen.csv"))
daily_energy.to_csv(os.path.join(output_folder, "typical_daily_energy_wind_niedersachsen.csv"))
monthly_energy.to_csv(os.path.join(output_folder, "typical_monthly_energy_wind_niedersachsen.csv"))

print("\nCSV files saved successfully.")