"""CSV loading, validation, and local persistence helpers for provincial market data."""

from __future__ import annotations

from pathlib import Path
from typing import IO

import pandas as pd

LOCAL_MARKET_DATA_PATH = Path("data/provincial_yields_local.csv")

REQUIRED_MARKET_COLUMNS = [
    "date",
    "qc_5y",
    "qc_10y",
    "qc_30y",
    "on_5y",
    "on_10y",
    "on_30y",
]

OPTIONAL_MARKET_COLUMNS = [
    "qc_2y",
    "on_2y",
    "bidask_qc_10y_bp",
    "bidask_qc_30y_bp",
    "auction_concession_bp",
    "rating_watch_flag",
    "event_note",
]

MARKET_COLUMNS = REQUIRED_MARKET_COLUMNS + OPTIONAL_MARKET_COLUMNS

NUMERIC_MARKET_COLUMNS = [
    col for col in MARKET_COLUMNS if col not in {"date", "rating_watch_flag", "event_note"}
]


def empty_market_data() -> pd.DataFrame:
    """Return an empty market-data frame with the canonical column order."""

    return pd.DataFrame(columns=MARKET_COLUMNS)


def starter_market_data() -> pd.DataFrame:
    """Return one blank row suitable for Streamlit manual data entry."""

    today = pd.Timestamp.today().normalize()
    return pd.DataFrame(
        [
            {
                "date": today,
                "qc_5y": pd.NA,
                "qc_10y": pd.NA,
                "qc_30y": pd.NA,
                "on_5y": pd.NA,
                "on_10y": pd.NA,
                "on_30y": pd.NA,
                "qc_2y": pd.NA,
                "on_2y": pd.NA,
                "bidask_qc_10y_bp": pd.NA,
                "bidask_qc_30y_bp": pd.NA,
                "auction_concession_bp": pd.NA,
                "rating_watch_flag": False,
                "event_note": "",
            }
        ]
    )


def load_market_data(source: str | Path | IO[bytes] | IO[str]) -> pd.DataFrame:
    """Load, normalize, and validate user-supplied provincial market data."""

    df = pd.read_csv(source)
    return normalize_market_data(df)


def load_local_market_data(path: Path = LOCAL_MARKET_DATA_PATH) -> pd.DataFrame:
    """Load locally persisted manual provincial data if it exists."""

    if not path.exists():
        return empty_market_data()
    return load_market_data(path)


def save_local_market_data(df: pd.DataFrame, path: Path = LOCAL_MARKET_DATA_PATH) -> Path:
    """Persist normalized manual provincial data to a local CSV file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_market_data(df)
    normalized.to_csv(path, index=False)
    return path


def normalize_market_data(df: pd.DataFrame, require_rows: bool = False) -> pd.DataFrame:
    """Normalize provincial CSV data and raise ValueError for missing required columns.

    Québec and Ontario provincial yields are user-supplied because the app does
    not assume a clean public provincial time-series API. Required columns cover
    the minimum 5Y/10Y/30Y curve needed for core spread monitoring.
    """

    normalized = df.copy()
    normalized.columns = [str(col).strip().lower() for col in normalized.columns]
    missing = [col for col in REQUIRED_MARKET_COLUMNS if col not in normalized.columns]
    if missing:
        raise ValueError(
            "Missing required market-data columns: " + ", ".join(missing) + ". "
            "Upload a CSV matching data/market_data_template.csv or enter rows manually."
        )

    for col in MARKET_COLUMNS:
        if col not in normalized.columns:
            if col == "rating_watch_flag":
                normalized[col] = False
            elif col == "event_note":
                normalized[col] = ""
            else:
                normalized[col] = pd.NA

    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    normalized = normalized.dropna(subset=["date"])

    for col in NUMERIC_MARKET_COLUMNS:
        normalized[col] = pd.to_numeric(normalized[col], errors="coerce")

    normalized["rating_watch_flag"] = normalized["rating_watch_flag"].map(_to_bool).fillna(False)
    normalized["event_note"] = normalized["event_note"].fillna("").astype(str)

    # Drop rows that have no required yield marks. This keeps blank data-editor
    # rows from being stored while preserving rows with partial optional fields.
    required_yield_columns = [col for col in REQUIRED_MARKET_COLUMNS if col != "date"]
    normalized = normalized.dropna(subset=required_yield_columns, how="all")
    if require_rows and normalized.empty:
        raise ValueError("No valid provincial yield rows were found.")

    return normalized[MARKET_COLUMNS].sort_values("date").reset_index(drop=True)


def combine_market_data(*frames: pd.DataFrame) -> pd.DataFrame:
    """Combine multiple market-data frames, with later frames overriding dates."""

    non_empty = [frame for frame in frames if frame is not None and not frame.empty]
    if not non_empty:
        return empty_market_data()
    combined = pd.concat(non_empty, ignore_index=True)
    normalized = normalize_market_data(combined)
    return normalized.drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Serialize market data for Streamlit downloads."""

    if df.empty:
        return empty_market_data().to_csv(index=False).encode("utf-8")
    return normalize_market_data(df).to_csv(index=False).encode("utf-8")


def _to_bool(value: object) -> bool | None:
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "t", "yes", "y", "1", "watch", "negative"}:
        return True
    if text in {"false", "f", "no", "n", "0", "none", "stable", ""}:
        return False
    return bool(text)
