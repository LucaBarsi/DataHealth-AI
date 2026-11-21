-- DataHealth AI — Sample parameterized query templates for synthetic data.
-- Run through a client that binds :patient_id, not string concatenation.

-- Synthetic patient name lookup: labels are display-only, IDs remain canonical keys.
SELECT patient_id, first_name, last_name, full_name, gender, birth_date
FROM patients
ORDER BY full_name, patient_id
LIMIT 10;

-- Overall dataset counts
SELECT COUNT(*) AS patient_count FROM patients;
SELECT COUNT(*) AS observation_row_count FROM observation_values;

-- Patient-level overview
SELECT * FROM v_patient_overview WHERE patient_id = :patient_id;

-- Most recent measurement values, including quality flags
SELECT effective_datetime_utc, measurement_display, value_numeric,
       value_text, unit_code, quality_status, quality_flags, observation_id
FROM v_observations
WHERE patient_id = :patient_id
ORDER BY effective_datetime_utc DESC
LIMIT 10;

-- Recent diagnostic reports
SELECT effective_datetime_utc, display, status, report_id
FROM diagnostic_reports
WHERE patient_id = :patient_id
ORDER BY effective_datetime_utc DESC
LIMIT 10;

-- Documents that are preliminary candidates for an eventual RAG workflow
-- NOTE: This view does not grant permission to index or disclose content.
SELECT document_id, document_type, document_date_utc
FROM v_rag_preliminary_document_metadata
WHERE patient_id = :patient_id;

-- Data quality distribution in the Gold Layer
SELECT quality_status, COUNT(*) AS measurement_row_count
FROM observation_values
GROUP BY quality_status;
