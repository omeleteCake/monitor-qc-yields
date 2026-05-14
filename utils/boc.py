"""Bank of Canada Valet API ingestion for benchmark Government of Canada yields."""

from __future__ import annotations

from io import StringIO

import pandas as pd
import requests
import streamlit as st

from utils.sources import BOC_VALET_CSV_URL

SERIES_TO_COLUMN = {
    "v39051": "goc_2y",
    "v39052": "goc_3y",
    "v39053": "goc_5y",
    "v39054": "goc_7y",
    "v39055": "goc_10y",
    "v39056": "goc_30y",
}

LABEL_TO_COLUMN = {
    "2 year": "goc_2y",
    "2-year": "goc_2y",
    "3 year": "goc_3y",
    "3-year": "goc_3y",
    "5 year": "goc_5y",
    "5-year": "goc_5y",
    "7 year": "goc_7y",
    "7-year": "goc_7y",
    "10 year": "goc_10y",
    "10-year": "goc_10y",
    "long": "goc_30y",
    "30 year": "goc_30y",
    "30-year": "goc_30y",
}

NORMALIZED_COLUMNS = ["date", "goc_2y", "goc_3y", "goc_5y", "goc_7y", "goc_10y", "goc_30y"]


@st.cache_data(ttl=60 * 60, show_spinner=False)
def fetch_boc_benchmark_yields(url: str = BOC_VALET_CSV_URL) -> tuple[pd.DataFrame, str | None]:
    """Download and parse Bank of Canada benchmark bond yields.

    Returns a tuple of (dataframe, error). Network and parsing failures are
    converted into an empty dataframe plus a friendly error message.
    """

    try:
        response = requests.get(url, timeout=20, headers={"User-Agent": "qc-risk-dashboard/1.0"})
        response.raise_for_status()
        return parse_boc_csv(response.text), None
    except Exception as exc:
        return pd.DataFrame(columns=NORMALIZED_COLUMNS), f"Bank of Canada data unavailable: {exc}"


def parse_boc_csv(csv_text: str) -> pd.DataFrame:
    """Parse a Valet CSV payload and normalize selected benchmark yields."""

    if not csv_text.strip():
        return pd.DataFrame(columns=NORMALIZED_COLUMNS)

    lines = csv_text.splitlines()
    header_idx = next((idx for idx, line in enumerate(lines) if line.lower().startswith("date,")), 0)
    df = pd.read_csv(StringIO("\n".join(lines[header_idx:])))
    df.columns = [str(col).strip() for col in df.columns]

    rename_map: dict[str, str] = {}
    for col in df.columns:
        lower = col.lower().strip()
        if lower == "date":
            rename_map[col] = "date"
        elif lower in SERIES_TO_COLUMN:
            rename_map[col] = SERIES_TO_COLUMN[lower]
        else:
            for label, normalized in LABEL_TO_COLUMN.items():
                if label in lower:
                    rename_map[col] = normalized
                    break

    df = df.rename(columns=rename_map)
    keep = [col for col in NORMALIZED_COLUMNS if col in df.columns]
    if "date" not in keep:
        return pd.DataFrame(columns=NORMALIZED_COLUMNS)

    normalized = df[keep].copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    for col in [col for col in normalized.columns if col != "date"]:
        normalized[col] = pd.to_numeric(normalized[col], errors="coerce")

    normalized = normalized.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    for col in NORMALIZED_COLUMNS:
        if col not in normalized.columns:
            normalized[col] = pd.NA
    return normalized[NORMALIZED_COLUMNS]
