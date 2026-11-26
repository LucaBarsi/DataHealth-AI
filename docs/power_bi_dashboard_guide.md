# DataHealth AI — Power BI Analytics Report

## Scope

This deliverable exports **aggregate-only** indicators from the local synthetic Gold Layer SQLite database. The application, Qwen API configuration, and public Streamlit demo are not modified. Power BI is used for **descriptive business intelligence**, not patient care or clinical decision-making.

## Export

At the repository root, run:

```powershell
.\.venv\Scripts\python.exe -m src.export_power_bi --database "data/gold/datahealth.db" --output "reports/power_bi/source_csv"
```

Generated CSVs (UTF-8 with BOM):

| File | Grain | Recommended visual |
|---|---|---|
| `overview.csv` | One entire-dataset row | KPI cards |
| `monthly_encounters.csv` | One calendar month | Line chart |
| `observation_categories.csv` | One observation category | Horizontal bar chart |
| `measurement_frequency.csv` | Code + display + unit | Top 10 measurements bar chart |
| `observation_quality.csv` | One structural quality status | Quality chart |

`export_summary.json` documents counts and caveats. CSVs intentionally omit patient identifiers, names, dates of birth, clinical document bodies, and raw numeric test values.

## Power BI Desktop setup

1. Install Power BI Desktop from Microsoft's official download or Microsoft Store.
2. Open **Home > Get data > Text/CSV** and import each of the five CSVs.
3. In Power Query ensure `month_start` is Date, all count columns are Whole Number, and `year`/`month_number` are Whole Number. Use **Close & Apply**.
4. Build a single page named **Synthetic Healthcare Operations** using a dark navy background (`#0B1424`) and turquoise accent (`#46CFC2`).
5. Suggested layout: KPI cards at top, monthly encounters line chart across the center, two bar charts for categories and top measurements below, structural-quality breakdown at the bottom.
6. Save a local file named `DataHealth_AI_Operations.pbix` in your preferred project directory. Review the report before deciding whether to share `.pbix` publicly.

### Simple DAX measures

```dax
Total Encounters = SUM(monthly_encounters[encounter_count])

Synthetic Patients = MAX(overview[patients_total])

Observation Value Rows = MAX(overview[observation_values_total])

Flagged Value Rows = MAX(overview[flagged_observation_values])

Flagged Share = DIVIDE([Flagged Value Rows], [Observation Value Rows])
```

Format `Flagged Share` as Percentage. These overview measures are **global dataset metrics**, not date-slicer responsive. Do not sum `monthly_unique_patients` across months as a measure of unique patients across the whole period.

## Quality and disclosure

- Source data must be verified as synthetic before export or sharing.
- Do not imply that flags verify clinical validity: they indicate structural checks/review needs.
- `observation_value_rows` is not equivalent to the number of distinct observation events.
- Monthly counts use Gold `start_time_utc` and fill missing calendar months with zero. Encounter records with no timestamp are excluded from the monthly plot and reported as `undated_encounters`.
- Source output lives under `reports/` and should remain ignored by Git (`/.gitignore`). The exporter source code, tests, and documentation can be committed independently.
- No Azure, Spark, Kafka, or Power BI service account is needed for this step.

## Next deliverables

Once the `.pbix` is validated, create a **small local PySpark ETL** demo producing Parquet from known synthetic inputs. Then connect a restricted Azure Data Lake Storage Gen2 account to a limited synthetic sample, with cost controls.
