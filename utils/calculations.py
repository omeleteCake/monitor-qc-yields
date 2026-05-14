"""Calculation and alert logic for Québec yield-spread monitoring."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

SPREAD_COLUMNS = [
    "qc_on_2y_spread_bp",
    "qc_on_5y_spread_bp",
    "qc_on_10y_spread_bp",
    "qc_on_30y_spread_bp",
    "qc_goc_5y_spread_bp",
    "qc_goc_10y_spread_bp",
    "qc_goc_30y_spread_bp",
]


@dataclass(frozen=True)
class Alert:
    """A dashboard alert with a severity and message."""

    severity: str
    title: str
    message: str


def merge_market_and_goc(market_df: pd.DataFrame, goc_df: pd.DataFrame) -> pd.DataFrame:
    """Merge provincial data with the latest same-day or prior GoC observation."""

    if market_df.empty:
        return market_df.copy()
    market = market_df.copy().sort_values("date")
    if goc_df.empty or "date" not in goc_df.columns:
        return market.reset_index(drop=True)
    goc = goc_df.copy().sort_values("date")
    return pd.merge_asof(market, goc, on="date", direction="backward").reset_index(drop=True)


def compute_spreads(df: pd.DataFrame) -> pd.DataFrame:
    """Compute Québec-Ontario and Québec-GoC spreads in basis points."""

    result = df.copy()
    spread_pairs = {
        "qc_on_2y_spread_bp": ("qc_2y", "on_2y"),
        "qc_on_5y_spread_bp": ("qc_5y", "on_5y"),
        "qc_on_10y_spread_bp": ("qc_10y", "on_10y"),
        "qc_on_30y_spread_bp": ("qc_30y", "on_30y"),
        "qc_goc_5y_spread_bp": ("qc_5y", "goc_5y"),
        "qc_goc_10y_spread_bp": ("qc_10y", "goc_10y"),
        "qc_goc_30y_spread_bp": ("qc_30y", "goc_30y"),
    }
    for target, (left, right) in spread_pairs.items():
        if left in result.columns and right in result.columns:
            result[target] = (result[left] - result[right]) * 100
    return result


def add_change_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Add 5-day and 20-day changes for 10Y and 30Y Québec-Ontario spreads."""

    result = df.copy().sort_values("date") if "date" in df.columns else df.copy()
    for tenor in ("10y", "30y"):
        col = f"qc_on_{tenor}_spread_bp"
        if col in result.columns:
            result[f"{col}_chg_5d"] = result[col].diff(5)
            result[f"{col}_chg_20d"] = result[col].diff(20)
    return result


def add_z_scores(df: pd.DataFrame, window: int = 60, min_periods: int = 20) -> pd.DataFrame:
    """Add rolling z-scores for 10Y and 30Y Québec-Ontario spreads when history exists."""

    result = df.copy()
    for tenor in ("10y", "30y"):
        col = f"qc_on_{tenor}_spread_bp"
        if col not in result.columns:
            continue
        rolling_mean = result[col].rolling(window=window, min_periods=min_periods).mean()
        rolling_std = result[col].rolling(window=window, min_periods=min_periods).std()
        result[f"{col}_zscore"] = (result[col] - rolling_mean) / rolling_std.replace(0, pd.NA)
    return result


def prepare_dashboard_data(market_df: pd.DataFrame, goc_df: pd.DataFrame) -> pd.DataFrame:
    """Merge datasets and add all dashboard calculations."""

    merged = merge_market_and_goc(market_df, goc_df)
    return add_z_scores(add_change_metrics(compute_spreads(merged)))


def latest_valid_row(df: pd.DataFrame) -> pd.Series | None:
    """Return the latest row by date, or None for empty data."""

    if df.empty:
        return None
    sorted_df = df.sort_values("date") if "date" in df.columns else df
    return sorted_df.iloc[-1]


def build_alerts(df: pd.DataFrame, bidask_threshold_bp: float, referendum_commitment_flag: bool) -> list[Alert]:
    """Build ordered alert messages using dashboard rule thresholds."""

    alerts: list[Alert] = []
    if referendum_commitment_flag:
        alerts.append(Alert("critical", "Referendum commitment", "Political monitor marks a referendum commitment as active."))

    row = latest_valid_row(df)
    if row is None:
        if not alerts:
            alerts.append(Alert("info", "No market data", "Upload a CSV or enable sample data to calculate market alerts."))
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        return sorted(alerts, key=lambda alert: severity_order.get(alert.severity, 99))

    if _value_gt(row.get("qc_on_10y_spread_bp_chg_5d"), 5):
        alerts.append(Alert("warning", "10Y spread widening", "Québec-Ontario 10Y spread widened by more than 5 bps over 5 observations."))
    if _value_gt(row.get("qc_on_30y_spread_bp_chg_5d"), 7):
        alerts.append(Alert("critical", "30Y spread widening", "Québec-Ontario 30Y spread widened by more than 7 bps over 5 observations."))
    if _value_gt(row.get("bidask_qc_30y_bp"), bidask_threshold_bp):
        alerts.append(Alert("warning", "30Y liquidity threshold", f"Québec 30Y bid-ask is above {bidask_threshold_bp:.1f} bps."))
    if bool(row.get("rating_watch_flag", False)):
        alerts.append(Alert("critical", "Rating watch flag", "Uploaded data marks Québec as on rating watch or comparable status."))

    if not alerts:
        alerts.append(Alert("info", "No active alerts", "No dashboard alert thresholds are currently breached."))

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(alerts, key=lambda alert: severity_order.get(alert.severity, 99))


def _value_gt(value: object, threshold: float) -> bool:
    try:
        if pd.isna(value):
            return False
        return float(value) > threshold
    except (TypeError, ValueError):
        return False
