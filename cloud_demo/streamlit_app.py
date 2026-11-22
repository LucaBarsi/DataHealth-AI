"""DataHealth AI public cloud demo — independent from the local application.

Local:   python -m streamlit run cloud_demo/streamlit_app.py
Cloud:   entrypoint = cloud_demo/streamlit_app.py

Uses invented sample fixtures in memory. Hosted Qwen is OPTIONAL and is only
activated when the deployer supplies a supported endpoint and secrets.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
import json
import os
import sqlite3
import sys

import plotly.graph_objects as go
import streamlit as st

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from demo_backend import (  # noqa: E402
    allowed_markers, citation_check, counts, evidence_only_answer, list_patients,
    load_fixtures, measurement_options, open_demo_database, retrieve_evidence, route_question, series_for_patient,
)
from remote_inference import RemoteInferenceError, remote_qwen_answer  # noqa: E402
from suggested_questions import SUGGESTED_QUESTIONS  # noqa: E402
from usage_controls import SharedProcessBudget, UsagePolicy, reserve_hosted_call  # noqa: E402
from scope_validation import negative_claim_check, retrieval_scope  # noqa: E402
from semantic_retrieval import MODEL_NAME, load_retriever  # noqa: E402

st.set_page_config(
    page_title="DataHealth AI | Public Demo",
    page_icon="🧬", layout="wide", initial_sidebar_state="expanded",
)
css_file = ROOT / "assets" / "datahealth.css"
if css_file.is_file():
    st.markdown("<style>" + css_file.read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)
st.markdown("""
<style>
.dh-cloud-kpi{font-size:.77rem;color:#bad1e5;letter-spacing:.08em}
.dh-cloud-pill{display:inline-block;border:1px solid #31516d;border-radius:999px;padding:.24rem .65rem;color:#9fdacc;font-size:.75rem;margin-right:.35rem}
.dh-cloud-quiet{color:#a0b9c9;font-size:.82rem}
</style>
""", unsafe_allow_html=True)

@st.cache_data(show_spinner=False)
def fixtures() -> dict:
    return load_fixtures(HERE / "sample_records.json")


@st.cache_resource(show_spinner=False)
def semantic_engine():
    """Load ONNX once per process, lazily on a document question (opt-in)."""
    return load_retriever(fixtures(), index_path=HERE / "semantic_index.json")


def semantic_enabled() -> bool:
    """Only project owner may opt in; never load the model for visitors by default."""
    value = secret("SEMANTIC_RAG_ENABLED") or os.getenv("SEMANTIC_RAG_ENABLED", "")
    return str(value).lower() in ("true", "1", "yes", "on")

# Shared across sessions in one Streamlit server process only. This best-effort
# limit resets on deployment/restart and is NOT an account-level spending cap.
@st.cache_resource(show_spinner=False)
def hosted_budget() -> SharedProcessBudget:
    return SharedProcessBudget(max_calls=24, window_seconds=3600)

HOSTED_POLICY = UsagePolicy(session_max_calls=6, session_cooldown_seconds=15,
                            process_max_calls=24, process_window_seconds=3600)


def secret(name: str) -> str:
    try:
        value = st.secrets.get(name, "")
        return str(value).strip() if value is not None else ""
    except Exception:  # StreamlitSecretNotFoundError when no secrets file exists
        return ""


def show_evidence(evidence: dict) -> None:
    with st.expander("Inspect retrieved sources and quality metadata", expanded=False):
        st.caption("These are patient-scoped fixtures; citation IDs identify the sample rows only.")
        scope = retrieval_scope(evidence)["categories"]
        for label, key in (("Structured measurements", "observations"),
                           ("Recorded conditions", "conditions"), ("Medication requests", "medications"), ("Clinical notes", "notes")):
            st.markdown("**" + label + "**")
            if evidence.get(key):
                st.dataframe(evidence[key], width="stretch", hide_index=True)
            elif not scope[key]["queried"]:
                st.caption("Not queried for this question; absence of rows here is not proof of absence.")
            else:
                st.caption("Queried, but no matching records were retrieved in this scope.")
        st.caption("Only selected evidence was retrieved. Do not infer absence of other records.")
        method = evidence.get("document_retrieval", {}).get("method", "legacy_keyword")
        if method == "semantic_vector_cosine":
            st.caption("Note retrieval: patient-scoped FastEmbed ONNX cosine search. Similarity is not factual support.")
        elif method == "lexical_keywords":
            st.caption("Note retrieval: keyword matching (semantic search off or unavailable).")
        else:
            st.caption("Clinical notes were not queried.")


def chart_panel(conn: sqlite3.Connection, patient_id: str, *, key: str) -> None:
    options = measurement_options(conn, patient_id)
    if not options:
        st.info("No numerical observations are available for this demo patient.")
        return
    chosen_idx = st.selectbox("Measurement (code and unit kept separate)",
                              range(len(options)),
                              format_func=lambda i: f"{options[i]['display']} · {options[i]['code']} · {options[i]['unit']}",
                              key="measurement_" + key)
    chosen = options[chosen_idx]
    flagged = st.checkbox("Include observations flagged for review", value=False, key="flagged_" + key)
    rows = series_for_patient(conn, patient_id, chosen["code"], chosen["unit"], include_flagged=flagged)
    if not rows:
        st.info("No eligible measurements. Enable flagged observations to inspect flagged values.")
        return
    good = [r for r in rows if r["quality_status"] == "PASS_STRUCTURAL_CHECKS"]
    review = [r for r in rows if r["quality_status"] != "PASS_STRUCTURAL_CHECKS"]
    fig = go.Figure()
    for group, color, label, symbol in ((good, "#4ADAC5", "Structural checks passed", "circle"),
                                        (review, "#F2C078", "Review required", "diamond")):
        if group:
            fig.add_trace(go.Scatter(
                x=[r["timestamp"] for r in group], y=[r["value"] for r in group],
                mode="lines+markers" if len(group)>1 and not review else "markers",
                line={"color": color, "width": 2}, marker={"color": color, "size": 10, "symbol": symbol},
                name=label, customdata=[r["observation_id"] for r in group],
                hovertemplate="Time: %{x}<br>Value: %{y}<br>Source: %{customdata}<extra></extra>"
            ))
    fig.update_layout(height=350, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font={"color": "#D3E6F6"},
                      margin={"l": 18, "r": 16, "t": 18, "b": 30},
                      xaxis={"title": "Recorded time (UTC)", "showgrid": False},
                      yaxis={"title": chosen["unit"], "gridcolor": "rgba(153,188,220,.15)"},
                      showlegend=bool(review))
    st.plotly_chart(fig, width="stretch", key="plot_" + key,
                    config={"displaylogo": False, "scrollZoom": False})
    if len(rows) == 1:
        st.caption("Only one point is available; no longitudinal trend can be inferred.")
    st.caption("Source: illustrative in-memory SQL fixtures. Structural checks ≠ clinical validation.")
    with st.expander("Inspect chart data"):
        st.dataframe(rows, width="stretch", hide_index=True)


data = fixtures()
conn = open_demo_database(data)
patients = list_patients(conn)
patient_map = {p["patient_id"]: p for p in patients}
totals = counts(conn)

api_base = secret("QWEN_API_BASE_URL")
api_key = secret("QWEN_API_KEY")
model_id = secret("QWEN_MODEL_ID")
remote_ready = bool(api_base and api_key and model_id and "qwen" in model_id.lower())

with st.sidebar:
    st.markdown(
        '<div class="dh-sidebar-logo"><div class="dh-logo-mark">DH<span>+</span></div>'
        '<div><div class="dh-sidebar-wordmark">DataHealth <span>AI</span></div>'
        '<div class="dh-sidebar-caption">PUBLIC DEMO · FICTIONAL FIXTURES</div></div></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="dh-sidebar-section">PATIENT CONTEXT</div>', unsafe_allow_html=True)
    selected_id = st.selectbox("Synthetic demo patient", options=list(patient_map),
                               format_func=lambda pid: patient_map[pid]["full_name"] + " · " + pid)
    selected = patient_map[selected_id]
    st.markdown(
        '<div class="dh-sidebar-patient">'
        f'<div class="dh-sidebar-patient-name">{escape(selected["full_name"])}</div>'
        '<div class="dh-sidebar-patient-meta">ILLUSTRATIVE DATA · NOT SYNTHEA EXPORT</div>'
        f'<div class="dh-sidebar-patient-detail">ID: {escape(selected_id)}</div>'
        '</div>', unsafe_allow_html=True)
    st.markdown('<div class="dh-sidebar-section">RETRIEVAL SETTINGS</div>', unsafe_allow_html=True)
    retrieval = st.selectbox("Data source", ["Auto", "Measurements", "Clinical notes", "Combined"])
    mode = {"Auto":"auto", "Measurements":"measurements", "Clinical notes":"notes", "Combined":"combined"}[retrieval]
    st.caption("Read-only SQLite in memory · Optional semantic note retrieval")
    st.caption("Document retrieval: ONNX semantic search (experimental)" if semantic_enabled() else
               "Document retrieval: keyword search (stable default)")
    st.markdown('<div class="dh-sidebar-section">INFERENCE MODE</div>', unsafe_allow_html=True)
    st.markdown("**Hosted Qwen configured**" if remote_ready else "**Evidence-only preview**")
    st.caption("Hosted model available only when the project owner configures a provider and API key." if not remote_ready else
               "A third-party provider processes the selected fictional question and evidence; limits and possible charges apply.")
    if remote_ready:
        st.caption("Demo limits: 6 hosted requests/session, 15s cooldown, and "
                   "24 requests/hour per running server process. "
                   "These are best-effort, not provider billing protections.")
    if st.button("Clear conversation", width="stretch"):
        st.session_state["messages"] = []
        st.rerun()
    st.markdown('<div class="dh-sidebar-footer"><span class="dh-status-dot"></span> PUBLIC SAMPLE DATA ONLY</div>', unsafe_allow_html=True)

if st.session_state.get("active_demo_patient") != selected_id:
    st.session_state["active_demo_patient"] = selected_id
    st.session_state["messages"] = []

st.markdown(
    '<section class="dh-hero"><div class="dh-kicker">DATAHEALTH AI <span> / </span> CLOUD DEMO</div>'
    '<h1>Data that connects.<br><em>Insights you can trace.</em></h1>'
    '<p>A lightweight public preview of clinical data exploration using invented fixtures. '
    'The full local prototype retains its original SQLite, ChromaDB and Ollama stack.</p>'
    '<div class="dh-hero-tags"><span>Public sample</span><span>Fixed SQL</span>'
    '<span>Document search</span><span>Optional hosted Qwen</span></div></section>', unsafe_allow_html=True,
)
st.warning("SYNTHETIC ILLUSTRATIVE FIXTURES ONLY. Educational software preview — no real patient data, diagnoses, care recommendations or clinical validation.")

col_a, col_b, col_c, col_d = st.columns(4)
col_a.metric("Demo patients", totals["patients"])
col_b.metric("SQL observations", totals["observations"])
col_c.metric("Clinical notes", totals["notes"])
col_d.metric("Inference", "Hosted Qwen" if remote_ready else "Evidence only")

chat_tab, analytics_tab = st.tabs(["Clinical Assistant", "Analytics Dashboard"])
with chat_tab:
    st.subheader("Ask about a selected synthetic patient")
    st.caption("Answers use only this patient's demo fixtures. In Evidence-only mode, no LLM is called.")
    st.markdown("**Suggested questions**")
    st.caption("Click any prompt to ask about the selected fictional patient. Suggested prompts use automatic source routing.")
    suggestions = SUGGESTED_QUESTIONS
    choice = None
    buttons = st.columns(3)
    for i, (label, question) in enumerate(suggestions):
        with buttons[i % 3]:
            if st.button(label, key="question_"+str(i), width="stretch", help=question):
                choice = question
    for idx, item in enumerate(st.session_state.get("messages", [])):
        with st.chat_message(item["role"]):
            st.markdown(item["text"])
            if item["role"] == "assistant" and item.get("evidence"):
                st.caption("Retrieval status: " + item.get("status", "UNSPECIFIED") + " · Citation IDs do not prove factual support.")
                st.caption("Notes: " + item["evidence"].get("document_retrieval", {}).get("method", "unknown"))
                if item.get("fallback_reason"):
                    st.caption("Hosted-model diagnostic: " + item["fallback_reason"])
                show_evidence(item["evidence"])
    typed = st.chat_input("Ask about the selected synthetic patient…", max_chars=1000)
    query = typed or choice
    if query:
        # Suggestions use reliable auto routing regardless of the custom sidebar mode.
        # Custom typed questions continue to respect the sidebar selection.
        effective_mode = "auto" if choice and not typed else mode
        semantic_search = None
        if semantic_enabled() and route_question(query, effective_mode)[1]:
            try:
                # Model download / index check happens only for document questions.
                semantic_search = semantic_engine().search
            except Exception:
                # Keep the public demo operational if the small model is unavailable.
                st.info("Semantic retrieval is unavailable; using keyword search for this request.")
        evidence = retrieve_evidence(conn, selected_id, query, mode=effective_mode,
                                     semantic_search=semantic_search)
        response = evidence_only_answer(evidence)
        status = "EVIDENCE_ONLY"
        fallback_reason = None
        if remote_ready and allowed_markers(evidence):
            allowed, usage_reason = reserve_hosted_call(
                st.session_state, hosted_budget(), policy=HOSTED_POLICY
            )
            if not allowed:
                status = "EVIDENCE_ONLY_FALLBACK"
                fallback_reason = usage_reason
                st.info("Hosted request not sent (" + usage_reason + "). "
                        "The evidence-only response remains available.")
            else:
                try:
                    generated = remote_qwen_answer(evidence=evidence, question=query,
                        api_base=api_base, api_key=api_key, model_id=model_id)
                    check = citation_check(generated, evidence)
                    if check["valid"]:
                        scope_check = negative_claim_check(generated, evidence)
                        if scope_check["valid"]:
                            response = generated
                            status = "CITATION_IDS_VALID"
                        else:
                            status = "EVIDENCE_ONLY_FALLBACK"
                            fallback_reason = "EVIDENCE_SCOPE_VIOLATION"
                    else:
                        status = "EVIDENCE_ONLY_FALLBACK"
                        fallback_reason = "CITATION_CHECK_FAILED"
                except RemoteInferenceError as exc:
                    status = "EVIDENCE_ONLY_FALLBACK"
                    fallback_reason = exc.code
                except ValueError:
                    status = "EVIDENCE_ONLY_FALLBACK"
                    fallback_reason = "INVALID_INFERENCE_CONFIGURATION"
        elif remote_ready:
            status = "NO_ELIGIBLE_EVIDENCE"
        st.session_state["messages"].extend([
            {"role":"user", "text":query},
            {"role":"assistant", "text":response, "status":status,
             "fallback_reason":fallback_reason, "evidence":evidence},
        ])
        with st.chat_message("user"):
            st.markdown(query)
        with st.chat_message("assistant"):
            st.markdown(response)
            st.caption("Retrieval status: " + status + " · Exact citation IDs are not proof of factual support.")
            st.caption("Notes: " + evidence.get("document_retrieval", {}).get("method", "unknown"))
            if fallback_reason:
                st.caption("Hosted-model diagnostic: " + fallback_reason)
            show_evidence(evidence)

with analytics_tab:
    st.subheader("Explore the illustration dataset")
    st.caption("These records are handcrafted public demonstration fixtures, not the 112-patient local Synthea Gold Layer.")
    st.caption(f"Condition records in scope: {totals['conditions']} · Entries are placeholder labels, not clinical diagnoses.")
    chart_panel(conn, selected_id, key="main")
    with st.expander("Dataset inventory"):
        st.json({"dataset_name": data["dataset_name"], "provenance": data["dataset_provenance"], "records": totals})

st.markdown(
    '<div class="dh-app-footer">DataHealth AI · Public proof of concept · '
    'Not authenticated for real patient use · Local production features are not available in this cloud preview</div>',
    unsafe_allow_html=True,
)
conn.close()
