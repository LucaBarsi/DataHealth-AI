# Cloud Qwen — Safe Diagnostics and Non-thinking Mode

This phase changes only the hosted-model integration of the public, fictional Streamlit demo. The existing evidence retrieval and exact citation guard stay in place.

The free Mixlayer Qwen 3.5 4B model has an optional reasoning mode; the request now sets `reasoning_effort: none` to obtain final answer text directly. `max_tokens` is set to 900 to reduce empty/unfinished outputs. The application **does not** infer clinical truths from a technically valid model response.

When inference fails or an answer contains invalid citation IDs, the app retains deterministic `evidence_only_answer(evidence)` rather than displaying unsupported generated content. It annotates the result with a coarse diagnostic code. HTTP response bodies and credentials are not printed or surfaced.

Approved citations are generated from the selected fictional patient's SQL and note records. The citation checker requires at least one exact approved marker; unknown, shortened or fabricated markers trigger the evidence-only fallback.

## Tested invariants

- The Mixlayer documented URL maps to `/v1/chat/completions`.
- Literal local/private endpoints are blocked.
- Hosted requests include the correct model, evidence and direct-answer mode.
- HTTP errors and empty completions produce non-sensitive diagnostic codes.
- The Streamlit UI displays only the diagnostic code, not upstream response bodies or keys.

No live provider connection was executed as part of the packaged tests. The deployed Streamlit instance must be checked independently.
