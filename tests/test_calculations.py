import pandas as pd

from utils.calculations import build_alerts, compute_spreads, prepare_dashboard_data


def test_compute_required_qc_on_spreads_in_basis_points():
    df = pd.DataFrame(
        {
            "qc_5y": [3.25],
            "on_5y": [3.00],
            "qc_10y": [3.75],
            "on_10y": [3.20],
            "qc_30y": [4.00],
            "on_30y": [3.35],
        }
    )

    result = compute_spreads(df)

    assert round(result.loc[0, "qc_on_5y_spread_bp"], 6) == 25.0
    assert round(result.loc[0, "qc_on_10y_spread_bp"], 6) == 55.0
    assert round(result.loc[0, "qc_on_30y_spread_bp"], 6) == 65.0


def test_compute_optional_qc_on_2y_spread_when_optional_columns_present():
    df = pd.DataFrame({"qc_2y": [3.10], "on_2y": [3.00]})

    result = compute_spreads(df)

    assert round(result.loc[0, "qc_on_2y_spread_bp"], 6) == 10.0


def test_compute_qc_goc_spreads_when_goc_columns_present():
    df = pd.DataFrame(
        {
            "qc_5y": [3.50],
            "goc_5y": [3.00],
            "qc_10y": [3.70],
            "goc_10y": [3.10],
            "qc_30y": [4.10],
            "goc_30y": [3.25],
        }
    )

    result = compute_spreads(df)

    assert round(result.loc[0, "qc_goc_5y_spread_bp"], 6) == 50.0
    assert round(result.loc[0, "qc_goc_10y_spread_bp"], 6) == 60.0
    assert round(result.loc[0, "qc_goc_30y_spread_bp"], 6) == 85.0


def test_prepare_dashboard_data_adds_five_day_change():
    dates = pd.date_range("2026-01-01", periods=6, freq="B")
    market = pd.DataFrame(
        {
            "date": dates,
            "qc_5y": [3.0] * 6,
            "qc_10y": [3.50, 3.51, 3.52, 3.53, 3.54, 3.60],
            "qc_30y": [4.00, 4.01, 4.02, 4.03, 4.04, 4.10],
            "on_5y": [2.8] * 6,
            "on_10y": [3.00] * 6,
            "on_30y": [3.30] * 6,
        }
    )
    goc = pd.DataFrame({"date": dates, "goc_5y": [2.7] * 6, "goc_10y": [2.8] * 6, "goc_30y": [3.0] * 6})

    result = prepare_dashboard_data(market, goc)

    assert round(result.loc[5, "qc_on_10y_spread_bp_chg_5d"], 6) == 10.0
    assert round(result.loc[5, "qc_on_30y_spread_bp_chg_5d"], 6) == 10.0


def test_build_alerts_orders_critical_before_warning():
    df = pd.DataFrame(
        {
            "date": [pd.Timestamp("2026-01-01")],
            "qc_on_10y_spread_bp_chg_5d": [6.0],
            "qc_on_30y_spread_bp_chg_5d": [8.0],
            "bidask_qc_30y_bp": [9.0],
            "rating_watch_flag": [False],
        }
    )

    alerts = build_alerts(df, bidask_threshold_bp=6.0, referendum_commitment_flag=False)

    assert alerts[0].severity == "critical"
    assert [alert.severity for alert in alerts].count("warning") == 2
