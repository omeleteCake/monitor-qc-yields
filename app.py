"""Québec Political Risk & Yield Spread Dashboard."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from utils.boc import fetch_boc_benchmark_yields
from utils.calculations import build_alerts, latest_valid_row, prepare_dashboard_data
from utils.loaders import (
    LOCAL_MARKET_DATA_PATH,
    MARKET_COLUMNS,
    REQUIRED_MARKET_COLUMNS,
    combine_market_data,
    dataframe_to_csv_bytes,
    empty_market_data,
    load_local_market_data,
    load_market_data,
    normalize_market_data,
    save_local_market_data,
    starter_market_data,
)
from utils.sources import (
    DEALER_SNAPSHOT_LINKS,
    QC_PROJECTIONS_URL,
    QC_RATINGS_URL,
    QC_SOVEREIGNTY_POLLS_URL,
    SOURCE_LINKS,
    fetch_dealer_snapshot,
    fetch_page_text_metadata,
    fetch_quebec_ratings_tables,
    source_links_as_markdown,
)

APP_TITLE = "Québec Political Risk & Yield Spread Dashboard"
SAMPLE_DATA_PATH = Path("data/sample_market_data.csv")

st.set_page_config(page_title=APP_TITLE, page_icon="📈", layout="wide")

st.markdown(
    """
    <style>
    .main .block-container {padding-top: 1.5rem; padding-bottom: 2rem;}
    div[data-testid="stMetric"] {background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 14px;}
    .risk-card {border: 1px solid #dbe3ef; border-radius: 12px; padding: 1rem; background: #ffffff; margin-bottom: .75rem;}
    .critical {border-left: 6px solid #b91c1c; background: #fef2f2;}
    .warning {border-left: 6px solid #d97706; background: #fffbeb;}
    .info {border-left: 6px solid #2563eb; background: #eff6ff;}
    .source-note {color: #475569; font-size: .93rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def main() -> None:
    """Render the Streamlit dashboard."""

    st.title(APP_TITLE)
    st.caption(
        "Official GoC curve from Bank of Canada plus user-supplied Québec/Ontario provincial marks. "
        "No proprietary provincial feed is assumed."
    )

    sidebar = render_sidebar()
    if sidebar["refresh"]:
        fetch_boc_benchmark_yields.clear()
        st.cache_data.clear()
        st.toast("Cached public-source data cleared. Refreshing dashboard.")

    goc_df, boc_error = fetch_boc_benchmark_yields()
    market_df, market_error = build_market_data_layer(sidebar["uploaded_file"], sidebar["use_sample_data"])
    if market_error:
        st.sidebar.error(market_error)
    if boc_error:
        st.sidebar.warning(boc_error)

    dashboard_df = prepare_dashboard_data(market_df, goc_df) if not market_df.empty else empty_market_data()
    dashboard_df = filter_by_date(dashboard_df, sidebar["start_date"], sidebar["end_date"])
    goc_display_df = filter_by_date(goc_df, sidebar["start_date"], sidebar["end_date"])

    latest = latest_valid_row(dashboard_df)
    render_summary_metrics(latest, goc_display_df)

    st.divider()
    edited_market_df = render_manual_data_entry(market_df)
    dashboard_df = prepare_dashboard_data(edited_market_df, goc_df) if not edited_market_df.empty else empty_market_data()
    dashboard_df = filter_by_date(dashboard_df, sidebar["start_date"], sidebar["end_date"])

    st.divider()
    render_political_monitor()

    st.divider()
    render_market_spreads(dashboard_df, goc_display_df)

    st.divider()
    render_liquidity_and_events(dashboard_df)

    st.divider()
    render_ratings_and_fiscal()

    st.divider()
    render_source_notes()


def render_sidebar() -> dict[str, object]:
    """Render sidebar controls and return their values."""

    st.sidebar.header("Controls")
    default_end = date.today()
    default_start = default_end - timedelta(days=365)
    selected_range = st.sidebar.date_input(
        "Date range",
        value=(default_start, default_end),
        help="Filters market and Bank of Canada history shown on the dashboard.",
    )
    if isinstance(selected_range, tuple) and len(selected_range) == 2:
        start_date, end_date = selected_range
    else:
        start_date, end_date = default_start, default_end

    uploaded_file = st.sidebar.file_uploader(
        "Import provincial CSV",
        type=["csv"],
        help="Required columns: " + ", ".join(REQUIRED_MARKET_COLUMNS),
    )
    use_sample_data = st.sidebar.toggle(
        "Load synthetic sample rows",
        value=False,
        help="Uses data/sample_market_data.csv for demos only. Turn off for production manual entry.",
    )
    bidask_threshold = st.sidebar.number_input(
        "30Y bid-ask alert threshold (bps)",
        min_value=0.0,
        max_value=100.0,
        value=6.0,
        step=0.5,
        help="Triggers a liquidity warning if bidask_qc_30y_bp exceeds this level.",
    )
    refresh = st.sidebar.button("Refresh public data", use_container_width=True)
    st.sidebar.download_button(
        "Download CSV template",
        data=Path("data/market_data_template.csv").read_text(),
        file_name="market_data_template.csv",
        mime="text/csv",
        use_container_width=True,
    )
    st.sidebar.caption(f"Manual rows persist locally to `{LOCAL_MARKET_DATA_PATH}`.")
    st.session_state["bidask_threshold_bp"] = bidask_threshold
    return {
        "start_date": start_date,
        "end_date": end_date,
        "uploaded_file": uploaded_file,
        "use_sample_data": use_sample_data,
        "refresh": refresh,
    }


def build_market_data_layer(uploaded_file: object, use_sample_data: bool) -> tuple[pd.DataFrame, str | None]:
    """Build the user-supplied provincial data layer from local, CSV, and sample rows."""

    try:
        local_df = load_local_market_data()
        upload_df = load_market_data(uploaded_file) if uploaded_file is not None else empty_market_data()
        sample_df = load_market_data(SAMPLE_DATA_PATH) if use_sample_data else empty_market_data()
        session_df = (
            normalize_market_data(st.session_state["manual_market_df"])
            if "manual_market_df" in st.session_state
            else empty_market_data()
        )
        return combine_market_data(local_df, sample_df, upload_df, session_df), None
    except Exception as exc:
        return empty_market_data(), str(exc)


def filter_by_date(df: pd.DataFrame, start_date: date, end_date: date) -> pd.DataFrame:
    """Filter a dataframe with a date column using inclusive date boundaries."""

    if df.empty or "date" not in df.columns:
        return df
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
    return df[(df["date"] >= start_ts) & (df["date"] <= end_ts)].copy()


def render_summary_metrics(latest: pd.Series | None, goc_df: pd.DataFrame) -> None:
    """Render top-line metric cards."""

    st.subheader("A. Summary metrics")
    latest_goc = latest_valid_row(goc_df)
    goc_10y = latest_goc.get("goc_10y") if latest_goc is not None else None

    metrics = [
        ("Latest GoC 10Y yield", format_pct(goc_10y), "Bank of Canada benchmark 10Y yield."),
        ("Québec-Ontario 10Y", format_bp(latest, "qc_on_10y_spread_bp"), "(qc_10y - on_10y) × 100."),
        ("Québec-Ontario 30Y", format_bp(latest, "qc_on_30y_spread_bp"), "(qc_30y - on_30y) × 100."),
        ("Québec-GoC 10Y", format_bp(latest, "qc_goc_10y_spread_bp"), "(qc_10y - goc_10y) × 100."),
        ("Québec-GoC 30Y", format_bp(latest, "qc_goc_30y_spread_bp"), "(qc_30y - goc_30y) × 100; BoC Long mapped to 30Y."),
        ("Rating watch", format_flag(latest, "rating_watch_flag"), "Optional manual/CSV flag."),
        ("Auction concession", format_bp(latest, "auction_concession_bp"), "Optional manual/CSV concession field in bps."),
    ]

    cols = st.columns(4)
    for idx, (label, value, help_text) in enumerate(metrics):
        with cols[idx % 4]:
            st.metric(label, value, help=help_text)


def render_manual_data_entry(market_df: pd.DataFrame) -> pd.DataFrame:
    """Render editable manual provincial yield table with import/export/local persistence."""

    st.subheader("B. Manual provincial yield entry")
    st.markdown(
        "Québec and Ontario provincial yields are **manual/user-supplied**. "
        "Enter daily marks below, import a CSV, or save the edited table to a local CSV. "
        "Dealer pages are optional spot checks only and are not ingested automatically."
    )

    if "manual_market_df" not in st.session_state:
        st.session_state["manual_market_df"] = market_df if not market_df.empty else starter_market_data()

    editor_df = st.data_editor(
        st.session_state["manual_market_df"],
        key="manual_market_editor",
        num_rows="dynamic",
        use_container_width=True,
        column_order=MARKET_COLUMNS,
        column_config={
            "date": st.column_config.DateColumn("date", help="Observation date."),
            "rating_watch_flag": st.column_config.CheckboxColumn("rating_watch_flag"),
            "event_note": st.column_config.TextColumn("event_note", width="medium"),
        },
    )

    c1, c2, c3 = st.columns(3)
    save_clicked = c1.button("Save manual table locally", use_container_width=True)
    reset_clicked = c2.button("Reset editor from local CSV", use_container_width=True)
    c3.download_button(
        "Export current table",
        data=dataframe_to_csv_bytes(editor_df),
        file_name="provincial_yields_export.csv",
        mime="text/csv",
        use_container_width=True,
    )

    if save_clicked:
        try:
            path = save_local_market_data(editor_df)
            st.session_state["manual_market_df"] = load_local_market_data(path)
            st.success(f"Saved provincial yield rows to {path}.")
        except Exception as exc:
            st.error(f"Could not save manual table: {exc}")
    elif reset_clicked:
        st.session_state["manual_market_df"] = load_local_market_data()
        if st.session_state["manual_market_df"].empty:
            st.session_state["manual_market_df"] = starter_market_data()
        st.info("Editor reset from local CSV storage.")
    else:
        st.session_state["manual_market_df"] = editor_df

    try:
        return normalize_market_data(st.session_state["manual_market_df"])
    except Exception as exc:
        st.error(f"Manual table validation error: {exc}")
        return empty_market_data()


def render_political_monitor() -> None:
    """Render political source links and manual monitor inputs."""

    st.subheader("C. Political monitor")
    col_links, col_inputs = st.columns([1, 2], gap="large")
    with col_links:
        st.markdown("**External political references**")
        st.markdown(f"- [338Canada Québec projections]({QC_PROJECTIONS_URL})")
        st.markdown(f"- [338Canada sovereignty polling]({QC_SOVEREIGNTY_POLLS_URL})")
        with st.expander("Optional page metadata", expanded=False):
            st.caption("Fetches only HTML title/meta-description text and does not parse rendered charts.")
            if st.button("Fetch lightweight political metadata"):
                for url in (QC_PROJECTIONS_URL, QC_SOVEREIGNTY_POLLS_URL):
                    st.write(fetch_page_text_metadata(url))

    with col_inputs:
        defaults = {
            "pq_vote_share": 0.0,
            "pq_seat_projection": 0,
            "sovereignty_yes_pct": 0.0,
            "sovereignty_no_pct": 0.0,
            "next_election_date": date(2026, 10, 5),
            "referendum_commitment_flag": False,
        }
        for key, value in defaults.items():
            st.session_state.setdefault(key, value)

        with st.form("political_monitor_form"):
            c1, c2, c3 = st.columns(3)
            st.session_state["pq_vote_share"] = c1.number_input("PQ vote share (%)", min_value=0.0, max_value=100.0, value=float(st.session_state["pq_vote_share"]), step=0.1)
            st.session_state["pq_seat_projection"] = c2.number_input("PQ seat projection", min_value=0, max_value=125, value=int(st.session_state["pq_seat_projection"]), step=1)
            st.session_state["next_election_date"] = c3.date_input("Next election date", value=st.session_state["next_election_date"])
            c4, c5, c6 = st.columns(3)
            st.session_state["sovereignty_yes_pct"] = c4.number_input("Sovereignty Yes (%)", min_value=0.0, max_value=100.0, value=float(st.session_state["sovereignty_yes_pct"]), step=0.1)
            st.session_state["sovereignty_no_pct"] = c5.number_input("Sovereignty No (%)", min_value=0.0, max_value=100.0, value=float(st.session_state["sovereignty_no_pct"]), step=0.1)
            st.session_state["referendum_commitment_flag"] = c6.checkbox("Referendum commitment flag", value=bool(st.session_state["referendum_commitment_flag"]))
            st.form_submit_button("Update political monitor", use_container_width=True)


def render_market_spreads(dashboard_df: pd.DataFrame, goc_df: pd.DataFrame) -> None:
    """Render market spread charts."""

    st.subheader("D. Market spreads")
    c1, c2 = st.columns(2)
    with c1:
        render_line_chart(goc_df, ["goc_2y", "goc_5y", "goc_10y", "goc_30y"], "GoC curve time series", "Yield (%)")
    with c2:
        render_line_chart(dashboard_df, ["qc_on_5y_spread_bp", "qc_on_10y_spread_bp", "qc_on_30y_spread_bp"], "Québec vs Ontario spreads", "Spread (bps)")
    render_line_chart(dashboard_df, ["qc_goc_5y_spread_bp", "qc_goc_10y_spread_bp", "qc_goc_30y_spread_bp"], "Québec vs Government of Canada spreads", "Spread (bps)")


def render_liquidity_and_events(dashboard_df: pd.DataFrame) -> None:
    """Render liquidity charts, events, and alert box."""

    st.subheader("E. Liquidity and event monitor")
    alerts = build_alerts(
        dashboard_df,
        bidask_threshold_bp=float(st.session_state.get("bidask_threshold_bp", 6.0)),
        referendum_commitment_flag=bool(st.session_state.get("referendum_commitment_flag", False)),
    )
    render_alert_cards(alerts)

    optional_cols = [col for col in ["bidask_qc_10y_bp", "bidask_qc_30y_bp", "auction_concession_bp"] if col in dashboard_df.columns]
    if optional_cols:
        render_line_chart(dashboard_df, optional_cols, "Liquidity and auction-concession series", "Basis points")
    else:
        st.info("Add optional bid-ask or auction-concession columns to enable the liquidity chart.")

    if "event_note" in dashboard_df.columns and dashboard_df["event_note"].astype(str).str.strip().any():
        events = dashboard_df.loc[dashboard_df["event_note"].astype(str).str.strip() != "", ["date", "event_note"]].tail(10)
        st.dataframe(events, use_container_width=True, hide_index=True)


def render_ratings_and_fiscal() -> None:
    """Render official ratings link, parseable ratings table, and fiscal notes."""

    st.subheader("F. Ratings and fiscal confirmation")
    st.markdown(f"Official source: [Québec credit ratings]({QC_RATINGS_URL})")
    tables = fetch_quebec_ratings_tables()
    if tables:
        st.dataframe(tables[0], use_container_width=True, hide_index=True)
    else:
        st.info("The official ratings table could not be parsed in this session. Use the source link above and the manual override table below.")
        manual = pd.DataFrame(
            {
                "Agency": ["Moody's", "S&P", "Fitch", "DBRS Morningstar"],
                "Rating": ["", "", "", ""],
                "Outlook / watch": ["", "", "", ""],
            }
        )
        st.data_editor(manual, num_rows="dynamic", use_container_width=True, key="manual_ratings_table")

    st.text_area(
        "Fiscal notes",
        key="fiscal_notes",
        height=140,
        placeholder="Return-to-balance path; latest budget comments; debt trend comments; other confirmation signals.",
    )


def render_source_notes() -> None:
    """Render source links, dealer spot-check adapters, and dashboard disclaimer."""

    st.subheader("G. Source links and notes")
    st.markdown(source_links_as_markdown(SOURCE_LINKS))

    with st.expander("Optional public dealer snapshot spot checks", expanded=False):
        st.caption(
            "These adapters are intentionally optional. They may fail, may parse partial tables, and are not used automatically in calculations."
        )
        for link in DEALER_SNAPSHOT_LINKS:
            st.markdown(f"**[{link.label}]({link.url})** — {link.note}")
            if st.button(f"Fetch snapshot metadata: {link.label}"):
                snapshot = fetch_dealer_snapshot(link.url)
                st.write(snapshot["metadata"])
                st.info(str(snapshot["note"]))
                for table in snapshot["tables"]:
                    st.dataframe(table, use_container_width=True, hide_index=True)

    st.warning(
        "Government of Canada benchmark yields are official public data fetched automatically from the Bank of Canada. "
        "Québec and Ontario provincial yields are manual/user-supplied via editable table, CSV upload, or local CSV persistence; "
        "the app does not invent provincial time series or assume a clean public provincial API. "
        "RBC Direct Investing and Edward Jones pages, when reachable, are only indicative public spot-check snapshots and may be partial or unstable. "
        "Political pages are linked as external references. This dashboard is a monitoring tool, not a trading system or legal/political forecast."
    )


def render_line_chart(df: pd.DataFrame, columns: list[str], title: str, y_label: str) -> None:
    """Render a Plotly line chart if at least one requested column exists."""

    available = [col for col in columns if col in df.columns and df[col].notna().any()]
    if df.empty or not available or "date" not in df.columns:
        st.info(f"{title}: insufficient data available.")
        return
    long_df = df[["date", *available]].melt(id_vars="date", var_name="Series", value_name=y_label)
    fig = px.line(long_df, x="date", y=y_label, color="Series", title=title, template="plotly_white")
    fig.update_layout(legend_title_text="", margin=dict(l=20, r=20, t=55, b=20), hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)


def render_alert_cards(alerts: list[object]) -> None:
    """Render alert cards in severity order."""

    for alert in alerts:
        icon = {"critical": "🔴", "warning": "🟠", "info": "🔵"}.get(alert.severity, "🔵")
        st.markdown(
            f'<div class="risk-card {alert.severity}"><strong>{icon} {alert.title}</strong><br><span>{alert.message}</span></div>',
            unsafe_allow_html=True,
        )


def format_bp(row: pd.Series | None, column: str) -> str:
    """Format a latest-row value in basis points."""

    if row is None or column not in row or pd.isna(row[column]):
        return "n/a"
    return f"{float(row[column]):,.1f} bps"


def format_pct(value: object) -> str:
    """Format a percent yield."""

    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.2f}%"


def format_flag(row: pd.Series | None, column: str) -> str:
    """Format a boolean flag from the latest row."""

    if row is None or column not in row or pd.isna(row[column]):
        return "n/a"
    return "Yes" if bool(row[column]) else "No"


if __name__ == "__main__":
    main()
