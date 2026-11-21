# Phase 11 — Evidence-Linked Clinical Charts

## Scope

The DataHealth AI Clinical Assistant can visualize patient-specific measurement history next to an SQL or hybrid response. This phase **does not** add automated clinical interpretation, forecasting, or diagnostic logic.

## Design decisions

1. **Explicit patient scope:** The chart backend verifies that the selected patient identifier matches the retrieved evidence. SQL history queries are parameterized and opened in SQLite read-only mode.
2. **No reliance on model-generated numbers:** The plotted values are fetched directly from the Gold Layer. The Qwen answer is not parsed for chart values or measurement types.
3. **Evidence-linked suggestions:** A chart selector is offered only for numeric observations present in the answer's structured SQL evidence (`vitals` or `laboratory`). RAG-only answers do not generate numeric charts.
4. **Comparable measurements:** A chart contains exactly one measurement code and its original unit code. Units are never converted, inferred, or pooled across incompatible series.
5. **Flags remain visible:** By default, measurements marked `REVIEW_REQUIRED` are excluded from the plot. Users can explicitly opt in to see them as amber diamonds. This flag is structural, not clinical.
6. **Historical scope:** A question may retrieve just five source rows, but the chart can retrieve up to the 500 latest matching historical records for the selected patient, code, and unit. This is labeled separately and must not be represented as the model's original evidence.
7. **Traceability:** Each charted point retains `observation_id`, recorded timestamp, value, original unit, and quality status. Exact records can be inspected in an expandable table.
8. **Graceful limitations:** A single plotted observation is called a single recorded point, not a trend. RAG-only or nonnumeric responses show no chart.

## Validation

Unit tests cover same-patient filtering, read-only behavior, precise code/unit selection, exclusion and opt-in visibility of flagged values, RAG-only behavior, unsupported SQL topics and integration with the Streamlit entrypoint.

## Future improvements

- Add explicit source-to-claim auditing independent of citation ID validation.
- Support clinician-defined, validated conversion rules only after terminology review.
- Add downloadable, machine-readable metadata for charts and embed them within the full Analytics Dashboard.
- Later assess whether a Power BI view can reproduce the exploratory indicators.

**Safety note:** Synthetic Synthea data only. These charts are not clinical decision support, realtime patient monitoring, normal-range interpretation, or a medical device.
