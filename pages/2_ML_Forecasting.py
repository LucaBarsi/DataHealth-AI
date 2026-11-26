"""Phase 18.1 — read-only local ML forecasting dashboard for synthetic monthly encounters.

Uses already-generated Phase 18 aggregate reports; DOES NOT train models or
connect to the public Cloud Demo, SQLite database, or hosted Qwen API.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.ml_dashboard_data import read_report

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports" / "ml" / "phase18"
BRAND_CSS = ROOT / "assets" / "datahealth.css"
TEAL = "#48D7C1"
BLUE = "#78A9FF"
AMBER = "#F0B976"
GRAY = "#A8B9CB"

st.set_page_config(page_title="DataHealth AI | ML Forecasting", page_icon="📈", layout="wide")
if BRAND_CSS.is_file():
    st.markdown(f"<style>{BRAND_CSS.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def style_chart(fig: go.Figure, height: int = 370) -> go.Figure:
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"color": "#D6E6F6", "size": 12},
        margin={"l": 16, "r": 16, "t": 24, "b": 20},
        hovermode="x unified", legend={"orientation": "h", "y": 1.14, "x": 0},
        xaxis={"showgrid": False, "linecolor": "#344C68", "title": "UTC calendar month"},
        yaxis={"gridcolor": "rgba(141,179,213,0.14)", "title": "Synthetic encounters", "rangemode": "tozero"},
    )
    return fig


with st.sidebar:
    st.markdown(
        '<div class="dh-sidebar-logo"><div class="dh-logo-mark">DH<span>+</span></div>'
        '<div><div class="dh-sidebar-wordmark">DataHealth <span>AI</span></div>'
        '<div class="dh-sidebar-caption">LOCAL ML EXPERIMENT</div></div></div>',
        unsafe_allow_html=True,
    )
    st.caption("Read-only reports · No model training · No API calls")
    st.info("Runs on synthetic monthly encounter counts only. This is not an operational forecast.")

st.markdown(
    '<section class="dh-hero dh-dashboard-hero">'
    '<div class="dh-kicker">DATAHEALTH AI / MACHINE LEARNING</div>'
    '<h1>Workload forecasting.<br><em>Evidence before prediction.</em></h1>'
    '<p>Exploratory one-step-ahead evaluation of monthly synthetic encounters.</p>'
    '<div class="dh-hero-tags"><span>Gold Layer</span><span>Random Forest & baselines</span>'
    '<span>Chronological evaluation</span><span>Read-only reports</span></div></section>',
    unsafe_allow_html=True,
)
st.warning("SYNTHETIC DATA ONLY · This dashboard does not predict actual hospital demand or provide clinical guidance.")

try:
    report = read_report(REPORTS)
except (OSError, ValueError, KeyError, TypeError) as exc:
    st.error("Phase 18 reports could not be loaded. Ensure that the local training run completed and the CSV/JSON files exist.")
    st.code(str(exc))
    st.code('.\\.venv\\Scripts\\python.exe -m src.workload_forecast run --database "data/gold/datahealth.db" --as-of 2026-11-22 --window 60 --output "reports/ml/phase18"', language="powershell")
    st.stop()

summary = report["summary"]
audit = report["audit"]
selected = report["selected"]
name = report["selected_model"].replace("_", " ").title()

st.caption(f"Analysis window: {audit['first_complete_month']} – {audit['last_complete_month']} · "
           f"Model selected using validation MAE · Test set: {summary['test_first_month']} – {summary['test_last_month']}")
a, b, c, d = st.columns(4)
a.metric("Selected model", name)
b.metric("Test MAE", f"{selected['test_mae']:.2f} encounters")
c.metric("Test RMSE", f"{selected['test_rmse']:.2f}")
d.metric("Test WAPE", f"{selected['test_wape_pct']:.2f}%" if selected['test_wape_pct'] is not None else "N/A")

history_tab, test_tab, model_tab = st.tabs(["Historical Activity", "Observed vs Predicted", "Model Comparison"])

with history_tab:
    history = pd.DataFrame(report["monthly"])
    max_months = len(history)
    choices = [n for n in (12, 24, 36, 60) if n <= max_months]
    if max_months not in choices:
        choices.append(max_months)
    options = sorted(set(choices))
    count = st.select_slider("Historical months displayed", options=options, value=max(options))
    subset = history.tail(count)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=subset["month"], y=subset["encounters"], name="Encounters",
                             line={"color": TEAL, "width": 2.5}, mode="lines+markers"))
    st.plotly_chart(style_chart(fig), width="stretch", theme=None, config={"displaylogo": False})
    st.caption(f"{audit['encounters_in_window']:,} encounters across {audit['window_months']} complete months. "
               "Charts display aggregated synthetic counts, not patient-level data.")

with test_tab:
    prediction = pd.DataFrame(report["predictions"])
    show_baselines = st.toggle("Show naive baselines", value=False)
    fig = go.Figure()
    series = [("Observed", "observed", BLUE), (name + " prediction", "predicted", TEAL)]
    if show_baselines:
        series.extend([("Last-month baseline", "last_month", AMBER),
                       ("12-month seasonal baseline", "seasonal_12", GRAY)])
    for label, key, color in series:
        fig.add_trace(go.Scatter(x=prediction["month"], y=prediction[key], name=label,
                                 mode="lines+markers", line={"color": color, "width": 2.5}))
    st.plotly_chart(style_chart(fig), width="stretch", theme=None, config={"displaylogo": False})
    st.caption("Held-out **rolling one-step-ahead** predictions use actual earlier-month counts at each step. "
               "This is NOT an unattended forecast for multiple future months.")
    with st.expander("Inspect the monthly predictions"):
        table = prediction.rename(columns={"month": "Month", "observed": "Observed", "predicted": "Selected model",
                                           "last_month": "Last-month baseline", "seasonal_12": "Seasonal baseline"})
        st.dataframe(table, width="stretch", hide_index=True)

with model_tab:
    rows = pd.DataFrame(report["models"])
    rows["model"] = rows["model"].str.replace("_", " ").str.title()
    rows["selected"] = rows["selected"].map({True: "Yes", False: "No"})
    display = rows.rename(columns={"model": "Model", "validation_mae": "Validation MAE", "test_mae": "Test MAE",
                                   "test_rmse": "Test RMSE", "test_wape_pct": "Test WAPE (%)", "selected": "Selected"})
    st.dataframe(display, width="stretch", hide_index=True)
    st.caption("Model selection was based on the **validation** MAE. The test metrics for other models "
               "are diagnostics only and must not be used to reselect a winner.")

with st.expander("Evaluation methodology & limitations"):
    st.write("**Protocol:** " + summary["evaluation_protocol"])
    st.write("**Forecast definition:** " + summary["forecast_type"])
    for limitation in summary.get("limitations", []):
        st.markdown("- " + str(limitation))

st.caption("DataHealth AI · Phase 18.1 · Synthetic data only · No model training during dashboard browsing")
