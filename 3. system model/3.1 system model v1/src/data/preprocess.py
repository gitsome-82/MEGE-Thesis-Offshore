"""
preprocess.py — Shared parsing helpers for raw data files.
"""
import pandas as pd


def parse_smard_timestamp(series: pd.Series) -> pd.Series:
    """Parse SMARD's two possible date formats into datetime."""
    timestamps = pd.to_datetime(series, format='%b %d, %Y %I:%M %p', errors='coerce')
    missing = timestamps.isna()
    if missing.any():
        timestamps.loc[missing] = pd.to_datetime(
            series[missing], format='%b-%d, %Y %I:%M %p', errors='coerce'
        )
    return timestamps


def parse_smard_numeric(series: pd.Series) -> pd.Series:
    """Convert SMARD comma-formatted numbers ('1,234.5') to float."""
    return pd.to_numeric(
        series.astype(str).str.replace(',', '', regex=False),
        errors='coerce',
    )
