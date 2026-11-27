r"""DataHealth AI — Clinical Assistant landing page.

Launch from the project root:
    .\.venv\Scripts\python.exe -m streamlit run Clinical_Assistant.py --server.address 127.0.0.1

Synthetic Synthea records only. This prototype is not for clinical use.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path
import os
import sqlite3

import plotly.graph_objects as go

import streamlit as st

from src import contextual_charts, hybrid_assistant, ui_backend

# Deployment wrapper opts into hosted SQL inference; direct local startup stays on Ollama.
HOSTED_SQL_MODE = os.environ.get("DATAHEALTH_HOSTED_SQL") == "1"


def hosted_answer_generator():
    """Create a guarded hosted generator without disclosing secret values."""
    from cloud_demo.usage_controls import SharedProcessBudget
    from src.hosted_qwen import HostedQwenSettings, generate_guarded_hosted_answer

    @st.cache_resource(show_spinner=False)
    def hosted_call_budget():
        return SharedProcessBudget(max_calls=24, window_seconds=3600)

    try:
        api_key = str(st.secrets.get("QWEN_API_KEY", "")).strip()
        api_base = str(st.secrets.get("QWEN_API_BASE_URL", "https://mixlayer.ai/v1")).strip()
        model_id = str(st.secrets.get("QWEN_MODEL_ID", "qwen/qwen3.5-4b-free")).strip()
    except (KeyError, FileNotFoundError):
        api_key, api_base, model_id = "", "https://mixlayer.ai/v1", "qwen/qwen3.5-4b-free"
    settings = HostedQwenSettings(api_key=api_key, api_base=api_base, model_id=model_id)

    def generate(evidence: dict) -> dict:
        return generate_guarded_hosted_answer(
            evidence,
            settings=settings,
            session_state=st.session_state,
            shared_budget=hosted_call_budget(),
        )

    return generate

st.set_page_config(
    page_title="DataHealth AI | Clinical Intelligence Workspace",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATABASE = Path("data/gold/datahealth.db")
INDEX = Path("data/vectorstore/chroma")
CSS_PATH = Path(__file__).resolve().parent / "assets" / "datahealth.css"

if CSS_PATH.is_file():
    st.markdown(f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


@st.cache_data(ttl=60, show_spinner=False)
def load_patients(database_path: str) -> list[dict]:
    """Load the existing patient-scoped selection data from the Gold Layer."""
    return ui_backend.list_synthetic_patients(Path(database_path))


def evidence_panel(result: dict) -> None:
    """Display auditable sources without modifying their raw content."""
    evidence = result["evidence"]
    response = result["response"]
    with st.expander("Sources, quality flags & retrieved evidence", expanded=False):
        m1, m2, m3 = st.columns(3)
        m1.metric("SQL records", evidence.get("sql_record_count", 0))
        m2.metric("RAG passages", evidence.get("rag_passage_count", 0))
        m3.metric("Citation guard", response.get("status", "Unknown"))
        if response.get("warning"):
            st.caption(response["warning"])
        rows = ui_backend.source_summary(evidence)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("No eligible evidence was retrieved for this question and patient.")
        with st.expander("Inspect raw evidence", expanded=False):
            st.json({
                "sql_evidence": evidence.get("sql_evidence", []),
                "rag_evidence": evidence.get("rag_evidence", []),
            })



def format_recorded_time_utc(raw_timestamp: object) -> str:
    """Format a recorded UTC timestamp without silently changing naive dates."""
    if not isinstance(raw_timestamp, str) or not raw_timestamp:
        return "Not recorded"
    try:
        timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
    except ValueError:
        return raw_timestamp
    if timestamp.tzinfo is None:
        return raw_timestamp
    return timestamp.astimezone(timezone.utc).strftime("%b %d, %Y · %H:%M:%S UTC")


def contextual_chart_panel(result: dict, patient_id: str, *, key: str) -> None:
    """Show a read-only patient trend alongside the answer's SQL sources.

    Chart data comes from SQLite, never from the Qwen response text. Distinct
    measurement codes or units are never combined into one trend.
    """
    evidence = result.get("evidence") or {}
    try:
        choices = contextual_charts.chart_targets(evidence, patient_id)
    except ValueError:
        st.error("The retrieved patient does not match the selected patient. No chart shown.")
        return
    if not choices:
        # A narrative-only answer cannot support a numeric measurement trend.
        return

    with st.expander("Explore measurements from this answer", expanded=True):
        st.caption(
            "Interactive historical chart from read-only Gold Layer measurements. "
            "It is linked to the SQL evidence, not to the model's generated text."
        )
        selected_index = st.selectbox(
            "Measurement and unit",
            options=range(len(choices)),
            format_func=lambda i: choices[i].label,
            key=f"linked_measurement_{key}",
        )
        chosen = choices[selected_index]
        show_flagged = st.checkbox(
            "Include records flagged for review",
            value=False,
            help="Flagged rows are not automatically corrected or clinically validated.",
            key=f"linked_flagged_{key}",
        )
        try:
            series = contextual_charts.chart_series(
                DATABASE, evidence, patient_id, chosen,
                include_flagged=show_flagged, limit=500,
            )
        except (ValueError, FileNotFoundError, RuntimeError, sqlite3.Error) as exc:
            st.error(f"Unable to load the selected synthetic measurement: {exc}")
            return
        rows = series["rows"]
        if not rows:
            st.info("No eligible numeric measurements. Enable flagged records to inspect review-required values.")
            return

        if len(rows) == 1:
            # A single eligible measurement is not a longitudinal trend.
            # Keep the source timestamp, observation ID, and quality status visible.
            record = rows[0]
            with st.container(border=True):
                st.caption("SINGLE RECORDED MEASUREMENT")
                value_col, details_col = st.columns([2, 1])
                with value_col:
                    value_label = f"{record['value_numeric']} {chosen.unit}".strip()
                    st.metric(chosen.display, value_label)
                    st.caption("Only one eligible measurement is available; no longitudinal trend can be shown.")
                with details_col:
                    st.markdown("**Recorded time**")
                    st.write(format_recorded_time_utc(record.get("effective_datetime_utc")))
                    st.markdown("**Data quality**")
                    quality_status = str(record.get("quality_status") or "Not specified")
                    if quality_status == "REVIEW_REQUIRED":
                        st.warning("REVIEW_REQUIRED")
                    else:
                        st.caption(quality_status)
                    if record.get("quality_flags"):
                        st.caption(f"Quality flags: {record['quality_flags']}")
                    st.caption(f"Observation ID: `{record['observation_id']}`")
        else:
            passing = [r for r in rows if r.get("quality_status") != "REVIEW_REQUIRED"]
            flagged = [r for r in rows if r.get("quality_status") == "REVIEW_REQUIRED"]
            fig = go.Figure()
            if passing:
                fig.add_trace(go.Scatter(
                    x=[r["effective_datetime_utc"] for r in passing],
                    y=[r["value_numeric"] for r in passing],
                    mode="lines+markers" if len(passing) > 1 else "markers",
                    marker={"color": "#4ADAC5", "size": 9},
                    line={"color": "#4ADAC5", "width": 2},
                    name="Structural checks passed",
                    customdata=[r["observation_id"] for r in passing],
                    hovertemplate="%{x}<br>Value: %{y}<br>Observation ID: %{customdata}<extra></extra>",
                ))
            if flagged:
                fig.add_trace(go.Scatter(
                    x=[r["effective_datetime_utc"] for r in flagged],
                    y=[r["value_numeric"] for r in flagged],
                    mode="markers",
                    marker={"color": "#F2C078", "size": 12, "symbol": "diamond"},
                    name="Review required",
                    customdata=[r["observation_id"] for r in flagged],
                    hovertemplate="%{x}<br>Value: %{y}<br>Review required<br>Observation ID: %{customdata}<extra></extra>",
                ))
            fig.update_layout(
                height=370, paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font={"color": "#C5DBEE"},
                margin={"l": 64, "r": 24, "t": 20, "b": 75},
                xaxis={
                    "title": {"text": "Recorded time (UTC)", "standoff": 20},
                    "showgrid": False,
                    "type": "date",
                    "tickformat": "%b %d<br>%Y",
                    "nticks": 5,
                    "automargin": True,
                },
                yaxis={
                    "title": {"text": chosen.unit or "Unit not recorded", "standoff": 16},
                    "gridcolor": "rgba(150,185,220,.14)",
                    "automargin": True,
                },
                showlegend=bool(flagged and passing),
            )
            st.plotly_chart(fig, width="stretch", theme=None, key=f"linked_chart_{key}",
                            config={"displaylogo": False, "scrollZoom": False})
        if series["truncated"]:
            st.warning("Chart limited to the most recent 500 matching records. It does not show the full history.")
        st.caption(
            f"{len(rows)} records · Code: {chosen.code} · Unit: {chosen.unit or 'not recorded'} · "
            "Sources: Gold Layer observation IDs. Structural checks do not establish clinical validity."
        )
        with st.expander("Inspect exact observations", expanded=False):
            st.dataframe(rows, width="stretch", hide_index=True)
        if Path("pages/1_Analytics_Dashboard.py").is_file():
            st.page_link("pages/1_Analytics_Dashboard.py", label="Open full Analytics Dashboard", icon="📊")


with st.sidebar:
    st.markdown(
        '<div class="dh-sidebar-logo"><div class="dh-logo-mark">DH<span>+</span></div>'
        '<div><div class="dh-sidebar-wordmark">DataHealth <span>AI</span></div>'
        '<div class="dh-sidebar-caption">' + ('HOSTED SQL TEST' if HOSTED_SQL_MODE else 'LOCAL RESEARCH WORKSPACE') + '</div></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="dh-sidebar-section">PATIENT CONTEXT</div>', unsafe_allow_html=True)

try:
    patients = load_patients(str(DATABASE))
except (ValueError, FileNotFoundError, sqlite3.Error) as exc:
    st.error(f"Unable to load the Gold Layer: {exc}")
    st.info("Build the Gold SQLite database and launch Streamlit from the project root.")
    st.stop()

if not patients:
    st.error("No synthetic patients were found in the Gold Layer.")
    st.stop()

patient_map = {str(item["patient_id"]): item for item in patients}
patient_ids = list(patient_map)

with st.sidebar:
    selected_patient_id = st.selectbox(
        "Synthetic patient",
        options=patient_ids,
        format_func=lambda patient_id: (
            f"{patient_map[patient_id].get('full_name') or 'Unnamed'} · {patient_id[:8]}"
        ),
        key="selected_patient_id",
    )
    patient = patient_map[selected_patient_id]
    selected_name = str(patient.get("full_name") or "Unnamed synthetic patient")
    st.markdown(
        '<div class="dh-sidebar-patient">'
        f'<div class="dh-sidebar-patient-name">{escape(selected_name)}</div>'
        '<div class="dh-sidebar-patient-meta">SYNTHETIC PATIENT · READ-ONLY</div>'
        f'<div class="dh-sidebar-patient-detail">Sex: {escape(str(patient.get("gender") or "Not specified"))}</div>'
        f'<div class="dh-sidebar-patient-detail">Birth date: {escape(str(patient.get("birth_date") or "Not specified"))}</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.caption(f"Patient ID: `{selected_patient_id}`")
    st.markdown('<div class="dh-sidebar-section">RETRIEVAL SETTINGS</div>', unsafe_allow_html=True)
    mode = st.selectbox(
        "Retrieval mode",
        options=["sql"] if HOSTED_SQL_MODE else list(hybrid_assistant.MODES),
        index=0,
    )
    if HOSTED_SQL_MODE:
        st.caption("Hosted SQL preview only; semantic RAG is not enabled without compatible embeddings.")
    topic_value = st.selectbox(
        "SQL topic", options=["Auto", *hybrid_assistant.SQL_TOPICS], index=0,
        disabled=(mode == "rag"),
    )
    topic = None if topic_value == "Auto" or mode == "rag" else topic_value
    sql_limit = st.slider("Maximum SQL records per topic", 1, 10, 5)
    top_k = st.slider("Maximum RAG passages", 1, 5, 2)
    st.caption("Read-only SQL queries · Patient-scoped document retrieval")
    if st.button("Clear conversation", use_container_width=True):
        st.session_state["chat_messages"] = []
        st.rerun()
    st.markdown(
        '<div class="dh-sidebar-footer">'
        '<span class="dh-status-dot"></span> LOCAL DEMO<br>'
        'Synthetic data only. No real clinical use.'
        '</div>',
        unsafe_allow_html=True,
    )

# Important: switching patients clears the old conversation in the existing backend.
ui_backend.sync_patient_session(st.session_state, selected_patient_id)

st.markdown(
    '<section class="dh-hero">'
    '<div class="dh-kicker">DATAHEALTH AI <span> / </span> CLINICAL INTELLIGENCE</div>'
    '<h1>Data that connects.<br><em>Insights you can trace.</em></h1>'
    '<p>Explore synthetic clinical records across structured data and patient notes, '
    + ('with citation-guarded hosted Qwen for SQL evidence.</p>' if HOSTED_SQL_MODE
       else 'with source-aware answers powered by local AI.</p>')
    '<div class="dh-hero-tags"><span>SQL</span><span>RAG</span><span>Qwen 3.5 4B</span>'
    '<span>Patient-scoped retrieval</span></div>'
    '</section>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="dh-disclaimer"><strong>SYNTHETIC DATA ONLY</strong> · Educational prototype. '
    'Not for clinical decisions, diagnosis, treatment, or real patient data. '
    'Citation IDs are not evidence of clinical validity.</div>',
    unsafe_allow_html=True,
)

st.markdown('<div class="dh-eyebrow">ACTIVE PATIENT WORKSPACE</div>', unsafe_allow_html=True)
st.subheader(selected_name)

col1, col2, col3 = st.columns(3)
col1.metric("Synthetic patient records", len(patients))
col2.metric("Retrieval mode", mode.upper())
col3.metric("Inference", "Hosted Qwen SQL preview" if HOSTED_SQL_MODE else "Local Qwen 3.5 4B")

st.markdown('<div class="dh-section-title">Ask a clinical data question</div>', unsafe_allow_html=True)
st.caption(
    "Select a suggested question below or write your own. "
    "Each answer is restricted to the selected synthetic patient."
)

# Suggested questions help first-time users explore safe, traceable retrieval workflows.
# Routing follows the currently selected mode; in AUTO the deterministic router
# selects SQL, RAG or both based on the question. No LLM-generated SQL is used.
SUGGESTED_QUESTIONS = (
    ("Latest vital signs", "Summarize the latest vital signs with values, units, dates, and source citations.", "sql"),
    ("Laboratory results", "Show the most recent laboratory test results with values, units, dates, and quality flags. Cite each source.", "sql"),
    ("Recorded conditions", "List the documented conditions for this patient with available dates and sources. Do not infer diagnoses.", "sql"),
    ("Clinical history", "Summarize the most recent clinical note and cite its document source. Distinguish documentation from verified facts.", "rag"),
    ("Medication comparison", "Compare medication requests from structured records with the most recent clinical note. Clearly indicate missing evidence and cite sources.", "hybrid"),
    ("Compare vitals & notes", "Compare recent vital signs with the most recent clinical note, citing each source and noting any missing information.", "hybrid"),
)

# Avoid offering an example that cannot be fully served by the selected retrieval mode.
if mode == "sql":
    visible_suggestions = [item for item in SUGGESTED_QUESTIONS if item[2] == "sql"]
elif mode == "rag":
    visible_suggestions = [item for item in SUGGESTED_QUESTIONS if item[2] == "rag"]
else:
    visible_suggestions = list(SUGGESTED_QUESTIONS)

st.markdown('<div class="dh-eyebrow">SUGGESTED QUESTIONS · CLICK TO ASK</div>', unsafe_allow_html=True)
quick_prompt = None
for offset in range(0, len(visible_suggestions), 3):
    suggestion_columns = st.columns(3)
    for index, (label, prompt, category) in enumerate(visible_suggestions[offset:offset + 3]):
        with suggestion_columns[index]:
            if st.button(
                label,
                use_container_width=True,
                key=f"suggestion_{category}_{offset + index}",
                help=prompt,
            ):
                quick_prompt = prompt
st.caption("Tip: Use AUTO mode to let the application select SQL, RAG, or both. Results are synthetic and not clinical advice.")

for message_index, message in enumerate(st.session_state["chat_messages"]):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant" and message.get("result"):
            evidence_panel(message["result"])
            contextual_chart_panel(message["result"], selected_patient_id, key=f"history_{message_index}")

st.markdown('<div class="dh-chat-anchor"></div>', unsafe_allow_html=True)
typed_question = st.chat_input("Ask about the selected synthetic patient…", max_chars=1500)
question = typed_question or quick_prompt
if question:
    st.session_state["chat_messages"].append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Retrieving patient-scoped evidence and validating source IDs…"):
            try:
                result = ui_backend.ask_synthetic_patient(
                    database=DATABASE,
                    index_dir=INDEX,
                    patient_id=selected_patient_id,
                    question=question,
                    mode=mode,
                    topic=topic,
                    sql_limit=sql_limit,
                    top_k=top_k,
                    answer_generator=hosted_answer_generator() if HOSTED_SQL_MODE else None,
                    allow_rag=not HOSTED_SQL_MODE,
                )
            except (ValueError, FileNotFoundError, RuntimeError, sqlite3.Error, OSError) as exc:
                st.error(f"Unable to complete this request: {exc}")
            else:
                answer = result["response"]["answer"]
                st.markdown(answer)
                st.caption(
                    f"Citation guard: {result['response']['status']} · "
                    "Source ID validation does not establish clinical accuracy."
                )
                if HOSTED_SQL_MODE:
                    reason = result["response"].get("reason", "")
                    if reason and reason != "HOSTED_QWEN":
                        st.info(f"Hosted inference status: {reason}. Evidence-only output shown.")
                evidence_panel(result)
                contextual_chart_panel(result, selected_patient_id, key=f"new_{len(st.session_state['chat_messages'])}")
                st.session_state["chat_messages"].append({
                    "role": "assistant", "content": answer, "result": result,
                })

st.markdown(
    '<div class="dh-app-footer">'
    'DataHealth AI <span>·</span> Local prototype <span>·</span> '
    ('Not authenticated <span>·</span> Not approved for public deployment'
     if HOSTED_SQL_MODE else
     'Not authenticated <span>·</span> Keep on localhost and never use real patient data')
    '</div>',
    unsafe_allow_html=True,
)
