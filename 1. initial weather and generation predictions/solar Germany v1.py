import pandas as pd
import zipfile
import os

# ---------------------------------------------------
# 1. Function to load one station from a ZIP file
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

    # Convert numeric radiation + quality
    df['FG_LBERG'] = pd.to_numeric(df['FG_LBERG'], errors='coerce')
    df['QN_592'] = pd.to_numeric(df['QN_592'], errors='coerce')

    # Parse timestamp (correct format: YYYYMMDDHH:mm)
    df['MESS_DATUM'] = pd.to_datetime(
        df['MESS_DATUM'].str.strip(),
        format='%Y%m%d%H:%M',
        errors='coerce'
    )

    # Drop rows where timestamp failed
    df = df.dropna(subset=['MESS_DATUM'])

    # Keep only good quality
    df = df[df['QN_592'].isin([1, 3])]

    # Keep only datetime + GHI
    df = df[['MESS_DATUM', 'FG_LBERG']].dropna()

    # Set index
    df = df.set_index('MESS_DATUM').sort_index()

    return df


# ---------------------------------------------------
# 2. Load all three stations
# ---------------------------------------------------
base = r"C:\Users\IanPe\OneDrive - Universidade de Lisboa\Documents\IST\MEGE\~Thesis Sem 4 26\DWD data\Hourly Solar"

paths = {
    "braunlage":    os.path.join(base, "stundenwerte_ST_00656_row.zip"),
    "braunschweig": os.path.join(base, "stundenwerte_ST_00662_row.zip"),
    "norderney":    os.path.join(base, "stundenwerte_ST_03631_row.zip"),
}

braunlage    = load_station_from_zip(paths["braunlage"]).rename(columns={'FG_LBERG': 'braunlage'})
braunschweig = load_station_from_zip(paths["braunschweig"]).rename(columns={'FG_LBERG': 'braunschweig'})
norderney    = load_station_from_zip(paths["norderney"]).rename(columns={'FG_LBERG': 'norderney'})


# ---------------------------------------------------
# 3. Merge into one dataframe
# ---------------------------------------------------
df = braunlage.join(braunschweig, how='outer').join(norderney, how='outer')
df = df.dropna(how='all')   # drop rows where all stations missing


# ---------------------------------------------------
# 4. Compute long-term hourly climatology
#    group by (day-of-year, hour)
# ---------------------------------------------------
df['doy'] = df.index.dayofyear
df['hour'] = df.index.hour

clim = df.groupby(['doy', 'hour']).mean()


# ---------------------------------------------------
# 5. Average across stations (equal weighting)
# ---------------------------------------------------
clim['ghi_avg'] = clim[['braunlage', 'braunschweig', 'norderney']].mean(axis=1)


# ---------------------------------------------------
# 6. Build the final 8784-hour typical (leap) year
# ---------------------------------------------------
typical_index = pd.date_range("2020-01-01", "2020-12-31 23:00", freq="h")

typical_year = pd.DataFrame(index=typical_index)
typical_year['doy'] = typical_year.index.dayofyear
typical_year['hour'] = typical_year.index.hour

typical_year = typical_year.merge(
    clim[['ghi_avg']],
    left_on=['doy', 'hour'],
    right_index=True,
    how='left'
)

typical_year = typical_year[['ghi_avg']]

print(typical_year.head())
print(typical_year.tail())


print(typical_year.loc["2020-06-15 12:00"])
print(typical_year["ghi_avg"].describe())