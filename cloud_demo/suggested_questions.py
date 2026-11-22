"""Public demonstration questions for the six Clinical Assistant shortcuts.

Questions are routed through the same patient-scoped, parameterized SQL retrieval.
No Qwen call is required to use them in Evidence-only mode.
"""

SUGGESTED_QUESTIONS = (
    ("Latest Vital Signs", "Summarize the latest vital signs with values, units, dates, and source citations."),
    ("Laboratory Results", "Show the most recent laboratory results with values, units, dates, and quality flags. Cite each source."),
    ("Recorded Conditions", "List recorded conditions with their status and dates, citing each available structured source. Do not infer diagnoses."),
    ("Clinical History", "Summarize the most recent clinical note and cite its document source. Distinguish documentation from verified facts."),
    ("Medication Comparison", "Compare medication requests from structured records with the latest clinical note, clearly indicate missing evidence, and cite available sources."),
    ("Compare Vitals & Notes", "Compare recent vital signs with the most recent clinical note, cite each source, and note any missing information."),
)
