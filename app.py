r"""DataHealth AI — branded local research workspace.

Launch from the project root:
    .\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1

Synthetic Synthea records only. This prototype is not for clinical use.
"""
from __future__ import annotations

from html import escape
import sqlite3
from pathlib import Path

import streamlit as st

from src import hybrid_assistant, ui_backend

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


with st.sidebar:
    st.markdown(
        '<div class="dh-sidebar-logo"><div class="dh-logo-mark">DH<span>+</span></div>'
        '<div><div class="dh-sidebar-wordmark">DataHealth <span>AI</span></div>'
        '<div class="dh-sidebar-caption">LOCAL RESEARCH WORKSPACE</div></div></div>',
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
    mode = st.selectbox("Retrieval mode", options=list(hybrid_assistant.MODES), index=0)
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
    'with source-aware answers powered by local AI.</p>'
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
col3.metric("Local language model", "Qwen 3.5 4B")

st.markdown('<div class="dh-section-title">Ask a clinical data question</div>', unsafe_allow_html=True)
st.caption("Start with a suggested question or type your own. Answers are restricted to the selected synthetic patient.")

quick_prompt = None
p1, p2, p3 = st.columns(3)
with p1:
    if st.button("↗  Latest vital signs", use_container_width=True, key="quick_vitals"):
        quick_prompt = "Summarize the latest vital signs with values, units, dates, and citations."
with p2:
    if st.button("↗  Recent clinical note", use_container_width=True, key="quick_note"):
        quick_prompt = "Summarize the most recent clinical note and cite the source."
with p3:
    if st.button("↗  Compare sources", use_container_width=True, key="quick_compare"):
        quick_prompt = (
            "Compare recent vital signs with the most recent clinical note. "
            "Cite each source and clearly state any missing evidence."
        )

for message in st.session_state["chat_messages"]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant" and message.get("result"):
            evidence_panel(message["result"])

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
                evidence_panel(result)
                st.session_state["chat_messages"].append({
                    "role": "assistant", "content": answer, "result": result,
                })

st.markdown(
    '<div class="dh-app-footer">'
    'DataHealth AI <span>·</span> Local prototype <span>·</span> '
    'Not authenticated <span>·</span> Keep on localhost and never use real patient data'
    '</div>',
    unsafe_allow_html=True,
)
