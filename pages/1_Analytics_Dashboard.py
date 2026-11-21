"""DataHealth AI — interactive analytics dashboard for synthetic Synthea records.

This page is added automatically by Streamlit's multipage pages/ directory.
It uses the existing SQLite Gold Layer in read-only mode and never invokes the LLM.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import csv
import io
import sqlite3

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import analytics_backend as analytics

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "gold" / "datahealth.db"
BRAND_CSS = ROOT / "assets" / "datahealth.css"
DASHBOARD_CSS = ROOT / "assets" / "analytics_dashboard.css"
TEAL = "#4ADAC5"
BLUE = "#78A9FF"
PURPLE = "#BAA6F7"
AMBER = "#F2C078"
PALETTE = [TEAL, BLUE, PURPLE, AMBER, "#80D3E7", "#EA8D9B", "#9DB6CD"]

st.set_page_config(
    page_title="DataHealth AI | Analytics Dashboard", page_icon="📊",
    layout="wide", initial_sidebar_state="expanded",
)
for path in (BRAND_CSS, DASHBOARD_CSS):
    if path.is_file():
        st.markdown(f"<style>{path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


@st.cache_data(ttl=60, show_spinner=False)
def patients_cached(db_path: str) -> list[dict]:
    return analytics.list_patients(Path(db_path))


@st.cache_data(ttl=60, show_spinner=False)
def bounds_cached(db_path: str) -> tuple[str | None, str | None]:
    return analytics.observation_date_bounds(Path(db_path))


def fig_style(fig: go.Figure, *, height: int = 340, y_title: str | None = None) -> go.Figure:
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#D6E6F6", "size": 12},
        margin={"l": 16, "r": 16, "t": 22, "b": 22},
        height=height, hovermode="x unified", showlegend=False,
        xaxis={"showgrid": False, "zeroline": False, "linecolor": "#3B526A"},
        yaxis={"gridcolor": "rgba(141,179,213,0.13)", "zeroline": False,
               "title": y_title},
    )
    return fig


def chart(fig: go.Figure, key: str) -> None:
    st.plotly_chart(fig, width="stretch", theme=None, key=key,
                    config={"displaylogo": False, "scrollZoom": False,
                            "toImageButtonOptions": {"format": "png", "scale": 2}})


def dataframe(rows: list[dict], key: str) -> None:
    if not rows:
        st.info("No records match the selected filters.")
        return
    table = pd.DataFrame(rows)
    st.dataframe(table, width="stretch", hide_index=True, key=key)


def csv_download(rows: list[dict], key: str, filename: str) -> None:
    """Export visible records while escaping spreadsheet-formula-like strings."""
    if not rows:
        return
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    for row in rows:
        clean = {}
        for name, value in row.items():
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                clean[name] = "'" + value
            else:
                clean[name] = value
        writer.writerow(clean)
    st.download_button("Download filtered CSV", output.getvalue().encode("utf-8-sig"),
                       file_name=filename, mime="text/csv", width="stretch", key=key)


if not DATABASE.is_file():
    st.error("Gold SQLite database not found. Run Phase 4 and launch Streamlit from the project root.")
    st.stop()
try:
    patients = patients_cached(str(DATABASE))
    first_date_str, last_date_str = bounds_cached(str(DATABASE))
except (sqlite3.Error, ValueError, OSError) as exc:
    st.error(f"Unable to read the synthetic Gold Layer: {exc}")
    st.stop()
if not patients:
    st.warning("The synthetic Gold Layer has no patients.")
    st.stop()

patient_lookup = {p["patient_id"]: p for p in patients}
patient_ids = [p["patient_id"] for p in patients]

with st.sidebar:
    st.markdown(
        '<div class="dh-sidebar-logo"><div class="dh-logo-mark">DH<span>+</span></div>'
        '<div><div class="dh-sidebar-wordmark">DataHealth <span>AI</span></div>'
        '<div class="dh-sidebar-caption">ANALYTICS WORKSPACE</div></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="dh-sidebar-section">ANALYSIS FILTERS</div>', unsafe_allow_html=True)
    scope_options = ["__ALL__", *patient_ids]
    scope_value = st.selectbox(
        "Population scope", scope_options,
        format_func=lambda value: "All synthetic patients" if value == "__ALL__"
            else f"{patient_lookup[value].get('full_name') or 'Unnamed'} · {value[:8]}",
        key="dashboard_scope",
    )
    selected_patient = None if scope_value == "__ALL__" else scope_value
    selected_category = st.selectbox("Observation category", analytics.OBSERVATION_CATEGORIES)
    time_choice = st.selectbox(
        "Observation date range", ["All recorded dates", "Last 365 days of dataset", "Custom range"],
    )
    start_date = end_date = None
    if time_choice == "Last 365 days of dataset" and last_date_str:
        end_date = last_date_str
        start_date = (date.fromisoformat(last_date_str) - timedelta(days=365)).isoformat()
        st.caption(f"Relative to the dataset's last observation ({end_date}), not today.")
    elif time_choice == "Custom range":
        start_default = date.fromisoformat(first_date_str) if first_date_str else date(2000, 1, 1)
        end_default = date.fromisoformat(last_date_str) if last_date_str else date.today()
        picked = st.date_input(
            "Recorded between", (start_default, end_default),
            min_value=date(1900, 1, 1), max_value=date(2100, 12, 31),
        )
        if not isinstance(picked, tuple) or len(picked) != 2:
            st.info("Choose a start date and an end date to continue.")
            st.stop()
        start_date, end_date = picked[0].isoformat(), picked[1].isoformat()
    st.markdown(
        '<div class="dh-sidebar-section">DATA INTEGRITY</div>'
        '<p class="dh-dashboard-sidebar-note">Source: local SQLite Gold Layer. '
        'All queries are read-only. Trends never merge distinct units. '
        'Flags identify structural review needs, not clinical validity.</p>',
        unsafe_allow_html=True,
    )

filters = {"patient_id": selected_patient, "start_date": start_date,
           "end_date": end_date, "category": selected_category}

st.markdown(
    '<section class="dh-hero dh-dashboard-hero">'
    '<div class="dh-kicker">DATAHEALTH AI / ANALYTICS</div>'
    '<h1>Clinical data, <em>clearly explored.</em></h1>'
    '<p>Interactive exploration of synthetic FHIR records, patient trends, '
    'data-quality flags and operational activity.</p>'
    '<div class="dh-hero-tags"><span>Gold Layer</span><span>Exploratory Analytics</span>'
    '<span>Read-only SQL</span><span>Synthetic Dataset</span></div>'
    '</section>', unsafe_allow_html=True,
)
st.markdown(
    '<div class="dh-disclaimer"><strong>SYNTHETIC DATA ONLY</strong> · '
    'This dashboard is for exploratory data analysis, not clinical monitoring, '
    'diagnosis, prediction or patient care. Structural validation is not clinical validation.'
    '</div>', unsafe_allow_html=True,
)

scope_name = ("All synthetic patients" if selected_patient is None else
              str(patient_lookup[selected_patient].get("full_name") or selected_patient))
st.markdown('<div class="dh-eyebrow">ANALYSIS SCOPE</div>', unsafe_allow_html=True)
st.subheader(scope_name)
st.caption(
    f"Category: {selected_category} · "
    f"Date range: {start_date or 'earliest available'} to {end_date or 'latest available'} · "
    "All dates use stored UTC timestamps."
)

try:
    overview = analytics.kpis(DATABASE, **filters)
except (sqlite3.Error, ValueError, OSError) as exc:
    st.error(f"Unable to generate dashboard metrics: {exc}")
    st.stop()

cards = st.columns(4)
cards[0].metric("Patients in scope", f"{overview['population_patients']:,}")
cards[1].metric("Encounters in period", f"{overview['encounters']:,}")
cards[2].metric("Observation value rows", f"{overview['observation_rows']:,}")
flag_rate = (100.0 * overview["flagged_rows"] / overview["observation_rows"]
             if overview["observation_rows"] else 0.0)
cards[3].metric("Rows flagged for review", f"{overview['flagged_rows']:,}", f"{flag_rate:.2f}% of rows", delta_color="off")
st.caption("Patient count is independent of the date filter. Observation totals count normalized value rows, not unique events.")

tab_overview, tab_patient, tab_quality, tab_operations = st.tabs([
    "Dataset overview", "Patient trends", "Data quality", "Operations",
])

with tab_overview:
    a, b = st.columns([1.18, 1])
    with a:
        st.markdown('<div class="dh-section-title">Observation activity over time</div>', unsafe_allow_html=True)
        granularity = st.radio("Time grouping", ["Year", "Month"], horizontal=True, key="obs_granularity")
        activity = analytics.observation_activity(DATABASE, **filters, granularity=granularity.lower())
        if activity:
            fig = go.Figure(go.Bar(
                x=[r["period"] for r in activity], y=[r["observation_rows"] for r in activity],
                marker_color=TEAL, hovertemplate="%{x}: %{y:,} rows<extra></extra>",
            ))
            chart(fig_style(fig, y_title="Value rows"), "obs_activity")
        else:
            st.info("No dated observations in this scope.")
    with b:
        st.markdown('<div class="dh-section-title">Observation categories</div>', unsafe_allow_html=True)
        distribution = analytics.category_distribution(DATABASE, **filters)
        if distribution:
            fig = go.Figure(go.Pie(
                labels=[r["category"] for r in distribution],
                values=[r["observation_rows"] for r in distribution],
                hole=0.66, marker={"colors": PALETTE},
                textinfo="label+percent", textposition="outside",
                hovertemplate="%{label}<br>%{value:,} rows<extra></extra>",
            ))
            chart(fig_style(fig), "obs_categories")
        else:
            st.info("No categories to display.")
    st.markdown('<div class="dh-section-title">Most frequent measurements</div>', unsafe_allow_html=True)
    frequent = analytics.top_measurements(DATABASE, **filters)
    if frequent:
        labels = [f"{r['display']} · {r['unit_code'] or 'no unit'}" for r in frequent]
        fig = go.Figure(go.Bar(
            x=[r["count"] for r in reversed(frequent)], y=list(reversed(labels)),
            orientation="h", marker_color=BLUE,
            hovertemplate="%{y}<br>%{x:,} rows<extra></extra>",
        ))
        fig = fig_style(fig, height=420, y_title=None)
        fig.update_layout(margin={"l": 220, "r": 22, "t": 22, "b": 22})
        chart(fig, "top_measurements")
    st.markdown('<div class="dh-section-title">Latest source records</div>', unsafe_allow_html=True)
    latest = analytics.latest_observations(DATABASE, **filters, limit=100)
    st.caption("Up to 100 newest normalized values. These records may contain unreviewed units and codes.")
    dataframe(latest, "latest_values_table")
    csv_download(latest, "download_latest_values", "datahealth_observations_filtered.csv")

with tab_patient:
    st.markdown('<div class="dh-section-title">Patient measurement trends</div>', unsafe_allow_html=True)
    if selected_patient is None:
        trend_patient = st.selectbox(
            "Select a synthetic patient for longitudinal trends", patient_ids,
            format_func=lambda pid: f"{patient_lookup[pid].get('full_name') or 'Unnamed'} · {pid[:8]}",
            key="trend_patient_id",
        )
    else:
        trend_patient = selected_patient
        st.caption(f"Patient: {scope_name}")
    options = analytics.measurement_options(
        DATABASE, trend_patient, start_date=start_date, end_date=end_date,
        category=selected_category,
    )
    if not options:
        st.info("No numeric measurements match the selected patient and date/category filters.")
    else:
        selection = st.selectbox(
            "Measurement (code + unit)", range(len(options)),
            format_func=lambda i: (
                f"{options[i]['display']} · {options[i]['measurement_code']} · "
                f"{options[i]['unit_code'] or 'unit not recorded'} "
                f"({options[i]['count']} rows, {options[i]['flagged_count']} flagged)"
            ), key="trend_measurement",
        )
        opt = options[selection]
        include_flagged = st.checkbox(
            "Show records flagged for review", value=False,
            help="Flags are retained and visually distinguished. They are not cleared or corrected.",
        )
        series = analytics.measurement_series(
            DATABASE, trend_patient, opt["measurement_code"], opt["unit_code"],
            start_date=start_date, end_date=end_date, category=selected_category,
            include_flagged=include_flagged,
        )
        trend = series["rows"]
        st.caption(
            f"Code: {opt['measurement_code']} · Unit: {opt['unit_code'] or 'not recorded'} · "
            "No conversion, reference range or clinical judgment is applied."
        )
        if series["truncated"]:
            st.warning("Showing only the 750 most recent matching rows. Export is limited to the displayed rows.")
        if trend:
            fig = go.Figure()
            valid_rows = [r for r in trend if r["quality_status"] != "REVIEW_REQUIRED"]
            flagged_rows = [r for r in trend if r["quality_status"] == "REVIEW_REQUIRED"]
            if valid_rows:
                fig.add_trace(go.Scatter(
                    x=[r["effective_datetime_utc"] for r in valid_rows],
                    y=[r["value_numeric"] for r in valid_rows],
                    name="Structural checks passed", mode="lines+markers",
                    line={"color": TEAL, "width": 2}, marker={"size": 8},
                    customdata=[r["observation_id"] for r in valid_rows],
                    hovertemplate="%{x}<br>%{y:.3f}<br>Observation: %{customdata}<extra></extra>",
                ))
            if flagged_rows:
                fig.add_trace(go.Scatter(
                    x=[r["effective_datetime_utc"] for r in flagged_rows],
                    y=[r["value_numeric"] for r in flagged_rows],
                    name="Review required", mode="markers",
                    marker={"color": AMBER, "size": 12, "symbol": "diamond"},
                    customdata=[r["observation_id"] for r in flagged_rows],
                    hovertemplate="%{x}<br>%{y:.3f}<br>Review required<br>Observation: %{customdata}<extra></extra>",
                ))
            fig = fig_style(fig, height=400, y_title=opt["unit_code"] or "Unit not recorded")
            fig.update_layout(showlegend=bool(valid_rows and flagged_rows))
            chart(fig, "patient_trend")
            dataframe(trend, "trend_table")
            csv_download(trend, "trend_csv", "datahealth_patient_trend.csv")
        else:
            st.info("No eligible results. Try enabling flagged records or modifying filters.")

with tab_quality:
    st.markdown('<div class="dh-section-title">Structural quality assessment</div>', unsafe_allow_html=True)
    results = analytics.quality_summary(DATABASE, **filters)
    st.caption("Quality flags identify records requiring metadata review. They do not label a result as clinically normal or abnormal.")
    x, y = st.columns(2)
    with x:
        st.markdown("**Quality status distribution**")
        statuses = results["status"]
        if statuses:
            fig = go.Figure(go.Pie(labels=list(statuses), values=list(statuses.values()),
                                   hole=0.65, textinfo="label+percent", textposition="outside",
                                   marker={"colors": [TEAL, AMBER, BLUE]}))
            chart(fig_style(fig), "quality_status")
        else:
            st.info("No quality statuses in this scope.")
    with y:
        st.markdown("**Reasons flagged for review**")
        flags = results["flags"]
        if flags:
            fig = go.Figure(go.Bar(x=list(flags), y=list(flags.values()), marker_color=AMBER,
                                   hovertemplate="%{x}<br>%{y:,} rows<extra></extra>"))
            chart(fig_style(fig, y_title="Flag occurrences"), "quality_flags")
            st.caption("A row may have more than one flag; flag totals can exceed flagged-row count.")
        else:
            st.success("No flagged observations match these filters.")
    st.markdown("**Records needing review (sample)**")
    problem_rows = analytics.flagged_observations(DATABASE, **filters, limit=100)
    st.caption("Up to 100 latest flagged observations. Export covers only displayed rows, not all flagged records.")
    dataframe(problem_rows, "flagged_sample")
    csv_download(problem_rows, "flagged_sample_download", "datahealth_flagged_sample.csv")

with tab_operations:
    st.markdown('<div class="dh-section-title">Operational activity</div>', unsafe_allow_html=True)
    st.caption("Counts represent recorded synthetic events, not staffing, bed occupancy, or real-time hospital utilization.")
    a, b = st.columns(2)
    with a:
        grouping = st.radio("Encounter time grouping", ["Year", "Month"],
                            horizontal=True, key="enc_grouping")
        encounter_periods = analytics.encounter_activity(
            DATABASE, patient_id=selected_patient,
            start_date=start_date, end_date=end_date,
            granularity=grouping.lower(),
        )
        st.markdown("**Recorded encounters over time**")
        if encounter_periods:
            fig = go.Figure(go.Bar(x=[r["period"] for r in encounter_periods],
                                   y=[r["encounters"] for r in encounter_periods],
                                   marker_color=BLUE))
            chart(fig_style(fig, y_title="Encounters"), "enc_activity")
        else:
            st.info("No dated encounters match the filters.")
    with b:
        docs = analytics.clinical_document_status(
            DATABASE, patient_id=selected_patient,
            start_date=start_date, end_date=end_date,
        )
        st.markdown("**Clinical document status**")
        if docs:
            fig = go.Figure(go.Bar(x=[r["status"] for r in docs],
                                   y=[r["count"] for r in docs],
                                   marker_color=[TEAL if r["status"] == "current" else PURPLE for r in docs]))
            chart(fig_style(fig, y_title="Documents"), "document_status")
        else:
            st.info("No dated clinical documents match the filters.")
    st.caption("Superseded documents are preserved as historical records and excluded from the default RAG index.")
    with st.expander("Inspect operational aggregates"):
        st.markdown("**Encounter periods**")
        dataframe(encounter_periods, "encounter_aggregates")
        st.markdown("**Document statuses**")
        dataframe(docs, "document_aggregates")

st.markdown(
    '<div class="dh-app-footer">DataHealth AI <span>·</span> '
    'Synthetic Synthea data <span>·</span> Read-only SQLite <span>·</span> '
    'Exploratory analytics only <span>·</span> Not for clinical decisions</div>',
    unsafe_allow_html=True,
)
