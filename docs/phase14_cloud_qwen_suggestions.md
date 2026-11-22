# Phase 14 — Cloud Question Routing and Hosted Qwen Preparation

## Objective

Extend the public DataHealth AI prototype from four to **six guided prompts** without breaking the existing Cloud Demo. Prepare the public app for a hosted Qwen service while preserving the independent, no-cost Evidence-only mode.

## Public demo versus local research prototype

| Area | Public Streamlit Demo | Local DataHealth AI |
|---|---|---|
| Patients | Four handwritten illustrative fixtures | 112 synthetic Synthea records |
| Conditions | Fabricated placeholder entries in in-memory SQL | FHIR-derived Gold Layer conditions |
| Structured queries | Fixed parameterized SQLite in memory | Gold Layer SQLite |
| Document lookup | Lexical matching | ChromaDB vector retrieval |
| Model generation | Optional hosted Qwen via managed secrets | Ollama with local Qwen 3.5 4B |
| Public access | Deployed via Streamlit Community Cloud | Not publicly hosted |

## Guided questions and evidence routing

| Suggested question | Automatic retrieval |
|---|---|
| Latest Vital Signs | Observations belonging to a fixed vital-sign code set |
| Laboratory Results | Observations belonging to a fixed laboratory-code set |
| Recorded Conditions | Invented structured `conditions` rows, if present |
| Clinical History | Current patient's note excerpts (lexical match) |
| Medication Comparison | Medication requests and note excerpts; explicitly signal missing data |
| Compare Vitals & Notes | Vital-sign observations and note excerpts |

Routing is deterministic and **does not produce arbitrary SQL**. SQL statements remain parameterized and bound to the selected fictional patient. Condition labels are intentionally non-clinical invented labels, not diagnoses or validated data.

For guided prompts, the source mode automatically follows the type of question. A custom typed question still respects the sidebar's Data source selection. All displayed SQL and document citations retain stable source IDs.

## Optional inference request lifecycle

1. The app constructs patient-scoped evidence from fixed SQL and lexical note matching.
2. If the owner has configured **all** three Streamlit secrets, the app can call a verified HTTPS provider exposing the OpenAI-compatible `/chat/completions` route.
3. The evidence and prompt are sent to the selected third-party provider. No full local Synthea dataset is uploaded.
4. Exact `source_marker` IDs are checked against the rows actually retrieved.
5. If citations are missing or unsupported or the provider call fails, the response falls back to a deterministic Evidence-only summary.
6. The UI displays a limitation notice. Citation ID matching is **not** factual entailment; claim-level clinical checks remain manual.

### Example configuration (documentation only)

```toml
QWEN_API_BASE_URL = "https://your-verified-provider.example/v1"
QWEN_MODEL_ID = "your-provider-specific-qwen-model-id"
QWEN_API_KEY = "YOUR_PRIVATE_KEY"
```

These are **placeholder values**. Never store real keys in this file or in Git. Verify provider availability and price before entering values through Streamlit Community Cloud app settings.

The current Cloud Demo has no server-side authentication for real patient data and must never accept or process real clinical records. Public deployment requires provider-side billing and usage controls; the in-memory session counter is not a global rate limiter.

## Testing

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud_demo_backend.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_cloud_demo_phase14.py" -v
```

The Phase 14 tests cover six distinct prompts, source routing, patient isolation, missing conditions, read-only SQL, laboratory/vital separation, citation IDs and a mocked HTTPS model request. **A real third-party inference request is not made by the test suite.**

## Next steps after the six prompts are deployed

1. Verify the six buttons, evidence labels and analytical charts on the actual public URL.
2. Choose a hosted Qwen service after reviewing costs, model availability, usage quotas and privacy terms; record provider and model version in documentation.
3. Add secrets via Streamlit Community Cloud app settings — not GitHub.
4. Verify hosted inference with only fictitious fixtures; compare exact evidence IDs and hand-check factual claims.
5. Add provider-side spend/usage limits before exposing LLM inference to public visitors.
6. Only consider larger data sources, cloud SQL/vector retrieval and additional services as separate releases.
